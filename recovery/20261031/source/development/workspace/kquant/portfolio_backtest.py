from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from statistics import mean, pstdev
from typing import Any, Iterable


@dataclass(frozen=True)
class PortfolioConfig:
    """Deterministic cash-only portfolio assumptions for research replay."""

    initial_cash: float = 100_000.0
    max_positions: int = 5
    risk_per_trade_pct: float = 0.5
    max_total_risk_pct: float = 2.0
    max_position_pct: float = 25.0
    allow_margin: bool = False


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _stamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _time_key(value: Any) -> tuple[int, str]:
    parsed = _stamp(value)
    return (0, parsed.isoformat()) if parsed else (1, str(value or ""))


def _equity(cash: float, positions: Iterable[dict[str, Any]]) -> float:
    return cash + sum(_number(item.get("shares")) * _number(item.get("mark_price")) for item in positions)


def _max_drawdown_pct(curve: list[dict[str, Any]]) -> float:
    peak = 0.0
    drawdown = 0.0
    for point in curve:
        equity = _number(point.get("equity"))
        peak = max(peak, equity)
        if peak:
            drawdown = min(drawdown, (equity / peak - 1.0) * 100)
    return round(drawdown, 4)


def simulate_cash_portfolio(
    trades: Iterable[dict[str, Any]],
    config: PortfolioConfig | None = None,
) -> dict[str, Any]:
    """Replay completed long trades as a cash-only, no-margin portfolio.

    Inputs are already point-in-time policy outcomes. This layer deliberately
    does not generate signals, alter entries, or turn a research result into an
    execution instruction. On a shared entry timestamp it processes higher
    ``rank``/``score`` candidates first, then symbol for reproducibility.
    """

    active_config = config or PortfolioConfig()
    normalized: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in trades:
        item = dict(raw)
        entry_time = _stamp(item.get("entry_time"))
        exit_time = _stamp(item.get("exit_time"))
        entry = _number(item.get("entry_price"))
        exit_price = _number(item.get("exit_price"))
        stop = _number(item.get("stop_price"))
        if not entry_time or not exit_time or exit_time < entry_time or entry <= 0 or exit_price <= 0 or stop <= 0 or stop >= entry:
            rejected.append({"trade": item, "reason": "invalid_completed_trade"})
            continue
        item["_entry_time"] = entry_time
        item["_exit_time"] = exit_time
        item["_entry_price"] = entry
        item["_exit_price"] = exit_price
        item["_stop_price"] = stop
        item["_rank"] = _number(item.get("rank"), _number(item.get("score")))
        normalized.append(item)
    normalized.sort(key=lambda item: (item["_entry_time"], -item["_rank"], str(item.get("symbol") or "")))

    cash = max(0.0, active_config.initial_cash)
    active: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []
    transactions: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = [{"time": "start", "equity": round(cash, 4), "cash": round(cash, 4), "open_positions": 0}]

    def close_due(until: datetime) -> None:
        nonlocal cash, active
        closing = sorted((position for position in active if position["exit_time"] <= until), key=lambda position: position["exit_time"])
        for position in closing:
            cash += position["shares"] * position["exit_price"]
            pnl = position["shares"] * (position["exit_price"] - position["entry_price"])
            realized_r = _number(position["trade"].get("realized_r"), pnl / max(position["risk_dollars"], 0.0001))
            execution = {
                "symbol": position["trade"].get("symbol"),
                "signal_time": position["trade"].get("signal_time"),
                "entry_time": position["entry_time"].isoformat(),
                "exit_time": position["exit_time"].isoformat(),
                "shares": position["shares"],
                "entry_price": round(position["entry_price"], 4),
                "exit_price": round(position["exit_price"], 4),
                "entry_notional": round(position["shares"] * position["entry_price"], 4),
                "exit_notional": round(position["shares"] * position["exit_price"], 4),
                "pnl": round(pnl, 4),
                "realized_r": round(realized_r, 4),
                "holding_days": round(max(0.0, (position["exit_time"] - position["entry_time"]).total_seconds() / 86_400), 4),
                "outcome": position["trade"].get("outcome", "time_exit"),
            }
            executions.append(execution)
            transactions.append({"type": "exit", "time": execution["exit_time"], "symbol": execution["symbol"], "notional": execution["exit_notional"]})
            active.remove(position)
            equity_curve.append({
                "time": execution["exit_time"],
                "equity": round(_equity(cash, active), 4),
                "cash": round(cash, 4),
                "open_positions": len(active),
            })

    for trade in normalized:
        close_due(trade["_entry_time"])
        current_equity = _equity(cash, active)
        if len(active) >= max(1, active_config.max_positions):
            rejected.append({"trade": trade, "reason": "max_positions"})
            continue
        risk_per_share = trade["_entry_price"] - trade["_stop_price"]
        open_risk = sum(position["risk_dollars"] for position in active)
        max_risk_dollars = current_equity * max(0.0, active_config.max_total_risk_pct) / 100
        risk_budget = min(
            current_equity * max(0.0, active_config.risk_per_trade_pct) / 100,
            max(0.0, max_risk_dollars - open_risk),
        )
        max_position_dollars = current_equity * max(0.0, active_config.max_position_pct) / 100
        shares = math.floor(min(
            risk_budget / risk_per_share,
            max_position_dollars / trade["_entry_price"],
            cash / trade["_entry_price"],
        ))
        if shares <= 0:
            rejected.append({"trade": trade, "reason": "cash_or_risk_limit"})
            continue
        cost = shares * trade["_entry_price"]
        cash -= cost
        risk_dollars = shares * risk_per_share
        position = {
            "trade": trade,
            "entry_time": trade["_entry_time"],
            "exit_time": trade["_exit_time"],
            "entry_price": trade["_entry_price"],
            "exit_price": trade["_exit_price"],
            "mark_price": trade["_entry_price"],
            "shares": shares,
            "risk_dollars": risk_dollars,
        }
        active.append(position)
        transactions.append({"type": "entry", "time": trade["_entry_time"].isoformat(), "symbol": trade.get("symbol"), "notional": round(cost, 4)})
        equity_curve.append({
            "time": trade["_entry_time"].isoformat(),
            "equity": round(_equity(cash, active), 4),
            "cash": round(cash, 4),
            "open_positions": len(active),
        })
    if active:
        close_due(max(position["exit_time"] for position in active))

    final_equity = _equity(cash, active)
    return {
        "portfolio_config": asdict(active_config),
        "initial_cash": round(active_config.initial_cash, 4),
        "ending_equity": round(final_equity, 4),
        "cash": round(cash, 4),
        "executions": executions,
        "rejected": rejected,
        "transactions": transactions,
        "equity_curve": equity_curve,
        "max_drawdown_pct": _max_drawdown_pct(equity_curve),
        "cash_only": True,
        "allow_margin": False,
        "read_only_research": True,
    }


def portfolio_performance_metrics(portfolio: dict[str, Any]) -> dict[str, Any]:
    """Return complete portfolio metrics with explicit observation limitations."""

    initial = max(_number(portfolio.get("initial_cash")), 0.0001)
    ending = _number(portfolio.get("ending_equity"))
    executions = list(portfolio.get("executions") or [])
    curve = [item for item in portfolio.get("equity_curve") or [] if _number(item.get("equity")) > 0]
    dated = [(stamp, _number(point.get("equity"))) for point in curve if (stamp := _stamp(point.get("time")))]
    dated.sort(key=lambda item: item[0])
    total_days = max(1.0, (dated[-1][0] - dated[0][0]).total_seconds() / 86_400) if len(dated) >= 2 else 1.0
    total_return = ending / initial - 1.0
    annualized = (ending / initial) ** (365.25 / total_days) - 1.0 if ending > 0 else -1.0
    returns = [dated[index][1] / dated[index - 1][1] - 1.0 for index in range(1, len(dated)) if dated[index - 1][1] > 0]
    periods_per_year = 252 * max(1, len(returns)) / total_days
    volatility = pstdev(returns) if len(returns) > 1 else 0.0
    sharpe = mean(returns) / volatility * math.sqrt(periods_per_year) if volatility else 0.0
    downside = [value for value in returns if value < 0]
    downside_volatility = math.sqrt(sum(value * value for value in downside) / len(downside)) if downside else 0.0
    sortino = mean(returns) / downside_volatility * math.sqrt(periods_per_year) if downside_volatility else 0.0
    drawdown = abs(_number(portfolio.get("max_drawdown_pct"))) / 100
    calmar = annualized / drawdown if drawdown else 0.0
    pnl = [_number(item.get("pnl")) for item in executions]
    r_values = [_number(item.get("realized_r")) for item in executions]
    wins = [value for value in r_values if value > 0]
    losses = [value for value in r_values if value <= 0]
    gross_profit = sum(value for value in pnl if value > 0)
    gross_loss = abs(sum(value for value in pnl if value < 0))
    streak = longest = 0
    for value in r_values:
        streak = streak + 1 if value <= 0 else 0
        longest = max(longest, streak)
    holding_days = sum(_number(item.get("holding_days")) for item in executions)
    turnover = sum(abs(_number(item.get("notional"))) for item in portfolio.get("transactions") or []) / max(initial, 0.0001)
    return {
        "total_return_pct": round(total_return * 100, 4),
        "annualized_return_pct": round(annualized * 100, 4),
        "max_drawdown_pct": round(-abs(_number(portfolio.get("max_drawdown_pct"))), 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (999.0 if gross_profit else 0.0),
        "win_rate_pct": round(len(wins) / len(r_values) * 100, 4) if r_values else 0.0,
        "average_r": round(mean(r_values), 4) if r_values else 0.0,
        "average_win_r": round(mean(wins), 4) if wins else 0.0,
        "average_loss_r": round(mean(losses), 4) if losses else 0.0,
        "max_consecutive_losses": longest,
        "exposure_time_pct": round(holding_days / total_days * 100, 4),
        "turnover_pct_of_initial_cash": round(turnover * 100, 4),
        "trade_count": len(executions),
        "rejected_candidate_count": len(portfolio.get("rejected") or []),
        "return_observation_count": len(returns),
        "metric_limitations": [
            "Portfolio equity is marked at deterministic entry and exit events, not an intraday NAV series.",
            "Metrics are research evidence only and do not represent a live trading forecast.",
        ],
    }


def buy_and_hold_benchmark(candles: Iterable[dict[str, Any]], name: str) -> dict[str, Any]:
    rows = sorted((dict(row) for row in candles if _number(row.get("close")) > 0), key=lambda row: _time_key(row.get("open_time")))
    if len(rows) < 2:
        return {"name": name, "available": False, "reason": "insufficient_candles"}
    start, end = _number(rows[0].get("close")), _number(rows[-1].get("close"))
    return {
        "name": name,
        "available": True,
        "start_time": rows[0].get("open_time"),
        "end_time": rows[-1].get("open_time"),
        "total_return_pct": round((end / start - 1.0) * 100, 4),
        "entry_price": round(start, 4),
        "exit_price": round(end, 4),
        "method": "buy_and_hold",
    }


def ema_trend_benchmark(candles: Iterable[dict[str, Any]], fast: int = 20, slow: int = 50) -> dict[str, Any]:
    rows = sorted((dict(row) for row in candles if _number(row.get("close")) > 0), key=lambda row: _time_key(row.get("open_time")))
    if len(rows) <= slow:
        return {"name": f"EMA{fast}/EMA{slow}", "available": False, "reason": "insufficient_candles"}
    closes = [_number(row.get("close")) for row in rows]

    def ema(period: int) -> list[float]:
        alpha = 2 / (period + 1)
        values = [closes[0]]
        for price in closes[1:]:
            values.append(values[-1] + alpha * (price - values[-1]))
        return values

    fast_values, slow_values = ema(fast), ema(slow)
    equity = 1.0
    invested = False
    trades = 0
    for index in range(1, len(rows)):
        should_hold = fast_values[index - 1] > slow_values[index - 1]
        if should_hold:
            equity *= closes[index] / closes[index - 1]
        if should_hold != invested:
            trades += 1
        invested = should_hold
    return {
        "name": f"EMA{fast}/EMA{slow}",
        "available": True,
        "total_return_pct": round((equity - 1.0) * 100, 4),
        "trade_transitions": trades,
        "method": "long_when_fast_above_slow_next_bar",
        "not_ai_ranked": True,
    }

