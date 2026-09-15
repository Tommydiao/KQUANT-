from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np

from .option_event_coverage import option_event_context as corporate_event_context
from .market_calendar import market_schedule
from .market_clock import is_trading_day, session_bounds_utc
from .options_expression import (
    option_chain,
    option_contract_snapshot,
    option_expiries,
    option_market_status,
)
from .operations import dispatch_personal_notification
from .stock_signals import api_stock_candles, api_stock_quote
from .stock_store import connect
from .web_push import deliver_web_push


OPTION_RADAR_POLICY_VERSION = "option_radar_v1.1.0"
OPTION_QUOTE_POLICY_VERSION = "option_quote_evidence_v1.0.0"
OPTION_SIMULATION_POLICY_VERSION = "option_simulation_ask_bid_v1.0.0"
OPTION_BBO_MAX_AGE_SECONDS = 15
NEW_YORK = ZoneInfo("America/New_York")

RADAR_UNIVERSE = (
    "SPY",
    "QQQ",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "TSLA",
    "AMD",
    "AVGO",
    "IWM",
)

SECTOR_BENCHMARK = {
    "SPY": "QQQ",
    "QQQ": "SPY",
    "IWM": "SPY",
    "AAPL": "XLK",
    "MSFT": "XLK",
    "NVDA": "XLK",
    "AMD": "XLK",
    "AVGO": "XLK",
    "AMZN": "XLY",
    "TSLA": "XLY",
    "META": "XLC",
    "GOOGL": "XLC",
}

HORIZON_GROUPS = {
    "INTRADAY_0DTE": {"min_dte": 0, "max_dte": 0, "max_trading_days": 0, "max_calendar_days": 0},
    "INTRADAY_7_14DTE": {"min_dte": 7, "max_dte": 14, "max_trading_days": 0, "max_calendar_days": 0},
    "SWING_14_35DTE": {"min_dte": 14, "max_dte": 35, "max_trading_days": 5, "max_calendar_days": 7},
}


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    return current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)


def _iso(value: datetime | None = None) -> str:
    return _now(value).isoformat()


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _now(value)
    if not value:
        return None
    try:
        return _now(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _json(value: Any) -> str:
    def encode(item: Any) -> str:
        if isinstance(item, datetime):
            return _iso(item)
        raise TypeError(f"Unsupported JSON type: {type(item).__name__}")
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=encode)


def _hash(value: Any, length: int = 24) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()[:length]


def _closed_daily(candles: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        row
        for row in candles
        if str(row.get("bar_state") or "closed_candle") == "closed_candle"
        and _number(row.get("close")) is not None
        and _parse_time(row.get("open_time")) is not None
    ]
    return sorted(rows, key=lambda row: str(row["open_time"]))


def _return_map(candles: Iterable[dict[str, Any]]) -> dict[str, float]:
    rows = _closed_daily(candles)
    result: dict[str, float] = {}
    for previous, current in zip(rows, rows[1:]):
        before = _number(previous.get("close"))
        after = _number(current.get("close"))
        stamp = _parse_time(current.get("open_time"))
        if before and after and before > 0 and after > 0 and stamp:
            result[stamp.date().isoformat()] = math.log(after / before)
    return result


def residual_evidence(
    target_candles: Iterable[dict[str, Any]],
    market_candles: Iterable[dict[str, Any]],
    sector_candles: Iterable[dict[str, Any]],
    *,
    current_target_return: float | None,
    current_market_return: float | None,
    current_sector_return: float | None,
    lookback: int = 60,
) -> dict[str, Any]:
    """Estimate market/sector residuals using only completed historical sessions."""

    target = _return_map(target_candles)
    market = _return_map(market_candles)
    sector = _return_map(sector_candles)
    dates = sorted(set(target) & set(market) & set(sector))
    if len(dates) < lookback + 5:
        return {"status": "insufficient_history", "observations": len(dates)}
    dates = dates[-max(lookback + 30, 90) :]
    training_dates = dates[-lookback:]
    y = np.asarray([target[item] for item in training_dates], dtype=float)
    market_values = np.asarray([market[item] for item in training_dates], dtype=float)
    sector_values = np.asarray([sector[item] for item in training_dates], dtype=float)
    if np.allclose(market_values, sector_values):
        x = np.column_stack([np.ones(len(y)), market_values])
        current_x = None if current_market_return is None else np.asarray([1.0, current_market_return])
        factor_names = ["intercept", "market_return"]
    else:
        x = np.column_stack([np.ones(len(y)), market_values, sector_values])
        current_x = (
            None
            if current_market_return is None or current_sector_return is None
            else np.asarray([1.0, current_market_return, current_sector_return])
        )
        factor_names = ["intercept", "market_return", "sector_return"]
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    residuals = y - x @ beta
    residual_std = float(np.std(residuals, ddof=1))
    result: dict[str, Any] = {
        "status": "available" if residual_std > 0 else "degenerate",
        "observations": len(y),
        "training_start": training_dates[0],
        "training_end": training_dates[-1],
        "factor_names": factor_names,
        "coefficients": [round(float(value), 8) for value in beta],
        "residual_std": residual_std,
    }
    if residual_std <= 0:
        return result
    if current_x is not None and current_target_return is not None:
        current_residual = float(current_target_return - current_x @ beta)
        result.update(
            current_residual=current_residual,
            current_residual_z=float((current_residual - float(np.mean(residuals))) / residual_std),
        )
    residual_by_date = {day: float(value) for day, value in zip(training_dates, residuals)}
    five_day_values = [
        sum(residual_by_date[day] for day in training_dates[index - 4 : index + 1])
        for index in range(4, len(training_dates))
    ]
    latest_five_day = sum(residual_by_date[day] for day in training_dates[-5:])
    five_day_std = float(np.std(five_day_values, ddof=1)) if len(five_day_values) > 1 else 0.0
    result.update(
        five_day_residual=latest_five_day,
        five_day_residual_z=(latest_five_day - float(np.mean(five_day_values))) / five_day_std if five_day_std else None,
    )
    return result


def _session_return(quote: dict[str, Any], session: str = "pre_market") -> tuple[float | None, str | None, dict[str, Any]]:
    session_quote = dict(quote.get(session) or {})
    last = _number(session_quote.get("last"))
    previous = _number(session_quote.get("previous_close")) or _number(quote.get("previous_close"))
    value = math.log(last / previous) if last and previous and last > 0 and previous > 0 else None
    return value, session_quote.get("event_time"), session_quote


def _realized_volatility(candles: Iterable[dict[str, Any]], periods: int = 20) -> float | None:
    values = list(_return_map(candles).values())[-periods:]
    if len(values) < periods:
        return None
    return float(np.std(np.asarray(values), ddof=1) * math.sqrt(252))


def _expiry_for_group(expiries: Iterable[str], market_day: date, group: str) -> str | None:
    limits = HORIZON_GROUPS[group]
    candidates: list[tuple[int, str]] = []
    for expiry in expiries:
        try:
            dte = (date.fromisoformat(expiry) - market_day).days
        except ValueError:
            continue
        if limits["min_dte"] <= dte <= limits["max_dte"]:
            candidates.append((dte, expiry))
    return min(candidates)[1] if candidates else None


def rank_atm_contracts(
    chain_rows: Iterable[dict[str, Any]],
    *,
    spot: float,
    direction: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    rows = [
        row
        for row in chain_rows
        if row.get("is_standard") and _number(row.get("strike_price")) is not None
    ]
    if not rows:
        return []
    if direction == "CALL":
        preferred = [row for row in rows if float(row["strike_price"]) <= spot]
        preferred.sort(key=lambda row: spot - float(row["strike_price"]))
        symbol_key = "call_symbol"
    else:
        preferred = [row for row in rows if float(row["strike_price"]) >= spot]
        preferred.sort(key=lambda row: float(row["strike_price"]) - spot)
        symbol_key = "put_symbol"
    ordered = preferred or sorted(rows, key=lambda row: abs(float(row["strike_price"]) - spot))
    result: list[dict[str, Any]] = []
    for row in ordered:
        if row.get(symbol_key):
            result.append({**row, "contract_symbol": row[symbol_key]})
        if len(result) >= max(1, min(limit, 3)):
            break
    return result


def select_atm_contract(
    chain_rows: Iterable[dict[str, Any]],
    *,
    spot: float,
    direction: str,
) -> dict[str, Any] | None:
    ranked = rank_atm_contracts(chain_rows, spot=spot, direction=direction, limit=1)
    return ranked[0] if ranked else None


def american_option_price(
    *,
    spot: float,
    strike: float,
    years_to_expiry: float,
    volatility: float,
    risk_free_rate: float,
    dividend_yield: float,
    direction: str,
    steps: int = 200,
) -> float:
    """Cox-Ross-Rubinstein value with continuous dividend yield and early exercise."""

    if spot <= 0 or strike <= 0 or years_to_expiry < 0 or volatility < 0 or steps < 2:
        raise ValueError("Invalid American option pricing input.")
    is_call = direction.upper() == "CALL"
    if years_to_expiry == 0:
        return max(0.0, spot - strike if is_call else strike - spot)
    dt = years_to_expiry / steps
    if volatility == 0:
        terminal = spot * math.exp((risk_free_rate - dividend_yield) * years_to_expiry)
        discounted = math.exp(-risk_free_rate * years_to_expiry) * max(0.0, terminal - strike if is_call else strike - terminal)
        return max(discounted, max(0.0, spot - strike if is_call else strike - spot))
    up = math.exp(volatility * math.sqrt(dt))
    down = 1.0 / up
    probability = (math.exp((risk_free_rate - dividend_yield) * dt) - down) / (up - down)
    if not 0 <= probability <= 1:
        raise ValueError("Binomial risk-neutral probability is outside [0, 1].")
    discount = math.exp(-risk_free_rate * dt)
    prices = np.asarray([spot * (up ** (steps - index)) * (down**index) for index in range(steps + 1)], dtype=float)
    values = np.maximum(prices - strike, 0.0) if is_call else np.maximum(strike - prices, 0.0)
    for level in range(steps - 1, -1, -1):
        prices = np.asarray([spot * (up ** (level - index)) * (down**index) for index in range(level + 1)], dtype=float)
        continuation = discount * (probability * values[:-1] + (1 - probability) * values[1:])
        exercise = np.maximum(prices - strike, 0.0) if is_call else np.maximum(strike - prices, 0.0)
        values = np.maximum(continuation, exercise)
    return float(values[0])


def _group_schedule(group: str, schedule: dict[str, Any], decision_at: datetime, expiry: str) -> dict[str, Any]:
    market_open = _parse_time(schedule.get("regular_open_utc"))
    market_close = _parse_time(schedule.get("regular_close_utc"))
    earliest = market_open + timedelta(minutes=10) if market_open else None
    if group == "INTRADAY_0DTE":
        cutoff = market_close - timedelta(minutes=60) if market_close else None
        reminder = market_close - timedelta(minutes=30) if market_close else None
        expires = market_close or decision_at
    elif group == "INTRADAY_7_14DTE":
        cutoff = market_close - timedelta(minutes=30) if market_close else None
        reminder = market_close - timedelta(minutes=15) if market_close else None
        expires = market_close or decision_at
    else:
        cutoff = market_close
        reminder = None
        contract_expiry = datetime.combine(date.fromisoformat(expiry), datetime.min.time(), tzinfo=NEW_YORK).astimezone(UTC)
        candidate_day = decision_at.astimezone(NEW_YORK).date()
        trading_days = 0
        fifth_trading_close = decision_at + timedelta(days=7)
        while candidate_day <= decision_at.astimezone(NEW_YORK).date() + timedelta(days=7):
            if is_trading_day(candidate_day):
                trading_days += 1
                if trading_days == 5:
                    fifth_trading_close = session_bounds_utc(candidate_day)[1]
                    break
            candidate_day += timedelta(days=1)
        expires = min(decision_at + timedelta(days=7), fifth_trading_close, contract_expiry)
    return {
        "earliest_confirm_at": _iso(earliest) if earliest else None,
        "entry_cutoff_at": _iso(cutoff) if cutoff else None,
        "exit_reminder_at": _iso(reminder) if reminder else None,
        "expires_at": _iso(expires),
    }


def _contract_scenarios(snapshot: dict[str, Any], underlying_price: float, *, as_of: datetime | None = None) -> dict[str, Any]:
    volatility = _number(snapshot.get("implied_volatility"))
    strike = _number(snapshot.get("strike_price"))
    risk_free_rate = _number(snapshot.get("risk_free_rate"))
    dividend_yield = _number(snapshot.get("dividend_yield"))
    try:
        expiry = date.fromisoformat(str(snapshot.get("expiry_date")))
    except ValueError:
        expiry = None
    if None in (volatility, strike, risk_free_rate, dividend_yield) or underlying_price <= 0 or expiry is None:
        return {
            "status": "unavailable",
            "reason": "IV, strike, expiry, dated risk-free rate, and dividend yield are required for American-option scenarios.",
        }
    current = _now(as_of)
    expiry_close = (datetime.combine(expiry, datetime.min.time(), tzinfo=NEW_YORK) + timedelta(hours=16)).astimezone(UTC)
    years = max(0.0, (expiry_close - current).total_seconds() / (365.25 * 24 * 3600))
    shocks = []
    for move_pct in (-2.0, 0.0, 2.0):
        shocked_spot = underlying_price * (1 + move_pct / 100)
        shocked_volatility = max(0.0001, float(volatility) - 0.05)
        remaining_years = max(0.0, years - 1 / 365.25)
        estimate = american_option_price(
            spot=shocked_spot,
            strike=float(strike),
            years_to_expiry=remaining_years,
            volatility=shocked_volatility,
            risk_free_rate=float(risk_free_rate),
            dividend_yield=float(dividend_yield),
            direction=str(snapshot.get("direction") or "CALL"),
        )
        shocks.append({"underlying_move_pct": move_pct, "iv_change_points": -5, "days_elapsed": 1, "estimated_option_price": round(estimate, 4)})
    return {
        "status": "american_binomial_scenario",
        "limitations": "Risk-neutral scenario value, not a trade price or a real-world return probability.",
        "inputs": {"risk_free_rate": risk_free_rate, "dividend_yield": dividend_yield, "implied_volatility": volatility},
        "scenarios": shocks,
    }


def _option_screen(snapshot: dict[str, Any], group: str, decision_at: datetime) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    if snapshot.get("provider_status") != "available":
        blockers.append("Option quote is unavailable.")
    if snapshot.get("depth_status") != "available":
        blockers.append("A valid two-sided option BBO is required.")
    if not snapshot.get("is_standard"):
        blockers.append("Only standard unadjusted contracts are eligible.")
    if not snapshot.get("strict_fill_eligible"):
        blockers.append("The BBO has no native event timestamp and cannot prove a post-decision fill.")
    received_at = _parse_time(snapshot.get("bbo_received_at"))
    event_time = _parse_time(snapshot.get("bbo_event_time"))
    if received_at is None or received_at <= decision_at:
        blockers.append("The option quote must be received after the decision is committed.")
    if event_time is None or event_time <= decision_at:
        blockers.append("The native BBO event must occur after the decision is committed.")
    if received_at is not None and event_time is not None and abs((received_at - event_time).total_seconds()) > OPTION_BBO_MAX_AGE_SECONDS:
        blockers.append(f"The BBO event and receipt clocks must agree within {OPTION_BBO_MAX_AGE_SECONDS} seconds.")
    delta = abs(_number(snapshot.get("delta")) or 0)
    if not 0.40 <= delta <= 0.65:
        blockers.append("Absolute delta must be between 0.40 and 0.65.")
    max_spread = 3.0 if group == "INTRADAY_0DTE" else 5.0
    if (_number(snapshot.get("spread_pct")) or math.inf) > max_spread:
        blockers.append(f"Spread must be no more than {max_spread:.1f}% of mid.")
    if (_number(snapshot.get("bid_size")) or 0) < 1 or (_number(snapshot.get("ask_size")) or 0) < 1:
        blockers.append("Both sides of the quote must show at least one contract.")
    if int(snapshot.get("open_interest") or 0) < 500:
        blockers.append("Open interest is below 500.")
    if int(snapshot.get("volume") or 0) < 100:
        blockers.append("Current-day contract volume is below 100.")
    if snapshot.get("quote_time_meaning") == "latest_trade_time_not_bbo_time":
        warnings.append("Longbridge quote_time is the latest trade time, not a BBO timestamp.")
    return blockers, warnings


def _persist_run(
    db_path: Path,
    *,
    market_day: str,
    run_type: str,
    data_hash: str,
    status: str,
    data_status: str,
    summary: dict[str, Any],
    generated_at: str,
) -> str:
    run_id = f"option-radar-{_hash([market_day, run_type, data_hash])}"
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO option_radar_runs(
              run_id, market_date, run_type, policy_version, universe_json,
              data_hash, status, data_status, generated_at, summary_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                market_day,
                run_type,
                OPTION_RADAR_POLICY_VERSION,
                _json(RADAR_UNIVERSE),
                data_hash,
                status,
                data_status,
                generated_at,
                _json(summary),
                generated_at,
            ),
        )
        conn.commit()
    return run_id


def _same_clock_participation(db_path: Path, symbol: str, market_minute: int, current_turnover: float | None) -> dict[str, Any]:
    if current_turnover is None:
        return {"status": "unavailable", "observations": 0, "percentile": None, "anomaly": False}
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT turnover FROM option_underlying_evidence
            WHERE symbol=? AND session='pre_market' AND strict_time_eligible=1
              AND market_minute BETWEEN ? AND ? AND turnover IS NOT NULL
            ORDER BY market_date DESC LIMIT 60
            """,
            (symbol, market_minute - 10, market_minute + 10),
        ).fetchall()
    values = [float(row["turnover"]) for row in rows if float(row["turnover"]) >= 0]
    if len(values) < 20:
        return {"status": "limited_history", "observations": len(values), "percentile": None, "anomaly": False}
    percentile = sum(value <= current_turnover for value in values) / len(values) * 100
    p90 = float(np.quantile(np.asarray(values, dtype=float), 0.9))
    return {
        "status": "available",
        "observations": len(values),
        "percentile": round(percentile, 2),
        "p90_turnover": p90,
        "current_turnover": current_turnover,
        "anomaly": current_turnover >= p90,
    }


def _persist_source_evidence(
    db_path: Path,
    run_id: str,
    *,
    market_day: str,
    market_minute: int,
    received_at: datetime,
    quotes: dict[str, dict[str, Any]],
    event_contexts: dict[str, dict[str, Any]],
) -> None:
    with connect(db_path) as conn:
        for symbol in RADAR_UNIVERSE:
            quote = quotes.get(symbol) or {}
            quote_received_at = _parse_time(quote.get("_request_received_at") or quote.get("received_at")) or received_at
            session_payload = quote.get("pre_market") or {}
            event_time = _parse_time(session_payload.get("event_time"))
            strict_time = bool(
                quote.get("provider_status") == "available"
                and event_time is not None
                and event_time <= quote_received_at + timedelta(seconds=30)
            )
            payload = {
                "symbol": symbol,
                "session": "pre_market",
                "source": quote.get("source_type") or "longbridge_quote",
                "provider_status": quote.get("provider_status") or "unknown",
                "event_time": _iso(event_time) if event_time else None,
                "received_at": _iso(quote_received_at),
                "last_price": session_payload.get("last"),
                "previous_close": session_payload.get("previous_close"),
                "volume": session_payload.get("volume"),
                "turnover": session_payload.get("turnover"),
                "strict_time_eligible": strict_time,
            }
            content_hash = _hash(payload, 64)
            conn.execute(
                """
                INSERT OR IGNORE INTO option_underlying_evidence(
                  evidence_id, run_id, symbol, market_date, market_minute, session,
                  source, provider_status, event_time, received_at, last_price,
                  previous_close, volume, turnover, strict_time_eligible,
                  content_hash, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, 'pre_market', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"option-underlying-{content_hash[:24]}",
                    run_id,
                    symbol,
                    market_day,
                    market_minute,
                    payload["source"],
                    payload["provider_status"],
                    payload["event_time"],
                    payload["received_at"],
                    payload["last_price"],
                    payload["previous_close"],
                    payload["volume"],
                    payload["turnover"],
                    int(strict_time),
                    content_hash,
                    _json(payload),
                    _iso(quote_received_at),
                ),
            )
            event = event_contexts.get(symbol) or {"status": "not_ingested", "trade_eligible": False}
            event_hash = _hash([run_id, symbol, event], 64)
            conn.execute(
                """
                INSERT OR IGNORE INTO option_event_evidence(
                  event_evidence_id, run_id, symbol, as_of, status, trade_eligible,
                  content_hash, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"option-event-{event_hash[:24]}",
                    run_id,
                    symbol,
                    _iso(received_at),
                    event.get("status") or "unknown",
                    int(event.get("trade_eligible") is True),
                    event_hash,
                    _json(event),
                    _iso(received_at),
                ),
            )
        conn.commit()


def _persist_opportunity(db_path: Path, run_id: str, item: dict[str, Any]) -> dict[str, Any]:
    now = item["decision_committed_at"]
    opportunity_id = f"option-opp-{_hash([run_id, item['symbol'], item['hypothesis'], item['direction']])}"
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO option_opportunities(
              opportunity_id, run_id, symbol, hypothesis, direction, horizon_class,
              rank_value, evidence_score, status, signal_time, market_data_time,
              decision_committed_at, event_status, evidence_grade, policy_version,
              material_state_hash, evidence_json, blockers_json, warnings_json,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                opportunity_id,
                run_id,
                item["symbol"],
                item["hypothesis"],
                item["direction"],
                item["horizon_class"],
                item["rank_value"],
                item["evidence_score"],
                item["status"],
                item["signal_time"],
                item.get("market_data_time"),
                now,
                item["event_status"],
                item["evidence_grade"],
                OPTION_RADAR_POLICY_VERSION,
                item["material_state_hash"],
                _json(item["evidence"]),
                _json(item["blockers"]),
                _json(item["warnings"]),
                now,
                now,
            ),
        )
        conn.commit()
    record_option_state_event(
        db_path,
        entity_type="opportunity",
        entity_id=opportunity_id,
        opportunity_id=opportunity_id,
        previous_state="",
        next_state=str(item["status"]),
        event_type="created",
        reasons=item.get("blockers") or (),
        material_state_hash=str(item["material_state_hash"]),
        recorded_at=now,
    )
    return {"opportunity_id": opportunity_id, **item}


def _persist_plan(db_path: Path, opportunity: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    plan_id = f"option-plan-{_hash([opportunity['opportunity_id'], plan['horizon_group'], plan['contract_symbol']])}"
    now = opportunity["decision_committed_at"]
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO option_plans(
              plan_id, opportunity_id, horizon_group, contract_symbol, expiry_date,
              dte, strike_price, direction, state, contract_status,
              decision_committed_at, earliest_confirm_at, entry_cutoff_at,
              exit_reminder_at, expires_at, max_holding_trading_days,
              max_holding_calendar_days, reference_quote_json, scenario_json,
              blockers_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id,
                opportunity["opportunity_id"],
                plan["horizon_group"],
                plan["contract_symbol"],
                plan["expiry_date"],
                plan["dte"],
                plan["strike_price"],
                plan["direction"],
                plan["state"],
                plan["contract_status"],
                now,
                plan.get("earliest_confirm_at"),
                plan.get("entry_cutoff_at"),
                plan.get("exit_reminder_at"),
                plan["expires_at"],
                plan["max_holding_trading_days"],
                plan["max_holding_calendar_days"],
                _json(plan.get("reference_quote") or {}),
                _json(plan.get("scenarios") or {}),
                _json(plan.get("blockers") or []),
                now,
                now,
            ),
        )
        conn.commit()
    record_option_state_event(
        db_path,
        entity_type="plan",
        entity_id=plan_id,
        opportunity_id=opportunity["opportunity_id"],
        plan_id=plan_id,
        previous_state="",
        next_state=str(plan["state"]),
        event_type="created",
        reasons=plan.get("blockers") or (),
        material_state_hash=_hash([plan_id, plan["state"], plan.get("blockers") or []]),
        recorded_at=now,
    )
    return {"plan_id": plan_id, **plan}


def _row_payload(row: Any, json_columns: Iterable[str]) -> dict[str, Any]:
    item = dict(row)
    for column in json_columns:
        value = item.pop(column, "{}" if column.endswith("_json") else "[]")
        key = column.removesuffix("_json")
        try:
            item[key] = json.loads(value or ("[]" if key in {"blockers", "warnings"} else "{}"))
        except (TypeError, json.JSONDecodeError):
            item[key] = [] if key in {"blockers", "warnings"} else {}
    return item


def _opportunity_from_row(row: Any) -> dict[str, Any]:
    return _row_payload(row, ("evidence_json", "blockers_json", "warnings_json"))


def _plan_from_row(row: Any) -> dict[str, Any]:
    return _row_payload(row, ("reference_quote_json", "scenario_json", "blockers_json"))


def record_option_state_event(
    db_path: Path,
    *,
    entity_type: str,
    entity_id: str,
    previous_state: str,
    next_state: str,
    event_type: str,
    reasons: Iterable[str] = (),
    opportunity_id: str | None = None,
    plan_id: str | None = None,
    material_state_hash: str = "",
    recorded_at: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    timestamp = recorded_at or _iso()
    reason_list = sorted({str(item) for item in reasons if str(item).strip()})
    content_hash = _hash(
        [entity_type, entity_id, event_type, previous_state, next_state, reason_list, material_state_hash],
        64,
    )
    event_id = f"option-state-{content_hash[:24]}"
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO option_state_events(
              event_id, entity_type, entity_id, opportunity_id, plan_id,
              event_type, previous_state, next_state, reason_json,
              material_state_hash, content_hash, recorded_at, actor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                entity_type,
                entity_id,
                opportunity_id,
                plan_id,
                event_type,
                previous_state,
                next_state,
                _json(reason_list),
                material_state_hash,
                content_hash,
                timestamp,
                actor,
            ),
        )
        conn.commit()
    return {
        "event_id": event_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "event_type": event_type,
        "previous_state": previous_state,
        "next_state": next_state,
        "reasons": reason_list,
        "material_state_hash": material_state_hash,
        "recorded_at": timestamp,
        "actor": actor,
    }


def option_plan_timeline(db_path: Path, plan_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        plan = conn.execute("SELECT * FROM option_plans WHERE plan_id=?", (plan_id,)).fetchone()
        if not plan:
            raise ValueError("Unknown option plan.")
        rows = conn.execute(
            "SELECT * FROM option_state_events WHERE plan_id=? ORDER BY recorded_at, event_id",
            (plan_id,),
        ).fetchall()
    events = []
    for row in rows:
        item = dict(row)
        try:
            item["reasons"] = json.loads(item.pop("reason_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            item["reasons"] = []
        events.append(item)
    return {
        "plan": _plan_from_row(plan),
        "events": events,
        "count": len(events),
        "append_only": True,
        "manual_execution_only": True,
    }


def _confirmation_decision_time(db_path: Path, plan_id: str) -> datetime | None:
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT recorded_at FROM option_state_events
            WHERE plan_id=? AND event_type='decision_committed'
            ORDER BY recorded_at LIMIT 1
            """,
            (plan_id,),
        ).fetchone()
    return _parse_time(row["recorded_at"]) if row else None


def _is_recomputed_plan_blocker(message: str) -> bool:
    prefixes = (
        "Option quote is unavailable",
        "A valid two-sided option BBO is required",
        "The BBO has no native event timestamp",
        "The option quote must be received after",
        "The native BBO event must occur after",
        "The BBO event and receipt clocks must agree",
        "Absolute delta must be between",
        "Spread must be no more than",
        "Both sides of the quote must show",
        "Open interest is below",
        "Current-day contract volume is below",
        "Premarket option quote is reference-only",
        "No option price was requested because OPRA",
        "OPRA realtime option quote permission",
        "Earnings, dividend, and corporate-event calendar",
        "No contract passed the strict post-decision BBO contract",
    )
    return message.startswith(prefixes)


def _create_alert(db_path: Path, opportunity: dict[str, Any], *, hub: Any | None = None) -> dict[str, Any] | None:
    state = str(opportunity["status"])
    severity = "RISK" if state in {"CANCELLED", "INVALIDATED", "EXIT_REVIEW"} else ("ACTION" if state == "CONFIRMED" else "INFO")
    dedupe_key = f"option-radar:{opportunity['opportunity_id']}:{state}:{opportunity['material_state_hash']}"
    alert_id = f"alert-{uuid.uuid4().hex[:20]}"
    now = _iso()
    title = {
        "PREMARKET_WATCH": "期权盘前观察",
        "WAIT_OPEN_CONFIRMATION": "等待开盘确认",
        "QUOTE_BLOCKED": "期权报价未通过",
        "CONFIRMED": "期权机会待人工复核",
        "CANCELLED": "期权计划已取消",
        "INVALIDATED": "期权计划已失效",
        "EXIT_REVIEW": "期权退出待复核",
    }.get(state, "期权机会状态变化")
    message = f"{opportunity['symbol']} {opportunity['direction']} · {title}"
    payload = {
        "opportunity_id": opportunity["opportunity_id"],
        "symbol": opportunity["symbol"],
        "direction": opportunity["direction"],
        "status": state,
        "manual_execution_only": True,
        "order_submission_enabled": False,
    }
    payload["plan_id"] = opportunity.get("plan_id")
    payload["contract_symbol"] = opportunity.get("contract_symbol")
    from urllib.parse import urlencode
    payload["url"] = "/?" + urlencode({
        "workspace": "options", "view": "plans" if opportunity.get("plan_id") else "opportunities",
        "symbol": opportunity["symbol"], "opportunity": opportunity["opportunity_id"],
        **({"plan": opportunity["plan_id"]} if opportunity.get("plan_id") else {}),
    })
    with connect(db_path) as conn:
        if conn.execute("SELECT 1 FROM alert_events WHERE dedupe_key = ?", (dedupe_key,)).fetchone():
            return None
        conn.execute(
            """
            INSERT INTO alert_events(
              alert_id, instruction_id, dedupe_key, symbol, severity, event_type,
              title, message, payload_json, delivery_status, acknowledged_at,
              created_at, updated_at
            ) VALUES (?, NULL, ?, ?, ?, 'option_radar', ?, ?, ?, 'web_queued', NULL, ?, ?)
            """,
            (alert_id, dedupe_key, opportunity["symbol"], severity, title, message, _json(payload), now, now),
        )
        conn.execute("INSERT INTO option_delivery_outbox VALUES (?, 'queued', ?, ?, ?, '{}')",
                     (alert_id, _json({"title": title, "body": message, "tag": dedupe_key,
                                      "severity": severity, **payload}), now, now))
        conn.commit()
    alert = {"alert_id": alert_id, "dedupe_key": dedupe_key, "severity": severity, "title": title, "message": message, "payload": payload}
    if hub is not None:
        hub.publish(alert)
    alert["web_push"] = {"status": "queued"}
    return alert


def dispatch_option_alerts(db_path: Path) -> dict[str, Any]:
    from .web_push import notification_preferences, _in_quiet_hours
    preferences = notification_preferences(db_path)
    with connect(db_path) as conn:
        rows = conn.execute("""SELECT * FROM option_delivery_outbox WHERE status IN ('queued','deferred','sending')
            ORDER BY CASE WHEN json_extract(payload_json, '$.severity') IN ('RISK','CRITICAL') THEN 0 ELSE 1 END,
            created_at LIMIT 10""").fetchall()
    results = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        if payload['severity'] not in {'RISK', 'CRITICAL'}:
            local = _now().astimezone(ZoneInfo(preferences['timezone']))
            day_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC).isoformat()
            with connect(db_path) as conn:
                delivered = conn.execute("""SELECT COUNT(*) FROM (
                    SELECT alert_id FROM alert_delivery_attempts WHERE status='sent'
                      AND severity IN ('INFO','ACTION') AND created_at >= ? AND alert_id IS NOT NULL
                    UNION SELECT substr(event_id, 17) FROM notification_events WHERE status='sent'
                      AND event_id LIKE 'option-telegram-%' AND created_at >= ?
                      AND json_extract(payload_json,'$.severity') IN ('INFO','ACTION'))""", (day_start,day_start)).fetchone()[0]
            if _in_quiet_hours(preferences) or delivered >= preferences['daily_routine_limit']:
                with connect(db_path) as conn:
                    conn.execute("UPDATE option_delivery_outbox SET status='deferred', result_json=?, updated_at=? WHERE alert_id=?",
                        (_json({'reason':'quiet_hours_or_daily_limit'}),_iso(),row['alert_id']))
                    conn.commit()
                results.append({'alert_id':row['alert_id'], 'status':'deferred'})
                continue
        if payload["severity"] not in {"RISK", "CRITICAL"} and _now() - _parse_time(row["created_at"]) > timedelta(minutes=30):
            result = {"status": "expired", "reason": "routine_alert_expired"}
        else:
            with connect(db_path) as conn:
                conn.execute("UPDATE option_delivery_outbox SET status='sending', updated_at=? WHERE alert_id=?", (_iso(), row["alert_id"]))
                conn.commit()
            result = deliver_web_push(db_path, alert_id=row["alert_id"], severity=payload["severity"], payload=payload)
            if os.getenv("KQUANT_ENABLE_NOTIFICATIONS", "false").lower() == "true":
                event_id = "option-telegram-" + row["alert_id"]
                with connect(db_path) as conn:
                    conn.execute("""INSERT OR IGNORE INTO notification_events
                        (event_id, channel, event_type, status, payload_json, created_at)
                        VALUES (?, 'telegram', 'option_radar', 'queued', ?, ?)""",
                        (event_id, _json(payload), row["created_at"]))
                    existing = conn.execute("SELECT status FROM notification_events WHERE event_id=?", (event_id,)).fetchone()
                    conn.commit()
                if existing["status"] == "queued":
                    result["telegram"] = dispatch_personal_notification(db_path, event_id=event_id)
        with connect(db_path) as conn:
            conn.execute("UPDATE option_delivery_outbox SET status=?, result_json=?, updated_at=? WHERE alert_id=?",
                         (result["status"], _json(result), _iso(), row["alert_id"]))
            conn.commit()
        results.append({"alert_id": row["alert_id"], **result})
    return {"processed": len(results), "results": results}


def _data_bundle(db_path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    symbols = sorted(set(RADAR_UNIVERSE) | set(SECTOR_BENCHMARK.values()))
    daily: dict[str, dict[str, Any]] = {}
    quotes: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        daily[symbol] = api_stock_candles(
            symbol,
            "1y",
            "1d",
            "live",
            db_path,
            allow_reference_fallback=False,
        )
        quote = api_stock_quote(symbol, db_path, isolated=True)
        quote.setdefault("_request_received_at", _iso())
        quotes[symbol] = quote
    return daily, quotes


def run_premarket_radar(
    db_path: Path,
    *,
    now: datetime | None = None,
    hub: Any | None = None,
    daily_payloads: dict[str, dict[str, Any]] | None = None,
    quote_payloads: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    current = _now(now)
    local = current.astimezone(NEW_YORK)
    schedule = market_schedule(local.date(), db_path)
    market_day = local.date().isoformat()
    market_status = option_market_status()
    if not schedule.get("is_trading_day"):
        summary = {"reason": "not_a_us_trading_day", "opportunity_count": 0, "manual_execution_only": True}
        data_hash = _hash([market_day, summary])
        run_id = _persist_run(
            db_path,
            market_day=market_day,
            run_type="premarket",
            data_hash=data_hash,
            status="closed",
            data_status="calendar_closed",
            summary=summary,
            generated_at=_iso(current),
        )
        return {"run_id": run_id, "market_date": market_day, "status": "closed", "opportunities": [], "summary": summary}

    daily, quotes = (
        (daily_payloads, quote_payloads)
        if daily_payloads is not None and quote_payloads is not None
        else _data_bundle(db_path)
    )
    raw_candidates: list[dict[str, Any]] = []
    event_contexts: dict[str, dict[str, Any]] = {}
    market_minute = local.hour * 60 + local.minute
    for symbol in RADAR_UNIVERSE:
        sector_symbol = SECTOR_BENCHMARK[symbol]
        target_daily = daily.get(symbol) or {}
        market_daily = daily.get("SPY") or {}
        sector_daily = daily.get(sector_symbol) or {}
        target_quote = quotes.get(symbol) or {}
        market_quote = quotes.get("SPY") or {}
        sector_quote = quotes.get(sector_symbol) or {}
        target_return, signal_time, session_quote = _session_return(target_quote)
        market_return, _, _ = _session_return(market_quote)
        sector_return, _, _ = _session_return(sector_quote)
        residual = residual_evidence(
            target_daily.get("candles") or [],
            market_daily.get("candles") or [],
            sector_daily.get("candles") or [],
            current_target_return=target_return,
            current_market_return=market_return,
            current_sector_return=sector_return,
        )
        event = corporate_event_context(db_path, symbol, as_of=_iso(current))
        event_contexts[symbol] = event
        if residual.get("status") != "available":
            continue
        common_blockers: list[str] = []
        common_warnings: list[str] = []
        provider_event_at = _parse_time(signal_time)
        quote_received_at = _parse_time(target_quote.get("_request_received_at") or target_quote.get("received_at")) or current
        clock_skew_seconds = (provider_event_at - quote_received_at).total_seconds() if provider_event_at else None
        if clock_skew_seconds is not None and clock_skew_seconds > 30:
            common_blockers.append(
                f"Provider event time is {int(clock_skew_seconds)} seconds ahead of the local decision clock."
            )
        if target_daily.get("source_type") != "longbridge_candles":
            common_blockers.append("Underlying daily data is not current Longbridge evidence.")
        if target_quote.get("provider_status") != "available":
            common_blockers.append("Underlying quote is unavailable.")
        if event.get("trade_eligible") is not True:
            common_blockers.append("Earnings, dividend, and corporate-event calendar is incomplete.")
        if market_status.get("opra_status") != "available":
            common_blockers.append("OPRA realtime option quote permission is not available.")
        turnover = _number(session_quote.get("turnover"))
        participation = _same_clock_participation(db_path, symbol, market_minute, turnover)
        if participation["status"] == "unavailable":
            common_blockers.append("Premarket participation is unavailable.")
        elif participation["status"] == "limited_history":
            common_blockers.append("Fewer than 20 same-clock premarket participation observations are available.")
        elif not participation["anomaly"]:
            common_blockers.append("Premarket turnover is below its registered same-clock 90th-percentile threshold.")
        else:
            common_warnings.append("Premarket turnover is above its stored same-clock 90th-percentile threshold.")
        definitions = (
            ("intraday_residual_continuation", "INTRADAY", residual.get("current_residual_z"), 1.5),
            ("short_swing_residual_continuation", "SHORT_SWING", residual.get("five_day_residual_z"), 1.25),
        )
        for hypothesis, horizon_class, z_value, threshold in definitions:
            z = _number(z_value)
            if z is None or abs(z) < threshold:
                continue
            direction = "CALL" if z > 0 else "PUT"
            score = min(100.0, abs(z) / 3.0 * 100)
            evidence = {
                "residual_model": residual,
                "residual_z": z,
                "threshold": threshold,
                "sector_benchmark": sector_symbol,
                "premarket": session_quote,
                "clock_contract": {
                    "received_at": _iso(quote_received_at),
                    "provider_event_time": signal_time,
                    "provider_ahead_seconds": clock_skew_seconds,
                    "status": "conflict" if clock_skew_seconds is not None and clock_skew_seconds > 30 else "accepted",
                },
                "premarket_participation": participation,
                "realized_volatility_20d": _realized_volatility(target_daily.get("candles") or []),
                "event_context": event,
                "supporting_factors": [
                    {"factor_id": f"{horizon_class.lower()}_residual_z", "value": z, "direction": direction},
                ],
                "opposing_factors": [
                    {"factor_id": "event_calendar", "status": event.get("status")},
                    {"factor_id": "opra_permission", "status": market_status.get("opra_status")},
                ],
            }
            raw_candidates.append(
                {
                    "symbol": symbol,
                    "hypothesis": hypothesis,
                    "direction": direction,
                    "horizon_class": horizon_class,
                    "evidence_score": round(score, 2),
                    "signal_time": signal_time or _iso(current),
                    "market_data_time": signal_time,
                    "decision_committed_at": _iso(current),
                    "event_status": str(event.get("status") or "unknown"),
                    "evidence_grade": "limited" if common_blockers else "observational",
                    "status": "PREMARKET_WATCH",
                    "evidence": evidence,
                    "blockers": list(common_blockers),
                    "warnings": list(common_warnings),
                }
            )
    raw_candidates.sort(key=lambda item: (-item["evidence_score"], RADAR_UNIVERSE.index(item["symbol"]), item["hypothesis"]))
    selected = raw_candidates[:5]
    for rank, item in enumerate(selected, start=1):
        item["rank_value"] = rank
        item["material_state_hash"] = _hash(
            [item["symbol"], item["hypothesis"], item["direction"], item["signal_time"], item["blockers"]]
        )
    source_manifest = {
        symbol: {
            "daily_source": (daily.get(symbol) or {}).get("source_type"),
            "daily_last": ((daily.get(symbol) or {}).get("candles") or [{}])[-1].get("open_time"),
            "quote_status": (quotes.get(symbol) or {}).get("provider_status"),
            "premarket_event_time": ((quotes.get(symbol) or {}).get("pre_market") or {}).get("event_time"),
        }
        for symbol in RADAR_UNIVERSE
    }
    data_hash = _hash(
        {
            "market_date": market_day,
            "policy_version": OPTION_RADAR_POLICY_VERSION,
            "candidates": selected,
            "calendar": schedule,
            "source_manifest": source_manifest,
        }
    )
    data_status = "limited" if any(item["blockers"] for item in selected) or market_status.get("opra_status") != "available" else "available"
    summary = {
        "opportunity_count": len(selected),
        "eligible_for_intraday_confirmation": sum(not item["blockers"] for item in selected),
        "opra_status": market_status.get("opra_status"),
        "event_calendar_status": "incomplete",
        "generated_for": "08:30 America/New_York premarket research",
        "manual_execution_only": True,
        "one_contract_risk_only": True,
    }
    run_id = _persist_run(
        db_path,
        market_day=market_day,
        run_type="premarket",
        data_hash=data_hash,
        status="completed",
        data_status=data_status,
        summary=summary,
        generated_at=_iso(current),
    )
    _persist_source_evidence(
        db_path,
        run_id,
        market_day=market_day,
        market_minute=market_minute,
        received_at=current,
        quotes=quotes,
        event_contexts=event_contexts,
    )
    opportunities = []
    for item in selected:
        opportunity = _persist_opportunity(db_path, run_id, item)
        spot = _number((quotes.get(item["symbol"]) or {}).get("pre_market", {}).get("last")) or _number((quotes.get(item["symbol"]) or {}).get("last")) or 0.0
        expiry_payload = option_expiries(item["symbol"])
        groups = ("INTRADAY_0DTE", "INTRADAY_7_14DTE") if item["horizon_class"] == "INTRADAY" else ("SWING_14_35DTE",)
        plans = []
        missing_groups: list[str] = []
        for group in groups:
            expiry = _expiry_for_group(expiry_payload.get("expiries") or [], local.date(), group)
            if expiry is None:
                missing_groups.append(group)
                continue
            chain_payload = option_chain(item["symbol"], expiry)
            selected_contracts = rank_atm_contracts(
                chain_payload.get("contracts") or [],
                spot=spot,
                direction=item["direction"],
                limit=3,
            )
            if not selected_contracts:
                missing_groups.append(group)
                continue
            for selected_contract in selected_contracts:
                reference_quote: dict[str, Any] = {}
                plan_blockers = list(item["blockers"])
                if market_status.get("opra_status") == "available":
                    reference_quote = option_contract_snapshot(str(selected_contract["contract_symbol"]), db_path)
                    plan_blockers.append("Premarket option quote is reference-only until the 09:40 confirmation decision.")
                else:
                    plan_blockers.append("No option price was requested because OPRA permission is unavailable.")
                schedule_values = _group_schedule(group, schedule, current, expiry)
                plan = {
                    "horizon_group": group,
                    "contract_symbol": str(selected_contract["contract_symbol"]),
                    "expiry_date": expiry,
                    "dte": (date.fromisoformat(expiry) - local.date()).days,
                    "strike_price": float(selected_contract["strike_price"]),
                    "direction": item["direction"],
                    "state": "REFERENCE_ONLY" if plan_blockers else "WAITING_CONFIRMATION",
                    "contract_status": "standard_reference",
                    "max_holding_trading_days": HORIZON_GROUPS[group]["max_trading_days"],
                    "max_holding_calendar_days": HORIZON_GROUPS[group]["max_calendar_days"],
                    "reference_quote": reference_quote,
                    "scenarios": _contract_scenarios(reference_quote, spot),
                    "blockers": plan_blockers,
                    **schedule_values,
                }
                plans.append(_persist_plan(db_path, opportunity, plan))
        if missing_groups:
            message = f"No standard contract was found for: {', '.join(missing_groups)}."
            opportunity["warnings"] = sorted(set((opportunity.get("warnings") or []) + [message]))
            if not plans:
                opportunity["blockers"] = sorted(set((opportunity.get("blockers") or []) + [message]))
            with connect(db_path) as conn:
                conn.execute(
                    "UPDATE option_opportunities SET blockers_json=?, warnings_json=?, updated_at=? WHERE opportunity_id=?",
                    (_json(opportunity["blockers"]), _json(opportunity["warnings"]), _iso(current), opportunity["opportunity_id"]),
                )
                conn.commit()
        opportunity["plans"] = plans
        opportunities.append(opportunity)
        _create_alert(db_path, opportunity, hub=hub)
    return {
        "run_id": run_id,
        "market_date": market_day,
        "status": "completed",
        "data_status": data_status,
        "summary": summary,
        "opportunities": opportunities,
        "policy_version": OPTION_RADAR_POLICY_VERSION,
        "read_only_research": True,
        "manual_execution_only": True,
        "order_submission_enabled": False,
    }


def persist_option_quote_evidence(db_path: Path, plan_id: str, snapshot: dict[str, Any], purpose: str) -> dict[str, Any]:
    received_at = snapshot.get("bbo_received_at")
    received_time = _parse_time(received_at)
    event_time = _parse_time(snapshot.get("bbo_event_time"))
    strict_fill_eligible = bool(
        snapshot.get("strict_fill_eligible")
        and snapshot.get("bbo_time_source") == "native_event_time"
        and received_time is not None
        and event_time is not None
        and abs((received_time - event_time).total_seconds()) <= OPTION_BBO_MAX_AGE_SECONDS
        and float(snapshot.get("bid") or 0) > 0
        and float(snapshot.get("ask") or 0) >= float(snapshot.get("bid") or 0)
        and float(snapshot.get("bid_size") or 0) >= 1
        and float(snapshot.get("ask_size") or 0) >= 1
    )
    material = {
        "plan_id": plan_id,
        "purpose": purpose,
        "contract_symbol": snapshot.get("contract_symbol"),
        "received_at": received_at,
        "bid": snapshot.get("bid"),
        "ask": snapshot.get("ask"),
        "bid_size": snapshot.get("bid_size"),
        "ask_size": snapshot.get("ask_size"),
        "source": snapshot.get("source"),
        "bbo_event_time": snapshot.get("bbo_event_time"),
        "bbo_time_source": snapshot.get("bbo_time_source"),
        "strict_fill_eligible": strict_fill_eligible,
    }
    content_hash = _hash(material, 64)
    evidence_id = f"option-quote-{content_hash[:24]}"
    execution_quality = "QUOTE_AWARE_STRICT" if strict_fill_eligible else "RECEIPT_TIME_ONLY" if received_time else "UNAVAILABLE"
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO option_quote_evidence(
              quote_evidence_id, plan_id, contract_symbol, purpose, source,
              received_at, latest_trade_time, bbo_event_time, bbo_time_source,
              bid, ask, bid_size, ask_size, strict_fill_eligible,
              execution_quality, content_hash, snapshot_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                plan_id,
                snapshot.get("contract_symbol") or "",
                purpose,
                snapshot.get("source") or "unknown",
                received_at or "",
                snapshot.get("quote_time"),
                snapshot.get("bbo_event_time"),
                snapshot.get("bbo_time_source") or "unknown",
                snapshot.get("bid"),
                snapshot.get("ask"),
                snapshot.get("bid_size"),
                snapshot.get("ask_size"),
                int(strict_fill_eligible),
                execution_quality,
                content_hash,
                _json(snapshot),
                _iso(),
            ),
        )
        conn.commit()
    return {"quote_evidence_id": evidence_id, **material, "strict_fill_eligible": strict_fill_eligible, "execution_quality": execution_quality}


def _closed_opening_bars(payload: dict[str, Any], market_open: datetime, now: datetime) -> list[dict[str, Any]]:
    result = []
    for row in payload.get("candles") or []:
        stamp = _parse_time(row.get("open_time"))
        if stamp is None or stamp < market_open or stamp + timedelta(minutes=5) > now:
            continue
        if str(row.get("bar_state") or "closed_candle") != "closed_candle":
            continue
        result.append(row)
    ordered = sorted(result, key=lambda row: str(row["open_time"]))
    opening = [row for row in ordered if _parse_time(row['open_time']) < market_open + timedelta(minutes=10)]
    if len(opening) != 2 or [_parse_time(row['open_time']) for row in opening] != [market_open, market_open+timedelta(minutes=5)]:
        return []
    return opening


def monitor_option_plans(db_path: Path, *, now: datetime | None = None, hub: Any | None = None) -> dict[str, Any]:
    """Deadline monitoring is independent of scanning, quotes, and new-entry gates."""
    current = _now(now)
    with connect(db_path) as conn:
        rows = conn.execute("""SELECT p.*, o.status AS opportunity_status
            FROM option_plans p JOIN option_opportunities o ON o.opportunity_id=p.opportunity_id
            WHERE EXISTS (SELECT 1 FROM option_outcomes x WHERE x.plan_id=p.plan_id AND x.status='open')
               OR EXISTS (SELECT 1 FROM option_manual_outcomes m WHERE m.plan_id=p.plan_id AND m.status='open')
               OR EXISTS (SELECT 1 FROM option_watchlist w WHERE w.plan_id=p.plan_id AND w.status='active')
            ORDER BY p.exit_reminder_at, p.plan_id""").fetchall()
    updated = 0
    for row in rows:
        plan = dict(row)
        with connect(db_path) as conn:
            open_result = conn.execute("""SELECT 1 FROM option_outcomes WHERE plan_id=? AND status='open'
                UNION ALL SELECT 1 FROM option_manual_outcomes WHERE plan_id=? AND status='open'""",
                (plan["plan_id"], plan["plan_id"])).fetchone()
        deadline = min(filter(None, (
            _parse_time(plan.get('exit_reminder_at')), _parse_time(plan.get('expires_at'))
        )), default=None) if open_result else _parse_time(plan['entry_cutoff_at'])
        if deadline is None or current < deadline:
            continue
        state = "EXIT_REVIEW" if open_result else "CANCELLED"
        reason = "Exit is due and remains unconfirmed." if open_result else "The entry window has closed without a recorded fill."
        event_hash = _hash([plan["plan_id"], state, _iso(deadline)])
        with connect(db_path) as conn:
            event_id = "option-deadline-" + event_hash
            conn.execute("""INSERT OR IGNORE INTO option_state_events
                (event_id,entity_type,entity_id,opportunity_id,plan_id,event_type,
                previous_state,next_state,reason_json,material_state_hash,content_hash,recorded_at,actor)
                VALUES (?, 'plan', ?, ?, ?, 'monitor_deadline', ?, ?, ?, ?, ?, ?, 'system')""",
                (event_id, plan['plan_id'], plan['opportunity_id'], plan['plan_id'],
                 plan['state'], state, _json([reason]), event_hash, event_hash, _iso(current)))
            conn.execute("UPDATE option_plans SET state=?, updated_at=? WHERE plan_id=?",
                         (state, _iso(current), plan["plan_id"]))
            conn.commit()
        # Retry the idempotent outbox creation even after a crash following the state commit.
        opportunity = option_signal_detail(db_path, plan["opportunity_id"])
        _create_alert(db_path, {**opportunity, "status": state, "material_state_hash": event_hash,
                               "plan_id": plan["plan_id"], "contract_symbol": plan["contract_symbol"]}, hub=hub)
        updated += int(plan['state'] != state)
    return {"tracked": len(rows), "updated": updated, "as_of": _iso(current), "fills_generated": 0}


def refresh_intraday_radar(db_path: Path, *, now: datetime | None = None, hub: Any | None = None) -> dict[str, Any]:
    current = _now(now)
    local_day = current.astimezone(NEW_YORK).date().isoformat()
    with connect(db_path) as conn:
        opportunity_rows = conn.execute(
            """
            SELECT DISTINCT o.* FROM option_opportunities o
            WHERE (
              o.run_id = (
                SELECT run_id FROM option_radar_runs
                WHERE market_date = ? AND run_type = 'premarket'
                ORDER BY generated_at DESC, created_at DESC
                LIMIT 1
              )
              OR EXISTS (
                SELECT 1 FROM option_plans p
                JOIN option_outcomes x ON x.plan_id = p.plan_id
                WHERE p.opportunity_id = o.opportunity_id AND x.status = 'open'
              )
              OR EXISTS (
                SELECT 1 FROM option_plans p JOIN option_watchlist w ON w.plan_id=p.plan_id
                WHERE p.opportunity_id=o.opportunity_id AND w.status='active'
              )
            )
              AND (
                o.status IN ('PREMARKET_WATCH','WAIT_OPEN_CONFIRMATION','QUOTE_BLOCKED','CONFIRMED','EXIT_REVIEW')
                OR EXISTS (
                  SELECT 1 FROM option_plans p
                  JOIN option_outcomes x ON x.plan_id = p.plan_id
                  WHERE p.opportunity_id = o.opportunity_id AND x.status = 'open'
                )
              )
            ORDER BY o.rank_value, o.symbol
            """,
            (local_day,),
        ).fetchall()
    if not opportunity_rows:
        return {"status": "idle", "market_date": local_day, "updated": 0, "reason": "no_current_premarket_opportunities"}
    status_payload = option_market_status()
    updated = 0
    results = []
    for row in opportunity_rows:
        opportunity = _opportunity_from_row(row)
        with connect(db_path) as conn:
            plan_rows = conn.execute("SELECT * FROM option_plans WHERE opportunity_id = ? ORDER BY horizon_group", (opportunity["opportunity_id"],)).fetchall()
            open_rows = conn.execute(
                """
                SELECT p.plan_id, x.outcome_id FROM option_plans p
                JOIN option_outcomes x ON x.plan_id=p.plan_id
                WHERE p.opportunity_id=? AND x.status='open'
                """,
                (opportunity["opportunity_id"],),
            ).fetchall()
        plans = [_plan_from_row(item) for item in plan_rows]
        open_plan_ids = {str(item["plan_id"]) for item in open_rows}
        if not plans:
            continue
        earliest = min(filter(None, (_parse_time(plan.get("earliest_confirm_at")) for plan in plans)), default=None)
        old_state = opportunity["status"]
        blockers = list(opportunity.get("blockers") or [])
        blockers = [item for item in blockers if "No contract passed the strict post-decision BBO contract" not in item]
        blockers = [item for item in blockers if not ("OPRA" in item and status_payload.get("opra_status") == "available")]
        current_event = corporate_event_context(db_path, opportunity["symbol"], as_of=_iso(current))
        if current_event.get("trade_eligible") is True:
            blockers = [item for item in blockers if "event calendar" not in item.lower()]
        elif not any("event calendar" in item.lower() for item in blockers):
            blockers.append("Earnings, dividend, and corporate-event calendar is incomplete.")
        if status_payload.get("opra_status") != "available" and not any("OPRA" in item for item in blockers):
            blockers.append("OPRA realtime option quote permission is not available.")
        warnings = list(opportunity.get("warnings") or [])
        new_state = old_state
        confirmation: dict[str, Any] = {"status": "waiting"}

        # Open simulations remain monitored across report dates. They never re-enter
        # the confirmation path, and an unconfirmed exit remains visible.
        if open_plan_ids:
            exit_review = False
            for plan in plans:
                if plan["plan_id"] not in open_plan_ids:
                    continue
                reminder = _parse_time(plan.get("exit_reminder_at"))
                expires = _parse_time(plan.get("expires_at"))
                if (reminder and current >= reminder) or (expires and current >= expires):
                    exit_review = True
                    previous = str(plan["state"])
                    with connect(db_path) as conn:
                        conn.execute(
                            "UPDATE option_plans SET state='EXIT_REVIEW', updated_at=? WHERE plan_id=?",
                            (_iso(current), plan["plan_id"]),
                        )
                        conn.commit()
                    if previous != "EXIT_REVIEW":
                        record_option_state_event(
                            db_path,
                            entity_type="plan",
                            entity_id=plan["plan_id"],
                            opportunity_id=opportunity["opportunity_id"],
                            plan_id=plan["plan_id"],
                            previous_state=previous,
                            next_state="EXIT_REVIEW",
                            event_type="exit_review_due",
                            reasons=("Exit reminder or plan expiry has been reached; exit remains unconfirmed.",),
                            material_state_hash=_hash([plan["plan_id"], "EXIT_REVIEW", reminder, expires]),
                            recorded_at=_iso(current),
                        )
            if exit_review or old_state == "EXIT_REVIEW":
                new_state = "EXIT_REVIEW"
                confirmation = {"status": "exit_review", "open_plan_count": len(open_plan_ids)}

        if open_plan_ids:
            pass
        elif earliest and current < earliest:
            new_state = "WAIT_OPEN_CONFIRMATION"
        elif new_state == "EXIT_REVIEW":
            confirmation = {"status": "exit_review"}
        else:
            schedule = market_schedule(current.astimezone(NEW_YORK).date(), db_path)
            market_open = _parse_time(schedule.get("regular_open_utc"))
            payload = api_stock_candles(
                opportunity["symbol"], "1d", "5m", "live", db_path, allow_reference_fallback=False
            )
            bars = _closed_opening_bars(payload, market_open, current) if market_open else []
            if len(bars) < 2:
                new_state = "WAIT_OPEN_CONFIRMATION"
                confirmation = {"status": "waiting", "closed_5m_bars": len(bars)}
            else:
                first, second = bars[0], bars[1]
                opening_move = math.log(float(second["close"]) / float(first["open"]))
                direction_ok = opening_move > 0 if opportunity["direction"] == "CALL" else opening_move < 0
                confirmation = {
                    "status": "confirmed" if direction_ok else "failed",
                    "closed_5m_bars": 2,
                    "first_bar_time": first["open_time"],
                    "second_bar_time": second["open_time"],
                    "opening_log_return": opening_move,
                }
                if not direction_ok:
                    new_state = "CANCELLED"
                    blockers.append("The first two closed 5-minute bars did not confirm the premarket direction.")
                else:
                    strict_plan_count = 0
                    active_plan_count = 0
                    for plan in plans:
                        cutoff = _parse_time(plan.get("entry_cutoff_at"))
                        if cutoff and current >= cutoff:
                            plan_blockers = sorted(set((plan.get("blockers") or []) + ["The entry window has closed."]))
                            previous = str(plan["state"])
                            with connect(db_path) as conn:
                                conn.execute(
                                    "UPDATE option_plans SET state='CANCELLED', blockers_json=?, updated_at=? WHERE plan_id=?",
                                    (_json(plan_blockers), _iso(current), plan["plan_id"]),
                                )
                                conn.commit()
                            if previous != "CANCELLED":
                                record_option_state_event(
                                    db_path,
                                    entity_type="plan",
                                    entity_id=plan["plan_id"],
                                    opportunity_id=opportunity["opportunity_id"],
                                    plan_id=plan["plan_id"],
                                    previous_state=previous,
                                    next_state="CANCELLED",
                                    event_type="entry_window_closed",
                                    reasons=("The entry window has closed.",),
                                    material_state_hash=_hash([plan["plan_id"], "CANCELLED", cutoff]),
                                    recorded_at=_iso(current),
                                )
                            continue
                        active_plan_count += 1
                        base_plan_blockers = [
                            item for item in (plan.get("blockers") or [])
                            if not _is_recomputed_plan_blocker(str(item))
                        ]
                        if blockers:
                            next_blockers = sorted(set(base_plan_blockers + blockers))
                            previous = str(plan["state"])
                            with connect(db_path) as conn:
                                conn.execute(
                                    "UPDATE option_plans SET state='QUOTE_BLOCKED', blockers_json=?, updated_at=? WHERE plan_id=?",
                                    (_json(next_blockers), _iso(current), plan["plan_id"]),
                                )
                                conn.commit()
                            if previous != "QUOTE_BLOCKED":
                                record_option_state_event(
                                    db_path,
                                    entity_type="plan",
                                    entity_id=plan["plan_id"],
                                    opportunity_id=opportunity["opportunity_id"],
                                    plan_id=plan["plan_id"],
                                    previous_state=previous,
                                    next_state="QUOTE_BLOCKED",
                                    event_type="dynamic_gate_blocked",
                                    reasons=next_blockers,
                                    material_state_hash=_hash([plan["plan_id"], "QUOTE_BLOCKED", next_blockers]),
                                    recorded_at=_iso(current),
                                )
                            continue
                        confirmation_decision_at = _confirmation_decision_time(db_path, plan["plan_id"])
                        if confirmation_decision_at is None:
                            confirmation_decision_at = current
                            record_option_state_event(
                                db_path,
                                entity_type="plan",
                                entity_id=plan["plan_id"],
                                opportunity_id=opportunity["opportunity_id"],
                                plan_id=plan["plan_id"],
                                previous_state=str(plan["state"]),
                                next_state=str(plan["state"]),
                                event_type="decision_committed",
                                reasons=("Closed 5-minute confirmation completed; decision time is now frozen.",),
                                material_state_hash=_hash([plan["plan_id"], confirmation, "decision_committed"]),
                                recorded_at=_iso(confirmation_decision_at),
                            )
                        snapshot = option_contract_snapshot(plan["contract_symbol"], db_path)
                        quote_evidence = persist_option_quote_evidence(db_path, plan["plan_id"], snapshot, "entry_check")
                        quote_blockers, plan_warnings = _option_screen(snapshot, plan["horizon_group"], confirmation_decision_at)
                        plan_blockers = sorted(set(base_plan_blockers + quote_blockers))
                        warnings.extend(plan_warnings)
                        state = "CONFIRMED" if not plan_blockers else "QUOTE_BLOCKED"
                        previous = str(plan["state"])
                        with connect(db_path) as conn:
                            conn.execute(
                                "UPDATE option_plans SET state=?, blockers_json=?, reference_quote_json=?, scenario_json=?, updated_at=? WHERE plan_id=?",
                                (state, _json(plan_blockers), _json(snapshot), _json(_contract_scenarios(snapshot, _number((opportunity.get("evidence") or {}).get("premarket", {}).get("last")) or 0)), _iso(current), plan["plan_id"]),
                            )
                            conn.commit()
                        if previous != state:
                            record_option_state_event(
                                db_path,
                                entity_type="plan",
                                entity_id=plan["plan_id"],
                                opportunity_id=opportunity["opportunity_id"],
                                plan_id=plan["plan_id"],
                                previous_state=previous,
                                next_state=state,
                                event_type="quote_evaluated",
                                reasons=plan_blockers,
                                material_state_hash=_hash([plan["plan_id"], state, quote_evidence["content_hash"], plan_blockers]),
                                recorded_at=_iso(current),
                            )
                        if not plan_blockers and quote_evidence["strict_fill_eligible"]:
                            strict_plan_count += 1
                            _open_simulation_from_evidence(db_path, plan["plan_id"], quote_evidence["quote_evidence_id"])
                    new_state = "CONFIRMED" if strict_plan_count else ("QUOTE_BLOCKED" if active_plan_count else "CANCELLED")
                    if active_plan_count and not strict_plan_count:
                        blockers.append("No contract passed the strict post-decision BBO contract.")
                    if not active_plan_count:
                        blockers.append("All contract entry windows have closed.")
        material_hash = _hash([opportunity["opportunity_id"], new_state, confirmation, sorted(set(blockers))])
        with connect(db_path) as conn:
            conn.execute(
                """
                UPDATE option_opportunities
                SET status=?, material_state_hash=?, evidence_json=?, blockers_json=?, warnings_json=?, updated_at=?
                WHERE opportunity_id=?
                """,
                (
                    new_state,
                    material_hash,
                    _json({**opportunity["evidence"], "intraday_confirmation": confirmation}),
                    _json(sorted(set(blockers))),
                    _json(sorted(set(warnings))),
                    _iso(current),
                    opportunity["opportunity_id"],
                ),
            )
            conn.commit()
        current_opportunity = option_signal_detail(db_path, opportunity["opportunity_id"])
        if new_state != old_state:
            updated += 1
            record_option_state_event(
                db_path,
                entity_type="opportunity",
                entity_id=opportunity["opportunity_id"],
                opportunity_id=opportunity["opportunity_id"],
                previous_state=old_state,
                next_state=new_state,
                event_type="state_changed",
                reasons=sorted(set(blockers)),
                material_state_hash=material_hash,
                recorded_at=_iso(current),
            )
            _create_alert(db_path, current_opportunity, hub=hub)
        results.append(current_opportunity)
    run_summary = {"updated": updated, "evaluated": len(results), "opra_status": status_payload.get("opra_status")}
    _persist_run(
        db_path,
        market_day=local_day,
        run_type="intraday",
        data_hash=_hash([local_day, run_summary, [item["material_state_hash"] for item in results]]),
        status="completed",
        data_status="limited" if status_payload.get("opra_status") != "available" else "available",
        summary=run_summary,
        generated_at=_iso(current),
    )
    return {"status": "completed", "market_date": local_day, **run_summary, "opportunities": results}


def _open_simulation_from_evidence(db_path: Path, plan_id: str, evidence_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        plan = conn.execute("SELECT * FROM option_plans WHERE plan_id = ?", (plan_id,)).fetchone()
        evidence = conn.execute("SELECT * FROM option_quote_evidence WHERE quote_evidence_id = ?", (evidence_id,)).fetchone()
        existing = conn.execute("SELECT * FROM option_outcomes WHERE plan_id = ?", (plan_id,)).fetchone()
    if existing and existing["status"] != "not_entered":
        return dict(existing)
    if not plan or not evidence:
        raise ValueError("Unknown plan or quote evidence.")
    if evidence["plan_id"] != plan_id or evidence["contract_symbol"] != plan["contract_symbol"]:
        raise ValueError("Quote evidence does not belong to this plan and contract.")
    if plan["state"] != "CONFIRMED":
        raise ValueError("Only an intraday-confirmed option plan can open a simulation.")
    decision = _confirmation_decision_time(db_path, plan_id) or _parse_time(plan["decision_committed_at"])
    received = _parse_time(evidence["received_at"])
    event_time = _parse_time(evidence["bbo_event_time"])
    if (
        not evidence["strict_fill_eligible"]
        or decision is None
        or received is None
        or event_time is None
        or received <= decision
        or event_time <= decision
        or abs((received - event_time).total_seconds()) > OPTION_BBO_MAX_AGE_SECONDS
    ):
        raise ValueError("Simulation entry requires strict post-decision BBO evidence.")
    ask = _number(evidence["ask"])
    if ask is None or ask <= 0:
        raise ValueError("Simulation entry requires a positive ask.")
    now = _iso()
    outcome_id = f"option-outcome-{uuid.uuid4().hex[:20]}"
    with connect(db_path) as conn:
        if existing:
            outcome_id = existing["outcome_id"]
            conn.execute(
                """
                UPDATE option_outcomes
                SET status='open', entry_quote_evidence_id=?, entry_time=?, entry_price=?,
                    outcome_reason='strict_ask_entry', censor_reason='', updated_at=?
                WHERE outcome_id=?
                """,
                (evidence_id, evidence["received_at"], ask, now, outcome_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO option_outcomes(
                  outcome_id, plan_id, status, entry_quote_evidence_id, exit_quote_evidence_id,
                  entry_time, entry_price, exit_time, exit_price, contracts, multiplier,
                  fees, gross_pnl, net_pnl, return_pct, outcome_reason, censor_reason,
                  execution_policy_id, created_at, updated_at
                ) VALUES (?, ?, 'open', ?, NULL, ?, ?, NULL, NULL, 1, 100, NULL, NULL, NULL, NULL, 'strict_ask_entry', '', ?, ?, ?)
                """,
                (outcome_id, plan_id, evidence_id, evidence["received_at"], ask, OPTION_SIMULATION_POLICY_VERSION, now, now),
            )
        conn.commit()
    return option_simulation_detail(db_path, outcome_id)


def record_option_simulation(db_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action") or "observe").lower()
    plan_id = str(payload.get("plan_id") or "")
    if action == "observe":
        with connect(db_path) as conn:
            plan = conn.execute("SELECT * FROM option_plans WHERE plan_id = ?", (plan_id,)).fetchone()
            existing = conn.execute("SELECT * FROM option_outcomes WHERE plan_id = ?", (plan_id,)).fetchone()
        if not plan:
            raise ValueError("Unknown option plan.")
        if existing:
            return option_simulation_detail(db_path, existing["outcome_id"])
        now = _iso()
        outcome_id = f"option-outcome-{uuid.uuid4().hex[:20]}"
        with connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO option_outcomes(
                  outcome_id, plan_id, status, contracts, multiplier, outcome_reason,
                  censor_reason, execution_policy_id, created_at, updated_at
                ) VALUES (?, ?, 'not_entered', 1, 100, 'observation_registered',
                          'awaiting_strict_post_decision_bbo', ?, ?, ?)
                """,
                (outcome_id, plan_id, OPTION_SIMULATION_POLICY_VERSION, now, now),
            )
            conn.commit()
        return option_simulation_detail(db_path, outcome_id)
    if action not in {"open", "close"}:
        raise ValueError("action must be observe, open, or close.")
    contract = ""
    with connect(db_path) as conn:
        plan = conn.execute("SELECT * FROM option_plans WHERE plan_id = ?", (plan_id,)).fetchone()
        outcome = conn.execute("SELECT * FROM option_outcomes WHERE plan_id = ?", (plan_id,)).fetchone()
    if not plan:
        raise ValueError("Unknown option plan.")
    contract = plan["contract_symbol"]
    snapshot = option_contract_snapshot(contract, db_path)
    evidence = persist_option_quote_evidence(db_path, plan_id, snapshot, "entry" if action == "open" else "exit")
    if action == "open":
        return _open_simulation_from_evidence(db_path, plan_id, evidence["quote_evidence_id"])
    if not outcome or outcome["status"] != "open":
        raise ValueError("Only an open simulation can be closed.")
    entry_time = _parse_time(outcome["entry_time"])
    received = _parse_time(evidence["received_at"])
    event_time = _parse_time(evidence["bbo_event_time"])
    if (
        not evidence["strict_fill_eligible"]
        or entry_time is None
        or received is None
        or event_time is None
        or received <= entry_time
        or event_time <= entry_time
        or abs((received - event_time).total_seconds()) > OPTION_BBO_MAX_AGE_SECONDS
    ):
        raise ValueError("Simulation exit requires strict BBO evidence received after entry.")
    bid = _number(evidence.get("bid"))
    if bid is None or bid < 0:
        raise ValueError("Simulation exit requires a valid bid.")
    entry = float(outcome["entry_price"])
    multiplier = float(outcome["multiplier"])
    gross = (bid - entry) * multiplier
    supplied_fees = payload.get("fees")
    fees = _number(supplied_fees) if supplied_fees is not None else None
    net = gross - fees if fees is not None else None
    return_pct = net / (entry * multiplier) * 100 if entry > 0 and net is not None else None
    now = _iso()
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE option_outcomes
            SET status='completed', exit_quote_evidence_id=?, exit_time=?, exit_price=?,
                fees=?, gross_pnl=?, net_pnl=?, return_pct=?, outcome_reason=?, censor_reason='', updated_at=?
            WHERE outcome_id=?
            """,
            (evidence["quote_evidence_id"], evidence["received_at"], bid, fees, gross, net, return_pct, str(payload.get("reason") or "manual_research_close")[:120], now, outcome["outcome_id"]),
        )
        conn.commit()
    return option_simulation_detail(db_path, outcome["outcome_id"])


def option_simulation_detail(db_path: Path, outcome_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM option_outcomes WHERE outcome_id = ?", (outcome_id,)).fetchone()
    if not row:
        raise ValueError("Unknown option simulation.")
    return {**dict(row), "simulated_only": True, "one_contract_only": True, "manual_execution_only": True}


def list_option_simulations(db_path: Path, *, limit: int = 200) -> dict[str, Any]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM option_outcomes ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return {
        "outcomes": [{**dict(row), "simulated_only": True, "one_contract_only": True} for row in rows],
        "count": len(rows),
        "legacy_paper_excluded": True,
        "order_submission_enabled": False,
    }


def option_signal_detail(db_path: Path, opportunity_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM option_opportunities WHERE opportunity_id = ?", (opportunity_id,)).fetchone()
        plan_rows = conn.execute("SELECT * FROM option_plans WHERE opportunity_id = ? ORDER BY horizon_group", (opportunity_id,)).fetchall()
        watch_rows = conn.execute(
            """
            SELECT w.* FROM option_watchlist w
            JOIN option_plans p ON p.plan_id=w.plan_id
            WHERE p.opportunity_id=? AND w.status='active'
            """,
            (opportunity_id,),
        ).fetchall()
        simulation_rows = conn.execute(
            """
            SELECT x.* FROM option_outcomes x
            JOIN option_plans p ON p.plan_id=x.plan_id
            WHERE p.opportunity_id=?
            """,
            (opportunity_id,),
        ).fetchall()
        manual_rows = conn.execute(
            """
            SELECT x.* FROM option_manual_outcomes x
            JOIN option_plans p ON p.plan_id=x.plan_id
            WHERE p.opportunity_id=?
            """,
            (opportunity_id,),
        ).fetchall()
    if not row:
        raise ValueError("Unknown option opportunity.")
    return {
        **_opportunity_from_row(row),
        "plans": [_plan_from_row(item) for item in plan_rows],
        "watchlist": [dict(item) for item in watch_rows],
        "simulation_outcomes": [dict(item) for item in simulation_rows],
        "manual_outcomes": [dict(item) for item in manual_rows],
        "manual_execution_only": True,
        "order_submission_enabled": False,
    }


def list_option_signals(db_path: Path, *, current_only: bool = True, limit: int = 100, now: datetime | None = None) -> dict[str, Any]:
    where = ""
    if current_only:
        where = """
        WHERE (
          run_id = (
            SELECT run_id FROM option_radar_runs
            WHERE run_type = 'premarket' AND market_date = ?
            ORDER BY generated_at DESC, created_at DESC
            LIMIT 1
          )
          OR EXISTS (
            SELECT 1 FROM option_plans p
            LEFT JOIN option_watchlist w ON w.plan_id=p.plan_id AND w.status='active'
            LEFT JOIN option_outcomes x ON x.plan_id=p.plan_id AND x.status='open'
            LEFT JOIN option_manual_outcomes m ON m.plan_id=p.plan_id AND m.status='open'
            WHERE p.opportunity_id=option_opportunities.opportunity_id
              AND (w.watch_id IS NOT NULL OR x.outcome_id IS NOT NULL OR m.manual_outcome_id IS NOT NULL)
          )
        )
          AND (
            status IN ('PREMARKET_WATCH','WAIT_OPEN_CONFIRMATION','QUOTE_BLOCKED','CONFIRMED','EXIT_REVIEW')
            OR EXISTS (
              SELECT 1 FROM option_plans p
              LEFT JOIN option_watchlist w ON w.plan_id=p.plan_id AND w.status='active'
              LEFT JOIN option_outcomes x ON x.plan_id=p.plan_id AND x.status='open'
              LEFT JOIN option_manual_outcomes m ON m.plan_id=p.plan_id AND m.status='open'
              WHERE p.opportunity_id=option_opportunities.opportunity_id
                AND (w.watch_id IS NOT NULL OR x.outcome_id IS NOT NULL OR m.manual_outcome_id IS NOT NULL)
            )
          )
        """
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM option_opportunities {where} ORDER BY signal_time DESC, rank_value LIMIT ?",
            (*((_now(now).astimezone(NEW_YORK).date().isoformat(),) if current_only else ()), max(1, min(int(limit), 500))),
        ).fetchall()
    items = [option_signal_detail(db_path, row["opportunity_id"]) for row in rows]
    return {
        "opportunities": items,
        "count": len(items),
        "policy_version": OPTION_RADAR_POLICY_VERSION,
        "manual_execution_only": True,
        "order_submission_enabled": False,
    }


def list_option_watchlist(db_path: Path, *, active_only: bool = True, limit: int = 200) -> dict[str, Any]:
    where = "WHERE w.status='active'" if active_only else ""
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT w.*, p.opportunity_id, p.horizon_group, p.contract_symbol,
                   p.expiry_date, p.strike_price, p.direction, p.state AS plan_state,
                   p.expires_at, o.symbol, o.status AS opportunity_status
            FROM option_watchlist w
            JOIN option_plans p ON p.plan_id=w.plan_id
            JOIN option_opportunities o ON o.opportunity_id=p.opportunity_id
            {where}
            ORDER BY w.updated_at DESC LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return {
        "items": [dict(row) for row in rows],
        "count": len(rows),
        "active_only": active_only,
        "manual_execution_only": True,
    }


def set_option_watch(db_path: Path, plan_id: str, *, notes: str = "") -> dict[str, Any]:
    now = _iso()
    watch_id = f"option-watch-{_hash(plan_id)}"
    with connect(db_path) as conn:
        plan = conn.execute("SELECT * FROM option_plans WHERE plan_id=?", (plan_id,)).fetchone()
        if not plan:
            raise ValueError("Unknown option plan.")
        conn.execute(
            """
            INSERT INTO option_watchlist(watch_id, plan_id, status, notes, created_at, updated_at)
            VALUES (?, ?, 'active', ?, ?, ?)
            ON CONFLICT(plan_id) DO UPDATE SET
              status='active', notes=excluded.notes, updated_at=excluded.updated_at
            """,
            (watch_id, plan_id, str(notes)[:1000], now, now),
        )
        conn.commit()
    record_option_state_event(
        db_path,
        entity_type="plan",
        entity_id=plan_id,
        opportunity_id=plan["opportunity_id"],
        plan_id=plan_id,
        previous_state=str(plan["state"]),
        next_state=str(plan["state"]),
        event_type="watch_started",
        reasons=(str(notes)[:1000],) if notes else (),
        material_state_hash=_hash([plan_id, "watch_started", now]),
        recorded_at=now,
        actor="user",
    )
    return next(item for item in list_option_watchlist(db_path, active_only=True)["items"] if item["plan_id"] == plan_id)


def remove_option_watch(db_path: Path, plan_id: str) -> dict[str, Any]:
    now = _iso()
    with connect(db_path) as conn:
        plan = conn.execute("SELECT * FROM option_plans WHERE plan_id=?", (plan_id,)).fetchone()
        if not plan:
            raise ValueError("Unknown option plan.")
        cursor = conn.execute(
            "UPDATE option_watchlist SET status='removed', updated_at=? WHERE plan_id=? AND status='active'",
            (now, plan_id),
        )
        conn.commit()
    if cursor.rowcount:
        record_option_state_event(
            db_path,
            entity_type="plan",
            entity_id=plan_id,
            opportunity_id=plan["opportunity_id"],
            plan_id=plan_id,
            previous_state=str(plan["state"]),
            next_state=str(plan["state"]),
            event_type="watch_stopped",
            material_state_hash=_hash([plan_id, "watch_stopped", now]),
            recorded_at=now,
            actor="user",
        )
    return {"plan_id": plan_id, "status": "removed", "changed": bool(cursor.rowcount)}


def list_option_manual_outcomes(db_path: Path, *, limit: int = 200) -> dict[str, Any]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT x.*, p.contract_symbol, p.horizon_group, p.direction,
                   o.symbol, o.opportunity_id
            FROM option_manual_outcomes x
            JOIN option_plans p ON p.plan_id=x.plan_id
            JOIN option_opportunities o ON o.opportunity_id=p.opportunity_id
            ORDER BY x.updated_at DESC LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return {
        "items": [dict(row) for row in rows],
        "count": len(rows),
        "source": "user_reported",
        "simulation_results_excluded": True,
    }


def record_option_manual_outcome(db_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    plan_id = str(payload.get("plan_id") or "")
    status = str(payload.get("status") or "observing").lower()
    allowed = {"not_entered", "observing", "open", "completed", "censored"}
    if status not in allowed:
        raise ValueError(f"status must be one of: {', '.join(sorted(allowed))}.")
    with connect(db_path) as conn:
        plan = conn.execute("SELECT * FROM option_plans WHERE plan_id=?", (plan_id,)).fetchone()
        existing = conn.execute("SELECT * FROM option_manual_outcomes WHERE plan_id=?", (plan_id,)).fetchone()
    if not plan:
        raise ValueError("Unknown option plan.")
    entry_price = _number(payload.get("entry_price"))
    exit_price = _number(payload.get("exit_price"))
    contracts = int(payload["contracts"]) if payload.get("contracts") is not None else None
    if contracts is not None and contracts < 1:
        raise ValueError("contracts must be at least 1 when supplied.")
    if status in {"open", "completed"} and (entry_price is None or entry_price <= 0):
        raise ValueError("An open or completed manual result requires a positive entry price.")
    if status == "completed" and (exit_price is None or exit_price < 0):
        raise ValueError("A completed manual result requires a valid exit price.")
    fees = _number(payload.get("fees")) if payload.get("fees") is not None else None
    if fees is not None and fees < 0:
        raise ValueError("fees cannot be negative.")
    multiplier = float(payload.get("multiplier") or 100)
    gross = None
    net = None
    return_pct = None
    if status == "completed" and entry_price is not None and exit_price is not None and contracts is not None:
        gross = (exit_price - entry_price) * multiplier * contracts
        net = gross - fees if fees is not None else None
        return_pct = net / (entry_price * multiplier * contracts) * 100 if net is not None else None
    now = _iso()
    manual_id = existing["manual_outcome_id"] if existing else f"option-manual-{uuid.uuid4().hex[:20]}"
    created_at = existing["created_at"] if existing else now
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO option_manual_outcomes(
              manual_outcome_id, plan_id, status, entry_time, entry_price,
              exit_time, exit_price, contracts, multiplier, fees, gross_pnl,
              net_pnl, return_pct, outcome_reason, notes, source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'user_reported', ?, ?)
            ON CONFLICT(plan_id) DO UPDATE SET
              status=excluded.status, entry_time=excluded.entry_time,
              entry_price=excluded.entry_price, exit_time=excluded.exit_time,
              exit_price=excluded.exit_price, contracts=excluded.contracts,
              multiplier=excluded.multiplier, fees=excluded.fees,
              gross_pnl=excluded.gross_pnl, net_pnl=excluded.net_pnl,
              return_pct=excluded.return_pct, outcome_reason=excluded.outcome_reason,
              notes=excluded.notes, updated_at=excluded.updated_at
            """,
            (
                manual_id,
                plan_id,
                status,
                payload.get("entry_time"),
                entry_price,
                payload.get("exit_time"),
                exit_price,
                contracts,
                multiplier,
                fees,
                gross,
                net,
                return_pct,
                str(payload.get("reason") or "")[:160],
                str(payload.get("notes") or "")[:2000],
                created_at,
                now,
            ),
        )
        conn.commit()
    record_option_state_event(
        db_path,
        entity_type="plan",
        entity_id=plan_id,
        opportunity_id=plan["opportunity_id"],
        plan_id=plan_id,
        previous_state=str(existing["status"] if existing else ""),
        next_state=status,
        event_type="manual_outcome_updated",
        reasons=(str(payload.get("reason") or ""),),
        material_state_hash=_hash([manual_id, status, entry_price, exit_price, fees, payload.get("reason")]),
        recorded_at=now,
        actor="user",
    )
    return next(item for item in list_option_manual_outcomes(db_path)["items"] if item["plan_id"] == plan_id)


def latest_premarket_report(db_path: Path, market_date: str = "") -> dict[str, Any]:
    query = "SELECT * FROM option_radar_runs WHERE run_type='premarket'"
    values: tuple[Any, ...] = ()
    if market_date:
        query += " AND market_date=?"
        values = (market_date,)
    query += " ORDER BY generated_at DESC LIMIT 1"
    with connect(db_path) as conn:
        row = conn.execute(query, values).fetchone()
    if not row:
        return {"status": "not_run", "opportunities": [], "policy_version": OPTION_RADAR_POLICY_VERSION}
    run = _row_payload(row, ("universe_json", "summary_json"))
    with connect(db_path) as conn:
        opportunity_rows = conn.execute("SELECT opportunity_id FROM option_opportunities WHERE run_id=? ORDER BY rank_value", (run["run_id"],)).fetchall()
    return {
        **run,
        "opportunities": [option_signal_detail(db_path, item["opportunity_id"]) for item in opportunity_rows],
        "manual_execution_only": True,
        "order_submission_enabled": False,
    }


def option_data_audit(db_path: Path) -> dict[str, Any]:
    status = option_market_status()
    clock_requested_at = _now()
    clock_quote = api_stock_quote("SPY", db_path, isolated=True)
    clock_received_at = _now()
    clock_candidates = [
        _parse_time(clock_quote.get("quote_time")),
        _parse_time((clock_quote.get("pre_market") or {}).get("event_time")),
        _parse_time((clock_quote.get("post_market") or {}).get("event_time")),
    ]
    provider_event_at = max((item for item in clock_candidates if item is not None), default=None)
    provider_ahead_seconds = (provider_event_at - clock_received_at).total_seconds() if provider_event_at else None
    with connect(db_path) as conn:
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "option_contract_snapshots",
                "option_radar_runs",
                "option_opportunities",
                "option_plans",
                "option_quote_evidence",
                "option_outcomes",
                "option_underlying_evidence",
                "option_event_evidence",
                "option_state_events",
                "option_watchlist",
                "option_manual_outcomes",
                "option_scan_jobs",
            )
        }
    event_payloads = {symbol: corporate_event_context(db_path, symbol) for symbol in RADAR_UNIVERSE}
    event_states = {symbol: payload.get("status") for symbol, payload in event_payloads.items()}
    event_ready = sum(payload.get("trade_eligible") is True for payload in event_payloads.values())
    with connect(db_path) as conn:
        strict_quote_count = int(conn.execute("SELECT COUNT(*) FROM option_quote_evidence WHERE strict_fill_eligible=1").fetchone()[0])
    blockers = []
    if status.get("opra_status") != "available":
        blockers.append("OPRA realtime options entitlement was not detected.")
    if counts["option_quote_evidence"] == 0:
        blockers.append("No timestamped option BBO evidence has been collected.")
    if event_ready < len(RADAR_UNIVERSE):
        blockers.append("Earnings/dividend/macro event coverage is incomplete.")
    if provider_ahead_seconds is not None and provider_ahead_seconds > 30:
        blockers.append(f"Provider event time is {int(provider_ahead_seconds)} seconds ahead of the local clock.")
    if strict_quote_count == 0:
        blockers.append("Longbridge latest-trade timestamp does not prove BBO event time; no native-timestamp BBO evidence exists.")
    performance_blockers = []
    if counts["option_outcomes"] == 0:
        performance_blockers.append("No completed option outcomes exist.")
    performance_blockers.append("Historical option bid/ask, contract adjustments, and outcome data are not available.")
    return {
        "as_of": _iso(),
        "provider": status,
        "counts": counts,
        "event_calendar": {"ready_symbols": event_ready, "total_symbols": len(RADAR_UNIVERSE), "by_symbol": event_states,
                           "coverage_details": event_payloads, "stock_strategy_gate_unchanged": True},
        "clock_contract": {
            "request_started_at": _iso(clock_requested_at),
            "request_received_at": _iso(clock_received_at),
            "request_round_trip_ms": round((clock_received_at - clock_requested_at).total_seconds() * 1000.0, 3),
            "local_utc": _iso(clock_received_at),
            "provider_event_time": _iso(provider_event_at) if provider_event_at else None,
            "provider_event_time_semantics": "latest_trade_or_extended_session_event_time_not_bbo_time",
            "provider_ahead_seconds": provider_ahead_seconds,
            "status": "unknown" if provider_ahead_seconds is None else "conflict" if provider_ahead_seconds > 30 else "no_future_conflict_detected",
            "system_clock_error_proven": False,
        },
        "strict_simulated_fill_ready": not blockers,
        "blockers": blockers,
        "performance_blockers": performance_blockers,
        "purchase_approval_required": True,
        "no_purchase_performed": True,
        "manual_execution_only": True,
        "order_submission_enabled": False,
    }


def option_research_report(db_path: Path) -> dict[str, Any]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT o.*, p.horizon_group, p.direction AS plan_direction,
                   x.status AS outcome_status, x.net_pnl, x.entry_price, x.multiplier
            FROM option_outcomes x
            JOIN option_plans p ON p.plan_id = x.plan_id
            JOIN option_opportunities o ON o.opportunity_id = p.opportunity_id
            ORDER BY x.updated_at
            """
        ).fetchall()
    groups: dict[str, list[dict[str, Any]]] = {}
    state_counts: dict[str, int] = {}
    for row in rows:
        item = dict(row)
        state = str(item.get("outcome_status") or "unknown")
        state_counts[state] = state_counts.get(state, 0) + 1
        key = f"{item['horizon_group']}|{item['direction']}"
        groups.setdefault(key, []).append(item)
    metrics: dict[str, Any] = {}
    for key, items in groups.items():
        completed = [item for item in items if item.get("outcome_status") == "completed" and item.get("net_pnl") is not None]
        wins = [float(item["net_pnl"]) for item in completed if float(item["net_pnl"]) > 0]
        losses = [float(item["net_pnl"]) for item in completed if float(item["net_pnl"]) < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        average_win = sum(wins) / len(wins) if wins else None
        average_loss = abs(sum(losses) / len(losses)) if losses else None
        metrics[key] = {
            "completed": len(completed),
            "win_rate_pct": len(wins) / len(completed) * 100 if completed else None,
            "average_win": average_win,
            "average_loss": average_loss,
            "payoff": average_win / average_loss if average_win is not None and average_loss else None,
            "profit_factor": gross_profit / gross_loss if gross_loss else None,
            "net_expectancy": sum(float(item["net_pnl"]) for item in completed) / len(completed) if completed else None,
            "evidence_status": "eligible_for_validation" if len(completed) >= 200 else "limited_evidence",
        }
    return {
        "as_of": _iso(),
        "policy_version": OPTION_RADAR_POLICY_VERSION,
        "state_counts": state_counts,
        "metrics_by_horizon_and_direction": metrics,
        "target_gates": {"minimum_completed_per_claim": 200, "profit_factor": 1.30, "payoff": 1.8, "double_cost_profit_factor": 1.05},
        "performance_status": "PERFORMANCE_UNPROVEN" if not metrics or any(value["evidence_status"] != "eligible_for_validation" for value in metrics.values()) else "READY_FOR_FORMAL_REVIEW",
        "historical_underlying_results_excluded": True,
        "legacy_option_paper_excluded": True,
        "simulated_results_are_not_live_performance": True,
    }


def option_radar_status(db_path: Path) -> dict[str, Any]:
    from .option_runtime import runtime_status
    latest = latest_premarket_report(db_path)
    audit = option_data_audit(db_path)
    return {
        "policy_version": OPTION_RADAR_POLICY_VERSION,
        "latest_premarket": {
            "run_id": latest.get("run_id"),
            "market_date": latest.get("market_date"),
            "generated_at": latest.get("generated_at"),
            "status": latest.get("status"),
            "opportunity_count": len(latest.get("opportunities") or []),
        },
        "data_status": "blocked_for_strict_option_fills" if not audit["strict_simulated_fill_ready"] else "available",
        "opra_status": (audit.get("provider") or {}).get("opra_status"),
        "current_market_date": _now().astimezone(NEW_YORK).date().isoformat(),
        "report_is_current": latest.get("market_date") == _now().astimezone(NEW_YORK).date().isoformat(),
        "runtime_checkpoints": runtime_status(db_path),
        "manual_execution_only": True,
        "order_submission_enabled": False,
    }
