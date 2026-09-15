"""Descriptive candidate statistics; evidence gates are never execution approval.

Times are UTC epoch seconds. Bootstrap resamples synchronized calendar days,
not individual trades. Exposure/data audits and full stress replay must be
supplied separately to evaluate_gates; summarize alone cannot prove performance.
"""
from __future__ import annotations

from collections import defaultdict
import math
import random

DAY = 86400
BOOTSTRAP_SEED = 20260905


def _number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("metrics require finite numeric values")
    return number


def _mean(values):
    return sum(values) / len(values) if values else None


def _basic(trades):
    pnls = [_number(t["net_pnl"]) for t in trades]
    rs = [_number(t["net_r"]) for t in trades]
    wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p < 0]
    rw, rl = [r for r in rs if r > 0], [r for r in rs if r < 0]
    total = peak = drawdown = 0.0
    for trade in sorted(trades, key=lambda t: (_number(t["exit_time"]), str(t.get("trade_id", "")))):
        total += _number(trade["net_r"])
        peak = max(peak, total)
        drawdown = max(drawdown, peak - total)
    return {
        "sample_count": len(trades), "wins": len(wins), "losses": len(losses),
        "breakevens": len(pnls) - len(wins) - len(losses),
        "net_pnl": sum(pnls), "total_net_r": sum(rs),
        "fees": sum(_number(t.get("fees", 0)) for t in trades),
        "win_rate": len(wins) / len(pnls) if pnls else None,
        "average_win": _mean(wins), "average_loss": _mean(losses),
        "payoff": _mean(wins) / abs(_mean(losses)) if wins and losses else None,
        "payoff_r": _mean(rw) / abs(_mean(rl)) if rw and rl else None,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "profit_factor_r": sum(rw) / abs(sum(rl)) if rl else None,
        "ratio_boundary": "no_trades" if not trades else "no_losses" if not losses else
                          "no_wins" if not wins else None,
        "expectancy": _mean(pnls), "expectancy_r": _mean(rs), "average_r": _mean(rs),
        "max_drawdown_r": drawdown if trades else None,
        "drawdown_r_definition": "Peak-to-trough cumulative closed-trade net_r, starting at 0; "
                                 "exit_time order, trade_id tie-break. Not mark-to-market R.",
    }


def _bootstrap(trades, equity):
    times = [_number(t["entry_time"]) for t in trades]
    bounds = [_number(row["time"]) for row in equity]
    if not times and not bounds:
        return {"interval_95": None, "calendar_days": 0, "complete_week_blocks": 0,
                "stable": False, "iterations": 2000, "seed": BOOTSTRAP_SEED,
                "block_days": 7, "valid_replicates": 0, "no_trade_days": 0}
    exits = [_number(t["exit_time"]) for t in trades]
    start, end = min(times + bounds), max(times + bounds + exits)
    first, last = math.floor(start / DAY), math.floor(end / DAY)
    # A midnight equity endpoint closes the preceding UTC day; it does not
    # invent an additional empty day unless an entry really occurred there.
    if end > start and end % DAY == 0 and end not in times:
        last -= 1
    days = [[0.0, 0] for _ in range(last - first + 1)]
    for t in trades:
        row = days[math.floor(_number(t["entry_time"]) / DAY) - first]
        row[0] += _number(t["net_r"])
        row[1] += 1
    # Moving, non-circular seven-day blocks; retain all symbols/modes together.
    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    if len(days) >= 7 and trades:
        for _ in range(2000):
            total, count, remaining = 0.0, 0, len(days)
            while remaining:
                offset = rng.randrange(len(days) - 6)
                width = min(7, remaining)
                for value, n in days[offset:offset + width]:
                    total += value
                    count += n
                remaining -= width
            if count:
                means.append(total / count)
    means.sort()
    interval = [means[int(0.025 * (len(means) - 1))],
                means[int(0.975 * (len(means) - 1))]] if means else None
    complete_days = max(0, math.floor(end / DAY) - math.ceil(start / DAY))
    weeks = complete_days // 7
    return {"interval_95": interval, "calendar_days": len(days),
            "no_trade_days": sum(n == 0 for _, n in days),
            "complete_week_blocks": weeks, "stable": weeks >= 12 and len(means) == 2000,
            "iterations": 2000, "valid_replicates": len(means), "seed": BOOTSTRAP_SEED,
            "block_days": 7, "grouping": "entry UTC date; all symbols synchronized",
            "window_source": "equity_and_entries" if bounds else "inferred_from_entries",
            "empty_replicates": 2000 - len(means),
            "warning": "Fewer than 12 complete weeks; interval unstable" if weeks < 12 else
                       "Empty-trade bootstrap replicates; conditional interval unstable" if len(means) < 2000 else None}


def fixed_cost_stress(trades):
    """Fixed long-spot trades, 2x fees and adverse execution; BASE risk frozen.

    Portfolio fields: entry_market_reference, exit_market_reference, quantity,
    fee_bps, base_unit_net_risk, execution_cost_bps. Also accepts legacy names
    entry_reference, exit_reference, q, base_unit_risk/frozen_unit_risk and
    ohlcv_execution_cost_bps. For quotes use execution_source='quotes' and
    execution_cost_bps (or quote_extra_slippage_bps) and
    observed ask/bid references. This preserves the observed spread.
    Cost/risk fields may also reside in a 'costs' mapping. No inferred defaults.
    This is NOT a replay of stressed sizing, signals, or cash constraints.
    """
    trades = list(trades)
    if not trades:
        return {"available": False, "reason": "no trades", "trades": []}
    stressed, missing = [], []
    for index, trade in enumerate(trades):
        try:
            values = {**trade.get("costs", {}), **trade}
            if values.get("cost_multiplier", 1) != 1:
                raise ValueError("fixed 2x stress requires BASE trades, not already stressed trades")
            if str(values.get("side", "long")).lower() not in {"long", "buy"}:
                raise ValueError("only long spot trades supported")
            entry = _number(values.get("entry_market_reference", values.get("entry_reference")))
            exit_ = _number(values.get("exit_market_reference", values.get("exit_reference")))
            q = _number(values.get("quantity", values.get("q")))
            risk = _number(values.get("base_unit_net_risk", values.get("base_unit_risk", values.get("frozen_unit_risk"))))
            fee = _number(values["fee_bps"]) * 2 / 10000
            source = values.get("execution_source", "ohlcv")
            if source not in {"ohlcv", "quote", "quotes"}:
                raise ValueError("unknown execution_source")
            cost_key = "quote_extra_slippage_bps" if source in {"quote", "quotes"} else "ohlcv_execution_cost_bps"
            slip = _number(values.get("execution_cost_bps", values.get(cost_key))) * 2 / 10000
            if min(entry, exit_, q, risk) <= 0 or not 0 <= fee < 1 or not 0 <= slip < 1:
                raise ValueError("invalid cost, quantity, reference or frozen risk")
            paid, received = entry * (1 + slip), exit_ * (1 - slip)
            fees = q * fee * (paid + received)
            pnl = q * (received - paid) - fees
            stressed.append({**trade, "net_pnl": pnl, "net_r": pnl / (q * risk),
                             "fees": fees, "risk_amount": q * risk,
                             "entry_price": paid, "exit_price": received,
                             "entry_fee": q * paid * fee, "cost_multiplier": 2,
                             "fee_bps": fee * 10000, "execution_cost_bps": slip * 10000})
        except (KeyError, TypeError, ValueError) as error:
            missing.append({"trade_id": trade.get("trade_id", index), "reason": str(error)})
    if missing:
        return {"available": False, "reason": "insufficient or invalid fixed-cost fields",
                "unavailable_trades": missing, "trades": []}
    return {"available": True, "scenario": "STRESS_2X_FIXED_TRADES", "trades": stressed,
            "summary": _basic(stressed), "risk_denominator": "BASE quantity * frozen unit risk",
            "full_stress_replay": False}


def summarize(trades, equity, initial_cash=10000):
    trades, equity = [dict(t) for t in trades], [dict(e) for e in equity]
    initial_cash = _number(initial_cash)
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    for t in trades:
        if _number(t["exit_time"]) < _number(t["entry_time"]):
            raise ValueError("exit_time precedes entry_time")
    result = _basic(trades)
    peak, drawdown = initial_cash, 0.0
    seen = {}
    for row in sorted(equity, key=lambda row: _number(row["time"])):
        stamp, value = _number(row["time"]), _number(row["equity"])
        if stamp in seen and seen[stamp] != value:
            raise ValueError("conflicting equity at the same timestamp")
        seen[stamp] = value
        peak = max(peak, value)
        drawdown = max(drawdown, (peak - value) / peak * 100)
    result["max_drawdown_pct"] = drawdown if equity else None
    result["drawdown_pct_definition"] = "Peak-to-trough supplied mark-to-market equity including initial_cash; percent"
    result["equity_observations"] = len(seen)
    groups = {}
    for name, fields in (("by_mode", ("mode",)), ("by_symbol", ("symbol",)),
                         ("by_symbol_mode", ("symbol", "mode"))):
        buckets = defaultdict(list)
        for t in trades:
            buckets[tuple(str(t.get(f, "UNKNOWN")) for f in fields)].append(t)
        if len(fields) == 1:
            groups[name] = {key[0]: _basic(rows) for key, rows in sorted(buckets.items())}
        else:
            groups[name] = {}
            for (symbol, mode), rows in sorted(buckets.items()):
                groups[name].setdefault(symbol, {})[mode] = _basic(rows)
    result.update(groups)
    best_symbol = max(result["by_symbol"], key=lambda s: result["by_symbol"][s]["net_pnl"], default=None)
    best_index = max(range(len(trades)), key=lambda i: _number(trades[i]["net_pnl"]), default=None)
    result["exclude_best_symbol"] = {"excluded_symbol": best_symbol,
        **_basic([t for t in trades if str(t.get("symbol", "UNKNOWN")) != best_symbol])}
    result["exclude_best_trade"] = {"excluded_trade_id": trades[best_index].get("trade_id", best_index)
                                    if best_index is not None else None,
        **_basic([t for i, t in enumerate(trades) if i != best_index])}
    result["bootstrap"] = _bootstrap(trades, equity)
    result["fixed_cost_stress"] = fixed_cost_stress(trades)
    result["gates"] = evaluate_gates(result)
    result["performance_status"] = result["gates"]["status"]
    return result


def evaluate_gates(summary, evidence=None):
    """Evaluate preregistered targets with explicit external audit evidence.

    evidence: unexposed_test, policy_frozen, data_continuous, equity_complete
    (strict booleans), full_stress_expectancy_r, and optional claimed_symbol_modes
    [(symbol, mode), ...]. Defaults claim every observed cell. Historical
    exposure is never inferred from profitable trades or a large sample.
    """
    evidence = dict(evidence or {})
    checks = {}

    def numeric(name, value, threshold, operator=">=", insufficient=False):
        if value is not None:
            try:
                value = _number(value)
            except (TypeError, ValueError):
                value = None
        passed = None if value is None else (value > threshold if operator == ">" else
                                              value <= threshold if operator == "<=" else value >= threshold)
        checks[name] = {"observed": value, "operator": operator, "required": threshold,
                        "status": "PASS" if passed else "INSUFFICIENT" if passed is None or insufficient else "FAIL"}

    for field, limit, op in (("payoff", 1.8, ">="), ("profit_factor", 1.30, ">="),
                             ("expectancy_r", 0, ">"), ("max_drawdown_pct", 5, "<="),
                             ("max_drawdown_r", 10, "<=")):
        numeric(field, summary.get(field), limit, op)
    numeric("sample_count", summary["sample_count"], 200, insufficient=True)
    for mode, aliases in (("trend", {"trend", "up_trend"}), ("range", {"range"})):
        matching = [v for k, v in summary["by_mode"].items() if k.lower() in aliases]
        # Mixed aliases are ambiguous evidence, not an opportunity to choose the better result.
        row = matching[0] if len(matching) == 1 else {}
        numeric(f"{mode}.sample_count", row.get("sample_count", 0), 50, insufficient=True)
        for field, limit, op in (("payoff", 1.5, ">="), ("profit_factor", 1.25, ">="), ("expectancy_r", 0, ">")):
            numeric(f"{mode}.{field}", row.get(field), limit, op)
    cells = summary["by_symbol_mode"]
    claims = evidence.get("claimed_symbol_modes") or [(s, m) for s in cells for m in cells[s]]
    for symbol, mode in claims:
        numeric(f"{symbol}.{mode}.sample_count", cells.get(symbol, {}).get(mode, {}).get("sample_count", 0),
                30, insufficient=True)
    for name in ("exclude_best_symbol", "exclude_best_trade"):
        numeric(name, summary[name]["expectancy_r"], 0, ">")
    stress = summary["fixed_cost_stress"]
    numeric("fixed_cost_stress_pf", stress.get("summary", {}).get("profit_factor") if stress["available"] else None, 1.05)
    numeric("full_stress_expectancy_r", evidence.get("full_stress_expectancy_r"), 0, ">")
    interval = summary["bootstrap"]["interval_95"]
    numeric("bootstrap_lower_95", interval[0] if interval else None, 0, ">", insufficient=True)
    for name, passed in {**{key: evidence.get(key) is True for key in
                          ("unexposed_test", "policy_frozen", "data_continuous", "equity_complete")},
                         "bootstrap_stable": summary["bootstrap"]["stable"]}.items():
        checks[name] = {"observed": passed if name == "bootstrap_stable" else evidence.get(name),
                        "required": True, "status": "PASS" if passed else "INSUFFICIENT"}
    statuses = {c["status"] for c in checks.values()}
    status = "TARGET_NOT_MET" if "FAIL" in statuses else "PERFORMANCE_UNPROVEN" if "INSUFFICIENT" in statuses else "TARGET_MET"
    return {"status": status, "checks": checks, "research_only": True, "order_submission": False}
