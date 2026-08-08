from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .longbridge_provider import longbridge_runtime
from .realtime_instructions import get_instruction, list_instructions
from .stock_signals import LONG_BRIDGE_TIMEOUT_SECONDS, api_stock_quote, longbridge_env_ready, longbridge_symbol
from .stock_store import connect


OPTION_EXPRESSION_VERSION = "option_expression_v1.0.0"
MIN_DTE = 14
MAX_DTE = 45
MIN_DELTA = 0.40
MAX_DELTA = 0.65
MAX_SPREAD_PCT = 8.0
MIN_OPEN_INTEREST = 500
MIN_VOLUME = 100


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None


def _attr(value: Any, *names: str) -> Any:
    if isinstance(value, dict):
        for name in names:
            if name in value:
                return value[name]
        return None
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _timestamp(value: Any) -> str | None:
    if isinstance(value, datetime):
        return (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).isoformat()
    number = _number(value)
    if number is not None:
        return datetime.fromtimestamp(number, tz=UTC).isoformat()
    return str(value) if value else None


def _iso_date(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "")
    if len(text) == 6 and text.isdigit():
        return f"20{text[:2]}-{text[2:4]}-{text[4:6]}"
    return text[:10]


def option_market_status() -> dict[str, Any]:
    if not longbridge_env_ready():
        return {
            "provider": "longbridge",
            "status": "missing_config",
            "opra_status": "unknown",
            "message": "Longbridge credentials are not configured.",
            "read_only_research": True,
        }
    try:
        packages = list(longbridge_runtime().quote_packages(min(LONG_BRIDGE_TIMEOUT_SECONDS, 5)) or [])
        package_payload = [str(item)[:300] for item in packages]
        encoded = " ".join(package_payload).lower()
        opra = any(token in encoded for token in ("opra", "option", "us option"))
        return {
            "provider": "longbridge",
            "status": "available",
            "opra_status": "available" if opra else "not_detected",
            "quote_packages": package_payload,
            "message": "OPRA package detected." if opra else "OPRA US options realtime permission was not detected.",
            "read_only_research": True,
            "order_submission_enabled": False,
        }
    except Exception as exc:  # pragma: no cover - provider/network dependent
        return {
            "provider": "longbridge",
            "status": "degraded",
            "opra_status": "unknown",
            "message": f"{type(exc).__name__}: {str(exc)[:240]}",
            "read_only_research": True,
            "order_submission_enabled": False,
        }


def option_expiries(symbol: str) -> dict[str, Any]:
    underlying = symbol.upper().split(".")[0]
    if not longbridge_env_ready():
        return {"symbol": underlying, "expiries": [], "provider_status": "missing_config", "read_only_research": True}
    try:
        rows = longbridge_runtime().option_expiry_dates(longbridge_symbol(underlying), LONG_BRIDGE_TIMEOUT_SECONDS)
        expiries = sorted({_iso_date(_attr(row, "expiry_date", "date") or row) for row in list(rows or [])})
        return {"symbol": underlying, "expiries": expiries, "provider_status": "available", "source": "longbridge_option_chain"}
    except Exception as exc:  # pragma: no cover - provider/network dependent
        return {"symbol": underlying, "expiries": [], "provider_status": "unavailable", "provider_errors": [str(exc)], "source": "longbridge_option_chain"}


def option_chain(symbol: str, expiry: str) -> dict[str, Any]:
    underlying = symbol.upper().split(".")[0]
    expiry_date = date.fromisoformat(expiry)
    try:
        rows = longbridge_runtime().option_chain(longbridge_symbol(underlying), expiry_date, LONG_BRIDGE_TIMEOUT_SECONDS)
        contracts = []
        for row in list(rows or []):
            strike = _number(_attr(row, "price", "strike_price", "strike"))
            standard_value = _attr(row, "standard", "is_standard")
            contracts.append({
                "strike_price": strike,
                "call_symbol": str(_attr(row, "call_symbol") or ""),
                "put_symbol": str(_attr(row, "put_symbol") or ""),
                "is_standard": str(standard_value).lower() not in {"false", "0", "none"},
            })
        return {
            "symbol": underlying,
            "expiry_date": expiry,
            "contracts": contracts,
            "provider_status": "available",
            "source": "longbridge_option_chain",
            "read_only_research": True,
        }
    except Exception as exc:  # pragma: no cover - provider/network dependent
        return {
            "symbol": underlying,
            "expiry_date": expiry,
            "contracts": [],
            "provider_status": "unavailable",
            "provider_errors": [str(exc)],
            "source": "longbridge_option_chain",
            "read_only_research": True,
        }


def _greek_indexes() -> list[Any]:
    from longbridge.openapi import CalcIndex  # type: ignore

    return [
        CalcIndex.ImpliedVolatility,
        CalcIndex.OpenInterest,
        CalcIndex.Delta,
        CalcIndex.Gamma,
        CalcIndex.Theta,
        CalcIndex.Vega,
        CalcIndex.Rho,
        CalcIndex.Volume,
    ]


def option_contract_snapshot(contract_symbol: str, db_path: Path | None = None) -> dict[str, Any]:
    contract = contract_symbol.upper()
    try:
        quote_rows = list(longbridge_runtime().option_quotes([contract], LONG_BRIDGE_TIMEOUT_SECONDS) or [])
        quote = quote_rows[0] if quote_rows else None
        if quote is None:
            raise RuntimeError("Longbridge returned no option quote.")
        calc_rows = list(longbridge_runtime().calc_indexes([contract], _greek_indexes(), LONG_BRIDGE_TIMEOUT_SECONDS) or [])
        calc = calc_rows[0] if calc_rows else None
        extend = _attr(quote, "option_extend") or {}
        bid = ask = None
        depth_status = "unavailable"
        try:
            depth, _ = longbridge_runtime().depth(contract, LONG_BRIDGE_TIMEOUT_SECONDS)
            bids = list(_attr(depth, "bids", "bid") or [])
            asks = list(_attr(depth, "asks", "ask") or [])
            bid = _number(_attr(bids[0], "price")) if bids else None
            ask = _number(_attr(asks[0], "price")) if asks else None
            depth_status = "available" if bid is not None and ask is not None and ask >= bid else "unavailable"
        except Exception:
            pass
        mid = (bid + ask) / 2 if bid is not None and ask is not None and ask >= bid else None
        spread_pct = ((ask - bid) / mid * 100) if mid and bid is not None and ask is not None else None
        underlying_provider = str(_attr(extend, "underlying_symbol") or "").split(".")[0]
        expiry = _iso_date(_attr(extend, "expiry_date") or _attr(calc, "expiry_date"))
        direction_raw = str(_attr(extend, "direction") or "").upper()
        direction = "CALL" if direction_raw in {"C", "CALL"} else "PUT"
        multiplier = _number(_attr(extend, "contract_multiplier", "contract_size")) or 100.0
        payload = {
            "contract_symbol": contract,
            "underlying_symbol": underlying_provider,
            "expiry_date": expiry,
            "strike_price": _number(_attr(extend, "strike_price") or _attr(calc, "strike_price")),
            "direction": direction,
            "is_standard": multiplier == 100,
            "contract_multiplier": multiplier,
            "bid": bid,
            "ask": ask,
            "last": _number(_attr(quote, "last_done", "last")),
            "mid": round(mid, 4) if mid is not None else None,
            "spread_pct": round(spread_pct, 4) if spread_pct is not None else None,
            "implied_volatility": _number(_attr(extend, "implied_volatility") or _attr(calc, "implied_volatility")),
            "historical_volatility": _number(_attr(extend, "historical_volatility")),
            "open_interest": int(_number(_attr(extend, "open_interest") or _attr(calc, "open_interest")) or 0),
            "volume": int(_number(_attr(quote, "volume") or _attr(calc, "volume")) or 0),
            "delta": _number(_attr(calc, "delta")),
            "gamma": _number(_attr(calc, "gamma")),
            "theta": _number(_attr(calc, "theta")),
            "vega": _number(_attr(calc, "vega")),
            "rho": _number(_attr(calc, "rho")),
            "quote_time": _timestamp(_attr(quote, "timestamp", "quote_time")),
            "depth_status": depth_status,
            "provider_status": "available",
            "source": "longbridge_option_quote",
            "read_only_research": True,
            "order_submission_enabled": False,
        }
        if db_path:
            persist_option_snapshot(db_path, payload)
        return payload
    except Exception as exc:  # pragma: no cover - provider/network dependent
        return {
            "contract_symbol": contract,
            "provider_status": "unavailable",
            "provider_errors": [f"{type(exc).__name__}: {str(exc)[:240]}"],
            "source": "longbridge_option_quote",
            "read_only_research": True,
            "order_submission_enabled": False,
        }


def persist_option_snapshot(db_path: Path, snapshot: dict[str, Any]) -> str:
    material = f"{snapshot['contract_symbol']}|{snapshot.get('quote_time')}|{snapshot.get('bid')}|{snapshot.get('ask')}"
    snapshot_id = f"option-snapshot-{hashlib.sha256(material.encode()).hexdigest()[:20]}"
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO option_contract_snapshots(
              snapshot_id, contract_symbol, underlying_symbol, expiry_date, strike_price,
              direction, is_standard, bid, ask, last, mid, spread_pct, implied_volatility,
              historical_volatility, open_interest, volume, delta, gamma, theta, vega, rho,
              quote_time, provider_status, source, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id, snapshot["contract_symbol"], snapshot.get("underlying_symbol") or "",
                snapshot.get("expiry_date") or "", snapshot.get("strike_price") or 0,
                snapshot.get("direction") or "", int(bool(snapshot.get("is_standard"))), snapshot.get("bid"),
                snapshot.get("ask"), snapshot.get("last"), snapshot.get("mid"), snapshot.get("spread_pct"),
                snapshot.get("implied_volatility"), snapshot.get("historical_volatility"),
                int(snapshot.get("open_interest") or 0), int(snapshot.get("volume") or 0), snapshot.get("delta"),
                snapshot.get("gamma"), snapshot.get("theta"), snapshot.get("vega"), snapshot.get("rho"),
                snapshot.get("quote_time"), snapshot.get("provider_status") or "unknown", snapshot.get("source") or "unknown",
                json.dumps(snapshot, ensure_ascii=True), _now(),
            ),
        )
        conn.commit()
    return snapshot_id


def screen_option_contract(
    snapshot: dict[str, Any],
    *,
    underlying_price: float,
    instruction_state: str,
    event_calendar_ready: bool,
    today: date | None = None,
) -> dict[str, Any]:
    current_date = today or datetime.now(UTC).date()
    try:
        dte = (date.fromisoformat(str(snapshot.get("expiry_date"))) - current_date).days
    except ValueError:
        dte = -1
    blockers: list[str] = []
    if snapshot.get("provider_status") != "available" or snapshot.get("depth_status") != "available":
        blockers.append("Fresh Longbridge option quote and valid BBO are required.")
    if not snapshot.get("is_standard"):
        blockers.append("Only standard 100-share contracts are supported.")
    if not MIN_DTE <= dte <= MAX_DTE:
        blockers.append(f"DTE must be between {MIN_DTE} and {MAX_DTE}.")
    delta = abs(_number(snapshot.get("delta")) or 0)
    if not MIN_DELTA <= delta <= MAX_DELTA:
        blockers.append(f"Absolute delta must be between {MIN_DELTA:.2f} and {MAX_DELTA:.2f}.")
    if (_number(snapshot.get("spread_pct")) or math.inf) > MAX_SPREAD_PCT:
        blockers.append(f"Bid/ask spread must be no more than {MAX_SPREAD_PCT:.1f}% of mid.")
    if int(snapshot.get("open_interest") or 0) < MIN_OPEN_INTEREST:
        blockers.append(f"Open interest must be at least {MIN_OPEN_INTEREST}.")
    if int(snapshot.get("volume") or 0) < MIN_VOLUME:
        blockers.append(f"Daily volume must be at least {MIN_VOLUME}.")
    if not event_calendar_ready:
        blockers.append("Earnings and corporate-event calendar is incomplete.")
    direction = str(snapshot.get("direction") or "")
    if direction == "CALL" and instruction_state != "TRIGGERED":
        blockers.append("Long Call expression requires a TRIGGERED underlying instruction.")
    if direction == "PUT":
        blockers.append("Long Put remains paper-research only until a bearish policy is validated.")
    ask = _number(snapshot.get("ask")) or 0
    strike = _number(snapshot.get("strike_price")) or 0
    multiplier = _number(snapshot.get("contract_multiplier")) or 100
    score = 100.0
    score -= min(35.0, (_number(snapshot.get("spread_pct")) or 35.0) * 3)
    score -= min(25.0, abs(delta - 0.525) * 100)
    score += min(10.0, math.log10(max(1, int(snapshot.get("open_interest") or 0))) * 2)
    return {
        "status": "eligible" if not blockers else ("paper_only" if direction == "PUT" and len(blockers) == 1 else "blocked"),
        "score": round(max(0.0, min(100.0, score)), 2),
        "dte": dte,
        "max_loss": round(ask * multiplier, 2),
        "breakeven": round(strike + ask if direction == "CALL" else strike - ask, 4),
        "underlying_price": underlying_price,
        "blockers": blockers,
        "filter_version": OPTION_EXPRESSION_VERSION,
        "read_only_research": True,
    }


def option_candidates(db_path: Path, symbol: str, *, event_calendar_ready: bool = False) -> dict[str, Any]:
    underlying = symbol.upper().split(".")[0]
    instructions = list_instructions(db_path, current_only=True, symbol=underlying, limit=1)["instructions"]
    instruction = instructions[0] if instructions else None
    quote = api_stock_quote(underlying, db_path)
    spot = _number(quote.get("last")) or 0
    if not instruction:
        return {"symbol": underlying, "candidates": [], "status": "blocked", "blockers": ["No current underlying instruction."], "read_only_research": True}
    expiry_payload = option_expiries(underlying)
    expiries = [item for item in expiry_payload.get("expiries", []) if _dte_in_range(item)]
    if not expiries:
        return {"symbol": underlying, "instruction": instruction, "candidates": [], "status": "blocked", "blockers": ["No 14-45 DTE expiry is available."], "read_only_research": True}
    chain = option_chain(underlying, expiries[0])
    rows = [row for row in chain.get("contracts", []) if row.get("is_standard") and row.get("strike_price") is not None]
    rows.sort(key=lambda row: abs(float(row["strike_price"]) - spot))
    contract_symbols = [row.get("call_symbol") for row in rows[:4] if row.get("call_symbol")]
    results = []
    for contract in contract_symbols:
        snapshot = option_contract_snapshot(str(contract), db_path)
        screen = screen_option_contract(
            snapshot,
            underlying_price=spot,
            instruction_state=instruction["state"],
            event_calendar_ready=event_calendar_ready,
        )
        candidate = _persist_option_candidate(db_path, instruction, snapshot, screen)
        results.append(candidate)
    results.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    return {
        "symbol": underlying,
        "instruction": instruction,
        "expiry_date": expiries[0],
        "candidates": results,
        "status": "available" if results else "blocked",
        "event_calendar_ready": event_calendar_ready,
        "read_only_research": True,
        "order_submission_enabled": False,
    }


def _dte_in_range(expiry: str) -> bool:
    try:
        dte = (date.fromisoformat(expiry) - datetime.now(UTC).date()).days
        return MIN_DTE <= dte <= MAX_DTE
    except ValueError:
        return False


def _persist_option_candidate(db_path: Path, instruction: dict[str, Any], snapshot: dict[str, Any], screen: dict[str, Any]) -> dict[str, Any]:
    material = f"{instruction['instruction_id']}|{snapshot.get('contract_symbol')}|{snapshot.get('quote_time')}"
    candidate_id = f"option-candidate-{hashlib.sha256(material.encode()).hexdigest()[:20]}"
    now = _now()
    rationale = {"screen": screen, "underlying_plan": instruction["plan"], "underlying_evidence": instruction["evidence"]}
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO option_expression_candidates(
              candidate_id, instruction_id, contract_symbol, underlying_symbol,
              expression_type, status, score, max_loss, breakeven, rationale_json,
              snapshot_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (candidate_id, instruction["instruction_id"], snapshot.get("contract_symbol") or "",
             instruction["symbol"], "LONG_CALL", screen["status"], screen["score"], screen["max_loss"],
             screen["breakeven"], json.dumps(rationale, ensure_ascii=True), json.dumps(snapshot, ensure_ascii=True), now, now),
        )
        conn.commit()
    return {"candidate_id": candidate_id, "instruction_id": instruction["instruction_id"], **snapshot, **screen}


def record_option_paper_observation(db_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action") or "open").lower()
    if action == "open":
        candidate_id = str(payload.get("candidate_id") or "")
        with connect(db_path) as conn:
            row = conn.execute("SELECT * FROM option_expression_candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
            existing = conn.execute(
                "SELECT observation_id FROM option_paper_observations WHERE candidate_id = ? AND status = 'open'",
                (candidate_id,),
            ).fetchone()
        if not row:
            raise ValueError("Unknown option expression candidate.")
        if existing:
            raise ValueError("This option candidate already has an open Paper Observation.")
        candidate = dict(row)
        if candidate["status"] not in {"eligible", "paper_only"}:
            raise ValueError("Blocked option candidate cannot enter Paper Observation.")
        snapshot = json.loads(candidate["snapshot_json"])
        entry_price = _number(snapshot.get("ask"))
        underlying_price = _number(payload.get("underlying_price"))
        if entry_price is None or entry_price <= 0 or underlying_price is None or underlying_price <= 0:
            raise ValueError("A valid ask and underlying price are required for Paper Observation.")
        observation_id = f"option-paper-{uuid.uuid4().hex[:20]}"
        now = _now()
        multiplier = _number(snapshot.get("contract_multiplier")) or 100
        with connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO option_paper_observations(
                  observation_id, candidate_id, contract_symbol, underlying_symbol, contracts,
                  entry_time, entry_price, entry_underlying_price, max_loss, status,
                  exit_time, exit_price, exit_underlying_price, realized_pnl,
                  realized_return_pct, exit_reason, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, 'open', NULL, NULL, NULL, NULL, NULL, NULL, ?, ?, ?)
                """,
                (observation_id, candidate_id, candidate["contract_symbol"], candidate["underlying_symbol"],
                 now, entry_price, underlying_price, entry_price * multiplier, str(payload.get("notes") or "")[:4000], now, now),
            )
            conn.commit()
        return option_paper_observation(db_path, observation_id)
    if action == "close":
        observation_id = str(payload.get("observation_id") or "")
        exit_price = _number(payload.get("exit_price"))
        exit_underlying = _number(payload.get("underlying_price"))
        if exit_price is None or exit_price < 0 or exit_underlying is None or exit_underlying <= 0:
            raise ValueError("Valid option and underlying exit prices are required.")
        with connect(db_path) as conn:
            row = conn.execute("SELECT * FROM option_paper_observations WHERE observation_id = ? AND status = 'open'", (observation_id,)).fetchone()
            if not row:
                raise ValueError("Unknown or closed option Paper Observation.")
            pnl = (exit_price - float(row["entry_price"])) * 100
            return_pct = pnl / float(row["max_loss"]) * 100 if row["max_loss"] else 0
            now = _now()
            conn.execute(
                """
                UPDATE option_paper_observations
                SET status='closed', exit_time=?, exit_price=?, exit_underlying_price=?,
                    realized_pnl=?, realized_return_pct=?, exit_reason=?, notes=?, updated_at=?
                WHERE observation_id=?
                """,
                (now, exit_price, exit_underlying, pnl, return_pct, str(payload.get("exit_reason") or "manual_review")[:120],
                 str(payload.get("notes") or row["notes"])[:4000], now, observation_id),
            )
            conn.commit()
        return option_paper_observation(db_path, observation_id)
    raise ValueError("action must be open or close.")


def option_paper_observation(db_path: Path, observation_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM option_paper_observations WHERE observation_id = ?", (observation_id,)).fetchone()
    if not row:
        raise ValueError("Unknown option Paper Observation.")
    return {**dict(row), "simulated_only": True, "one_contract_only": True, "no_broker_or_order_api": True}


def list_option_paper_observations(db_path: Path, *, status: str = "", limit: int = 100) -> dict[str, Any]:
    where = "WHERE status = ?" if status in {"open", "closed"} else ""
    values: tuple[Any, ...] = (status, max(1, min(int(limit), 500))) if where else (max(1, min(int(limit), 500)),)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM option_paper_observations {where} ORDER BY updated_at DESC LIMIT ?",
            values,
        ).fetchall()
    return {
        "observations": [{**dict(row), "simulated_only": True, "one_contract_only": True} for row in rows],
        "count": len(rows),
        "read_only_research": True,
        "order_submission_enabled": False,
    }
