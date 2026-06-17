from __future__ import annotations

import json
import math
import re
import ssl
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from btc_eth_15m.options_pilot_journal import journal_summary_for_alerts, load_pilot_journal


DEFAULT_OPTION_SYMBOLS = [
    "SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META",
    "GOOGL", "AMD", "AVGO", "NFLX", "COST", "JPM", "BAC", "WFC", "GS", "MS",
    "XOM", "CVX", "COP", "UNH", "LLY", "MRK", "JNJ", "ABBV", "HD", "WMT",
    "MCD", "NKE", "BA", "CAT", "GE", "DIS", "T", "V", "MA", "CRM",
    "ORCL", "ADBE", "INTC", "MU", "QCOM", "SMCI", "PLTR", "COIN", "SHOP", "UBER",
]
AI_OPTION_SYMBOLS = [
    "NVDA", "AMD", "AVGO", "MSFT", "GOOGL", "META", "AMZN", "ORCL", "CRM", "ADBE",
    "PLTR", "SMCI", "MU", "QCOM", "INTC", "ARM", "MRVL", "TSM", "ASML", "ANET",
    "DELL", "NOW", "SNOW", "DDOG", "MDB", "CRWD", "PANW", "NET", "AI", "PATH",
]
ALL_OPTION_SYMBOLS = list(dict.fromkeys([*DEFAULT_OPTION_SYMBOLS, *AI_OPTION_SYMBOLS]))
ETF_SYMBOLS = {"SPY", "QQQ", "IWM", "DIA"}
OPTION_UNIVERSES = {
    "default": DEFAULT_OPTION_SYMBOLS,
    "ai": AI_OPTION_SYMBOLS,
    "all": ALL_OPTION_SYMBOLS,
}
FREQUENCY_PROFILE = {
    "label": "15m signal / 1h confirmation / same-day review",
    "signal_interval": "15m",
    "confirmation_interval": "1h",
    "holding_style": "intraday_research",
    "execution": "read_only_no_orders",
}
LLM_POLICY = {
    "llm_signal_core_enabled": False,
    "external_llm_calls_enabled": False,
    "core_signal_engine": "strict_rules_plus_black_scholes_surface_v1",
    "review_assistant_status": "planned_read_only_after_live_pilot",
    "user_facing_label": "LLM Core Locked",
    "blocked_uses": [
        "alert_score",
        "alert_level",
        "scan_trigger",
        "broker_order",
        "paper_order",
        "testnet_order",
        "live_order",
    ],
    "allowed_future_uses": [
        "read_only_signal_explanation",
        "risk_question_generation",
        "manual_checklist_summary",
        "after_hours_journal_summary",
    ],
}
PILOT_STATE_FILE = "options-live-pilot-state.json"
PILOT_SCAN_COOLDOWN_SECONDS = 15 * 60
PRICE_HISTORY_RANGES = {"1d", "5d", "1mo", "3mo", "1y"}
PRICE_HISTORY_INTERVALS = {"5m", "15m", "1d"}
RECOMMEND_TRADE = "TRADE CANDIDATE"
RECOMMEND_OBSERVE = "OBSERVE"
RECOMMEND_NO_TRADE = "NO TRADE"
ATM_ALERT = "ATM ALERT"
ATM_WATCH = "WATCH"
ATM_PASS = "PASS"
ATM_SIGNAL_PROFILES = {
    "strict": {
        "profile_id": "strict_local_v1",
        "label": "Strict local ATM manual alerts / 15m signal / 1h confirmation",
        "strategy_id": "atm-manual-options-strict-local-v1",
        "atm_moneyness_pct": 1.0,
        "delta_band": [0.40, 0.60],
        "dte_window": [2, 21],
        "alert_score_threshold": 82.0,
        "watch_score_threshold": 65.0,
        "watch_moneyness_pct": 2.0,
        "max_alert_spread_pct": 8.0,
        "min_alert_volume": 500,
        "min_alert_open_interest": 1000,
        "default_alert_channel": "dashboard_alert_inbox",
        "execution": "read_only_manual_trade_research",
    },
    "balanced": {
        "profile_id": "balanced_v1",
        "label": "Balanced ATM manual alerts / 15m signal / 1h confirmation",
        "strategy_id": "atm-manual-options-v1",
        "atm_moneyness_pct": 1.0,
        "delta_band": [0.40, 0.60],
        "dte_window": [2, 21],
        "alert_score_threshold": 78.0,
        "watch_score_threshold": 58.0,
        "watch_moneyness_pct": 2.0,
        "max_alert_spread_pct": 12.0,
        "min_alert_volume": 100,
        "min_alert_open_interest": 300,
        "default_alert_channel": "dashboard_alert_inbox",
        "execution": "read_only_manual_trade_research",
    },
}
ATM_SIGNAL_PROFILE = ATM_SIGNAL_PROFILES["strict"]


def _atm_signal_profile(profile: str | None = None) -> dict[str, Any]:
    key = str(profile or "strict").strip().lower()
    aliases = {
        "": "strict",
        "strict_local_v1": "strict",
        "strict-local-v1": "strict",
        "local": "strict",
        "balanced_v1": "balanced",
        "legacy": "balanced",
    }
    return ATM_SIGNAL_PROFILES.get(aliases.get(key, key), ATM_SIGNAL_PROFILES["strict"])


def _llm_policy_payload() -> dict[str, Any]:
    payload = dict(LLM_POLICY)
    payload["blocked_uses"] = list(LLM_POLICY["blocked_uses"])
    payload["allowed_future_uses"] = list(LLM_POLICY["allowed_future_uses"])
    return payload


@dataclass(frozen=True)
class OptionContract:
    option_symbol: str
    underlying: str
    expiration: str
    dte: int
    strike: float
    option_type: str
    bid: float
    ask: float
    volume: int
    open_interest: int
    implied_volatility: float
    delta: float
    gamma: float
    theta: float
    vega: float
    event_risk: str

    @property
    def mid(self) -> float:
        return round((self.bid + self.ask) / 2, 2)

    @property
    def spread(self) -> float:
        return round(max(self.ask - self.bid, 0.0), 2)

    @property
    def spread_pct(self) -> float:
        mid = self.mid
        return round((self.spread / mid) * 100, 2) if mid else 999.0

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mid"] = self.mid
        payload["spread"] = self.spread
        payload["spread_pct"] = self.spread_pct
        return payload


@dataclass(frozen=True)
class UnderlyingSnapshot:
    symbol: str
    name: str
    price: float
    change_pct: float
    iv_rank: float
    trend: str
    data_source: str
    updated_at: str
    momentum_score: float = 0.0
    relative_volume: float = 1.0
    scan_rank: int = 0
    theme_tags: tuple[str, ...] = ()
    universe_groups: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def options_underlyings(
    symbols: list[str] | None = None,
    *,
    source: str = "live",
    universe: str = "default",
    timeout: float = 8.0,
) -> dict[str, Any]:
    selected = _selected_symbols(symbols, universe=universe)
    universe_name = _normalize_universe(universe)
    generated_at = datetime.now(timezone.utc).isoformat()
    if source == "fixture":
        snapshots = _underlying_fixtures()
        filtered = [snapshots[symbol] for symbol in selected if symbol in snapshots]
        return {
            "generated_at": generated_at,
            "source_type": "fixture_read_only",
            "universe": universe_name,
            "universes": _universe_payload(),
            "frequency_profile": FREQUENCY_PROFILE,
            "symbols": [item.symbol for item in filtered],
            "underlyings": [item.to_payload() for item in filtered],
            "limitations": _limitations("fixture"),
        }

    snapshots, errors = _live_underlying_snapshots(selected, timeout=timeout)
    underlyings = _rank_underlyings(list(snapshots.values()))
    source_type = "public_live_us_equities" if underlyings else "live_read_only_unavailable"
    return {
        "generated_at": generated_at,
        "source_type": source_type,
        "universe": universe_name,
        "universes": _universe_payload(),
        "frequency_profile": FREQUENCY_PROFILE,
        "requested_symbols": selected,
        "symbols": [item.symbol for item in underlyings],
        "underlyings": [item.to_payload() for item in underlyings],
        "provider_errors": errors,
        "live_data_health": _live_data_health(
            requested_symbols=selected,
            successful_symbols=[item.symbol for item in underlyings],
            provider_errors=errors,
            source_type=source_type,
        ),
        "limitations": _limitations("live"),
    }


def options_daily_candidates(
    symbols: list[str] | None = None,
    *,
    source: str = "live",
    universe: str = "default",
    timeout: float = 8.0,
) -> dict[str, Any]:
    selected = _selected_symbols(symbols, universe=universe)
    universe_name = _normalize_universe(universe)
    scan_time = datetime.now(timezone.utc).isoformat()
    if source == "fixture":
        ranked = _rank_underlyings([item for item in _underlying_fixtures().values() if item.symbol in selected])
        return {
            "generated_at": scan_time,
            "source_type": "fixture_read_only",
            "universe": universe_name,
            "universes": _universe_payload(),
            "frequency_profile": FREQUENCY_PROFILE,
            "requested_symbols": selected,
            "symbols": [item.symbol for item in ranked],
            "candidates": _daily_candidate_records(ranked, [], scan_time, "fixture_read_only"),
            "provider_errors": [],
            "limitations": _limitations("fixture"),
            "safety": _safety_payload(),
        }

    snapshots, errors = _live_underlying_snapshots(selected, timeout=timeout)
    ranked = _rank_underlyings(list(snapshots.values()))
    source_type = "public_live_us_equities" if ranked else "live_read_only_unavailable"
    return {
        "generated_at": scan_time,
        "source_type": source_type,
        "universe": universe_name,
        "universes": _universe_payload(),
        "frequency_profile": FREQUENCY_PROFILE,
        "requested_symbols": selected,
        "symbols": [item.symbol for item in ranked],
        "candidates": _daily_candidate_records(ranked, errors, scan_time, source_type),
        "provider_errors": errors,
        "live_data_health": _live_data_health(
            requested_symbols=selected,
            successful_symbols=[item.symbol for item in ranked],
            provider_errors=errors,
            source_type=source_type,
        ),
        "limitations": _limitations("live"),
        "safety": _safety_payload(),
    }


def options_chain(
    symbol: str = "SPY",
    *,
    source: str = "live",
    timeout: float = 8.0,
    expiration: str | None = None,
) -> dict[str, Any]:
    normalized = _normalize_symbol(symbol)
    scan_time = datetime.now(timezone.utc).isoformat()
    if source == "fixture":
        snapshots = _underlying_fixtures()
        if normalized not in snapshots:
            raise ValueError(f"Unsupported options fixture symbol: {normalized}")
        contracts = _filter_contracts_by_expiration(_contract_fixtures()[normalized], expiration)
        data_quality = "fixture"
        return {
            "generated_at": scan_time,
            "source_type": "fixture_read_only",
            "underlying": snapshots[normalized].to_payload(),
            "selected_expiration": expiration,
            "data_quality": data_quality,
            "contracts": [_contract_payload(contract, snapshots[normalized], data_quality=data_quality) for contract in contracts],
            "expiration_groups": _expiration_groups(contracts),
            "chain_rows": _broker_chain_rows(contracts, snapshots[normalized], data_quality=data_quality),
            "limitations": _limitations("fixture"),
            "safety": _safety_payload(),
        }

    snapshots, errors = _live_underlying_snapshots([normalized], timeout=timeout)
    underlying = snapshots.get(normalized)
    contracts: list[OptionContract] = []
    if underlying:
        try:
            contracts = _fetch_live_chain(normalized, underlying, timeout=timeout)
        except Exception as exc:
            errors.append({"symbol": normalized, "provider": "nasdaq_option_chain", "error": str(exc)})

    data_quality = _data_quality_for_symbol(normalized, underlying, errors, bool(contracts))
    contracts = _filter_contracts_by_expiration(contracts, expiration)
    contracts.sort(key=lambda item: (item.dte, abs(item.strike - (underlying.price if underlying else item.strike)), item.option_type))
    source_type = "public_live_us_options" if contracts else "public_live_us_options_partial"
    return {
        "generated_at": scan_time,
        "source_type": source_type,
        "underlying": underlying.to_payload() if underlying else _empty_underlying(normalized).to_payload(),
        "selected_expiration": expiration,
        "data_quality": data_quality,
        "quote_updated_at": underlying.updated_at if underlying else None,
        "suggested_observation_window": _suggested_observation_window(data_quality, errors),
        "contracts": [_contract_payload(contract, underlying or _empty_underlying(normalized), data_quality=data_quality) for contract in contracts],
        "expiration_groups": _expiration_groups(contracts),
        "chain_rows": _broker_chain_rows(contracts, underlying or _empty_underlying(normalized), data_quality=data_quality),
        "provider_errors": errors,
        "live_data_health": _live_data_health(
            requested_symbols=[normalized],
            successful_symbols=[normalized] if underlying else [],
            provider_errors=errors,
            source_type=source_type,
            chain_symbols=[normalized],
            successful_chain_symbols=[normalized] if contracts else [],
        ),
        "limitations": _limitations("live"),
        "safety": _safety_payload(),
    }


def options_contract(
    option_symbol: str,
    *,
    source: str = "live",
    timeout: float = 8.0,
) -> dict[str, Any]:
    parsed = _parse_option_symbol(option_symbol)
    if parsed is None:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_type": "invalid_option_symbol",
            "option_symbol": option_symbol,
            "contract": None,
            "score": None,
            "error": "Unsupported option symbol format.",
            "safety": _safety_payload(),
        }
    chain = options_chain(parsed["underlying"], source=source, timeout=timeout, expiration=parsed["expiration"])
    contract = next((item for item in chain.get("contracts", []) if item.get("option_symbol") == option_symbol), None)
    if contract is None:
        return {
            "generated_at": chain.get("generated_at"),
            "source_type": chain.get("source_type"),
            "option_symbol": option_symbol,
            "underlying": chain.get("underlying"),
            "contract": None,
            "score": None,
            "error": "Contract was not found in the current option chain.",
            "provider_errors": chain.get("provider_errors", []),
            "safety": _safety_payload(),
        }
    underlying_payload = chain.get("underlying") or {}
    underlying = UnderlyingSnapshot(
        symbol=str(underlying_payload.get("symbol") or parsed["underlying"]),
        name=str(underlying_payload.get("name") or parsed["underlying"]),
        price=float(underlying_payload.get("price") or 0.0),
        change_pct=float(underlying_payload.get("change_pct") or 0.0),
        iv_rank=float(underlying_payload.get("iv_rank") or 0.0),
        trend=str(underlying_payload.get("trend") or "neutral"),
        data_source=str(underlying_payload.get("data_source") or chain.get("source_type") or "-"),
        updated_at=str(underlying_payload.get("updated_at") or chain.get("generated_at") or ""),
        momentum_score=float(underlying_payload.get("momentum_score") or 0.0),
        relative_volume=float(underlying_payload.get("relative_volume") or 1.0),
        scan_rank=int(underlying_payload.get("scan_rank") or 0),
        theme_tags=tuple(underlying_payload.get("theme_tags") or _theme_tags(parsed["underlying"])),
        universe_groups=tuple(underlying_payload.get("universe_groups") or _universe_groups(parsed["underlying"])),
    )
    raw_contract = _contract_from_payload(contract)
    score = score_contract(raw_contract, underlying)
    return {
        "generated_at": chain.get("generated_at"),
        "source_type": chain.get("source_type"),
        "option_symbol": option_symbol,
        "underlying": underlying.to_payload(),
        "contract": contract,
        "score": score,
        "agent_reason": score.get("agent_note"),
        "blockers": score.get("blockers", []),
        "provider_errors": chain.get("provider_errors", []),
        "safety": _safety_payload(),
    }


def options_model_surface(
    option_symbol: str,
    *,
    source: str = "live",
    timeout: float = 8.0,
    price_steps: int = 9,
    iv_steps: int = 7,
) -> dict[str, Any]:
    contract_payload = options_contract(option_symbol, source=source, timeout=timeout)
    if not contract_payload.get("contract"):
        return {
            "generated_at": contract_payload.get("generated_at") or datetime.now(timezone.utc).isoformat(),
            "source_type": contract_payload.get("source_type") or "unavailable",
            "option_symbol": option_symbol,
            "model": None,
            "error": contract_payload.get("error") or "Contract unavailable for model surface.",
            "provider_errors": contract_payload.get("provider_errors", []),
            "safety": _safety_payload(),
        }

    contract = contract_payload["contract"]
    underlying = contract_payload.get("underlying") or {}
    model = _build_model_surface(
        contract=contract,
        underlying=underlying,
        price_steps=price_steps,
        iv_steps=iv_steps,
    )
    score = contract_payload.get("score") or {}
    model["decision_lens"] = _build_model_decision_lens(
        model=model,
        contract=_contract_from_payload(contract),
        underlying=underlying,
        score=score,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_type": contract_payload.get("source_type") or source,
        "option_symbol": option_symbol,
        "underlying": underlying,
        "contract": contract,
        "score": score,
        "model": model,
        "provider_errors": contract_payload.get("provider_errors", []),
        "limitations": [
            "Surface uses local Black-Scholes assumptions and public option-chain inputs.",
            "PnL assumes a long single-contract premium reference and excludes commissions, slippage, exercise, assignment, and early exercise.",
            "The decision lens is a read-only research filter; it is not an order instruction.",
        ],
        "safety": _safety_payload(),
    }


def options_price_history(
    *,
    instrument: str = "underlying",
    symbol: str | None = None,
    option_symbol: str | None = None,
    range_value: str = "5d",
    interval: str = "15m",
    source: str = "live",
    timeout: float = 8.0,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    normalized_instrument = "option" if str(instrument).lower() == "option" else "underlying"
    normalized_range = range_value if range_value in PRICE_HISTORY_RANGES else "5d"
    normalized_interval = interval if interval in PRICE_HISTORY_INTERVALS else "15m"
    provider_errors: list[dict[str, Any]] = []

    if normalized_instrument == "option":
        parsed = _parse_option_symbol(option_symbol or "")
        normalized_symbol = parsed["underlying"] if parsed else _normalize_symbol(symbol or "")
        normalized_option_symbol = str(option_symbol or "").upper().strip()
        instrument_symbol = normalized_option_symbol
    else:
        normalized_symbol = _normalize_symbol(symbol or (option_symbol or "SPY"))
        normalized_option_symbol = None
        instrument_symbol = normalized_symbol

    if not instrument_symbol:
        provider_errors.append({"symbol": "-", "provider": "price_history", "error": "Missing symbol."})
        return _price_history_payload(
            generated_at=generated_at,
            source_type="price_history_unavailable",
            instrument_type=normalized_instrument,
            symbol=normalized_symbol,
            option_symbol=normalized_option_symbol,
            range_value=normalized_range,
            interval=normalized_interval,
            candles=[],
            provider_errors=provider_errors,
        )

    if source == "fixture":
        if normalized_instrument == "option":
            candles = _fixture_option_candles(
                normalized_option_symbol or "",
                range_value=normalized_range,
                interval=normalized_interval,
            )
        else:
            candles = _fixture_underlying_candles(
                normalized_symbol,
                range_value=normalized_range,
                interval=normalized_interval,
            )
        return _price_history_payload(
            generated_at=generated_at,
            source_type="fixture_read_only",
            instrument_type=normalized_instrument,
            symbol=normalized_symbol,
            option_symbol=normalized_option_symbol,
            range_value=normalized_range,
            interval=normalized_interval,
            candles=candles,
            provider_errors=[],
        )

    yahoo_symbol = normalized_option_symbol if normalized_instrument == "option" else normalized_symbol
    try:
        candles = _fetch_yahoo_price_history(
            yahoo_symbol or "",
            range_value=normalized_range,
            interval=normalized_interval,
            timeout=timeout,
        )
    except Exception as exc:
        provider_errors.append({"symbol": yahoo_symbol or "-", "provider": "yahoo_chart", "error": str(exc)})
        candles = []

    if normalized_instrument == "option" and not candles and not provider_errors:
        provider_errors.append(
            {
                "symbol": normalized_option_symbol or "-",
                "provider": "yahoo_chart",
                "error": "No traded option candles from public provider.",
            }
        )
    source_type = (
        "public_live_us_option_history"
        if normalized_instrument == "option" and candles
        else "public_live_us_option_history_empty"
        if normalized_instrument == "option"
        else "public_live_us_equity_history"
        if candles
        else "public_live_us_equity_history_unavailable"
    )
    return _price_history_payload(
        generated_at=generated_at,
        source_type=source_type,
        instrument_type=normalized_instrument,
        symbol=normalized_symbol,
        option_symbol=normalized_option_symbol,
        range_value=normalized_range,
        interval=normalized_interval,
        candles=candles,
        provider_errors=provider_errors,
        live_data_health=_live_data_health(
            requested_symbols=[instrument_symbol],
            successful_symbols=[instrument_symbol] if candles else [],
            provider_errors=provider_errors,
            source_type=source_type,
        ),
    )


def options_worthiness_report(
    *,
    symbols: list[str] | None = None,
    outputs_dir: str | Path = "outputs",
    source: str = "live",
    universe: str = "default",
    timeout: float = 8.0,
    max_chain_symbols: int = 4,
) -> dict[str, Any]:
    selected = _selected_symbols(symbols, universe=universe)
    universe_name = _normalize_universe(universe)
    if source == "fixture":
        payload = _fixture_worthiness_report(selected, universe=universe_name)
        paths = write_options_worthiness_report(payload, outputs_dir)
        payload.update(paths)
        return payload

    snapshots, errors = _live_underlying_snapshots(selected, timeout=timeout)
    ranked = _rank_underlyings(list(snapshots.values()))
    chains: dict[str, list[OptionContract]] = {}
    chain_candidates = ranked[: max(int(max_chain_symbols), 1)]
    for snapshot in chain_candidates:
        try:
            chains[snapshot.symbol] = _fetch_live_chain(snapshot.symbol, snapshot, timeout=timeout)
        except Exception as exc:
            chains[snapshot.symbol] = []
            errors.append({"symbol": snapshot.symbol, "provider": "nasdaq_option_chain", "error": str(exc)})

    evaluations = _build_evaluations(ranked, chains)
    source_type = "public_live_us_options" if any(chains.values()) else "public_live_us_options_partial"
    if not ranked:
        source_type = "live_read_only_unavailable"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_type": source_type,
        "module": "US Options Live Scanner v1",
        "universe": universe_name,
        "universes": _universe_payload(),
        "frequency_profile": FREQUENCY_PROFILE,
        "symbols": selected,
        "daily_candidates": _daily_candidate_records(ranked, errors, datetime.now(timezone.utc).isoformat(), source_type),
        "scanner": {
            "underlying_provider": "yahoo_chart_public",
            "options_provider": "nasdaq_option_chain_public",
            "default_symbols": DEFAULT_OPTION_SYMBOLS,
            "ai_symbols": AI_OPTION_SYMBOLS,
            "option_chain_symbols": [item.symbol for item in chain_candidates],
            "ranking": "absolute intraday/5d change, relative volume, and direction strength",
        },
        "overall_recommendation": _overall_recommendation(evaluations),
        "evaluations": evaluations,
        "provider_errors": errors,
        "live_data_health": _live_data_health(
            requested_symbols=selected,
            successful_symbols=[item.symbol for item in ranked],
            provider_errors=errors,
            source_type=source_type,
            chain_symbols=[item.symbol for item in chain_candidates],
            successful_chain_symbols=[symbol for symbol, contracts in chains.items() if contracts],
        ),
        "limitations": _limitations("live"),
        "safety": _safety_payload(),
    }
    paths = write_options_worthiness_report(payload, outputs_dir)
    payload.update(paths)
    return payload


def options_atm_alerts(
    *,
    symbols: list[str] | None = None,
    outputs_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    source: str = "live",
    universe: str = "default",
    profile: str = "strict",
    timeout: float = 8.0,
    max_chain_symbols: int = 12,
) -> dict[str, Any]:
    selected = _selected_symbols(symbols, universe=universe)
    universe_name = _normalize_universe(universe)
    generated_at = datetime.now(timezone.utc).isoformat()
    signal_profile = _atm_signal_profile(profile)

    if source == "fixture":
        snapshots = _underlying_fixtures()
        ranked = _rank_underlyings([snapshots[symbol] for symbol in selected if symbol in snapshots])
        chains = {symbol: _contract_fixtures()[symbol] for symbol in selected if symbol in snapshots}
        payload = _build_atm_alerts_payload(
            generated_at=generated_at,
            source_type="fixture_read_only",
            universe=universe_name,
            selected=selected,
            ranked=ranked,
            chains=chains,
            provider_errors=[],
            live_data_health=None,
            signal_profile=signal_profile,
        )
        _attach_live_pilot_review(payload, outputs_dir, db_path=db_path)
        payload["live_pilot_status"] = options_live_pilot_status(outputs_dir=outputs_dir, db_path=db_path, latest_payload=payload)
        paths = write_options_atm_alerts_report(payload, outputs_dir)
        payload.update(paths)
        return payload

    cooldown = _live_pilot_scan_cooldown(outputs_dir, universe_name)
    if cooldown.get("active"):
        cached = options_atm_alerts_latest(outputs_dir=outputs_dir, db_path=db_path, universe=universe_name, profile=profile)
        if cached.get("source_type") != "atm_alerts_snapshot_missing" and cached.get("universe") == universe_name:
            cached["scan_cooldown_active"] = True
            cached["scan_cooldown"] = cooldown
            warnings = list(cached.get("provider_errors") or [])
            warnings.insert(
                0,
                {
                    "symbol": "OPTIONS",
                    "provider": "live_pilot_cooldown",
                    "error": f"Live scan cooldown active for {cooldown.get('remaining_seconds')} seconds; returned cache-only live pilot snapshot.",
                },
            )
            cached["provider_errors"] = warnings
            cached["live_pilot_status"] = options_live_pilot_status(outputs_dir=outputs_dir, db_path=db_path, latest_payload=cached)
            return cached

    snapshots, errors = _live_underlying_snapshots(selected, timeout=timeout)
    ranked = _rank_underlyings(list(snapshots.values()))
    chains: dict[str, list[OptionContract]] = {}
    chain_candidates = ranked[: max(int(max_chain_symbols), 1)]
    for snapshot in chain_candidates:
        try:
            chains[snapshot.symbol] = _fetch_live_chain(snapshot.symbol, snapshot, timeout=timeout)
        except Exception as exc:
            chains[snapshot.symbol] = []
            errors.append({"symbol": snapshot.symbol, "provider": "nasdaq_option_chain", "error": str(exc)})

    source_type = "public_live_us_options_atm_alerts" if any(chains.values()) else "public_live_us_options_atm_alerts_partial"
    if not ranked:
        source_type = "live_read_only_unavailable"
    live_data_health = _live_data_health(
        requested_symbols=selected,
        successful_symbols=[item.symbol for item in ranked],
        provider_errors=errors,
        source_type=source_type,
        chain_symbols=[item.symbol for item in chain_candidates],
        successful_chain_symbols=[symbol for symbol, contracts in chains.items() if contracts],
    )
    payload = _build_atm_alerts_payload(
        generated_at=generated_at,
        source_type=source_type,
        universe=universe_name,
        selected=selected,
        ranked=ranked,
        chains=chains,
        provider_errors=errors,
        live_data_health=live_data_health,
        signal_profile=signal_profile,
    )
    _attach_live_pilot_review(payload, outputs_dir, db_path=db_path)
    _record_live_pilot_scan(payload, outputs_dir)
    payload["live_pilot_status"] = options_live_pilot_status(outputs_dir=outputs_dir, db_path=db_path, latest_payload=payload)
    paths = write_options_atm_alerts_report(payload, outputs_dir)
    payload.update(paths)
    return payload


def options_atm_alerts_latest(
    *,
    outputs_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    universe: str = "default",
    profile: str = "strict",
) -> dict[str, Any]:
    signal_profile = _atm_signal_profile(profile)
    path = Path(outputs_dir) / "options-atm-alerts-report.json"
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict) and payload and "fixture" not in str(payload.get("source_type") or ""):
            payload = dict(payload)
            payload["snapshot_read_mode"] = "cache_only"
            payload.setdefault("universe", universe)
            payload.setdefault("profile_id", signal_profile["profile_id"])
            payload.setdefault("atm_signal_profile", signal_profile)
            payload.setdefault("llm_policy", _llm_policy_payload())
            payload.setdefault("safety", _safety_payload())
            if isinstance(payload.get("safety"), dict):
                payload["safety"].setdefault("llm_signal_core_enabled", False)
                payload["safety"].setdefault("external_llm_calls_enabled", False)
            _attach_live_pilot_review(payload, outputs_dir, db_path=db_path)
            payload.setdefault("live_pilot_status", options_live_pilot_status(outputs_dir=outputs_dir, db_path=db_path, latest_payload=payload))
            return payload

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "run_id": f"atm-cache-missing-{signal_profile['profile_id']}-{now.replace(':', '').replace('-', '')}",
        "generated_at": now,
        "source_type": "atm_alerts_snapshot_missing",
        "snapshot_read_mode": "cache_only",
        "module": "ATM Options Manual Signal Assistant v1",
        "strategy_id": signal_profile["strategy_id"],
        "profile": signal_profile["profile_id"],
        "profile_id": signal_profile["profile_id"],
        "universe": universe,
        "universes": _universe_payload(),
        "symbols": _selected_symbols(None, universe=universe),
        "scanned_symbol_count": 0,
        "frequency_profile": FREQUENCY_PROFILE,
        "llm_policy": _llm_policy_payload(),
        "atm_signal_profile": signal_profile,
        "daily_candidates": [],
        "atm_alerts": [],
        "alert_summary": _atm_alert_summary([], signal_profile),
        "overall_alert_level": ATM_PASS,
        "provider_errors": [
            {
                "symbol": "OPTIONS",
                "provider": "atm_alerts_cache",
                "error": "No live ATM alert snapshot is available. Click Run ATM Alert Scan to refresh public data.",
            }
        ],
        "live_data_health": {
            "requested_symbol_count": len(_selected_symbols(None, universe=universe)),
            "successful_symbol_count": 0,
            "failed_symbol_count": 0,
            "failed_symbols": [],
            "provider_degraded": True,
            "provider_error_count": 1,
            "provider_errors": [
                {
                    "symbol": "OPTIONS",
                    "provider": "atm_alerts_cache",
                    "error": "No cache-only live pilot report is available.",
                }
            ],
            "source_type": "atm_alerts_snapshot_missing",
        },
        "manual_research_flow": [
            "Click Run ATM Alert Scan to refresh public live data.",
            "Review only after stock K-Line, option K-Line, liquidity, and 3D Lens checks.",
        ],
        "limitations": ["Cache-only live pilot has no report yet."],
        "safety": _safety_payload(),
    }
    _attach_live_pilot_review(payload, outputs_dir, db_path=db_path)
    payload["live_pilot_status"] = options_live_pilot_status(outputs_dir=outputs_dir, db_path=db_path, latest_payload=payload)
    return payload


def options_live_pilot_status(
    *,
    outputs_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    latest_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    market_date = _current_market_date()
    state = _read_live_pilot_state(outputs_dir)
    latest = latest_payload if isinstance(latest_payload, dict) else _read_latest_atm_report(outputs_dir)
    journal = load_pilot_journal(outputs_dir, db_path=db_path)
    entries = journal.get("entries") or []
    today_entries = [item for item in entries if item.get("market_date") == market_date]
    state_dates = sorted((state.get("market_dates") or {}).keys())
    pilot_day = min(max(len([item for item in state_dates if item <= market_date]) or 1, 1), 3)
    provider_errors = list((latest or {}).get("provider_errors") or [])
    pilot_review = (latest or {}).get("live_pilot_review") if isinstance((latest or {}).get("live_pilot_review"), dict) else {}
    latest_health = (latest or {}).get("live_data_health") if isinstance((latest or {}).get("live_data_health"), dict) else {}
    data_caution = bool(
        pilot_review.get("data_caution")
        or provider_errors
        or latest_health.get("provider_degraded")
        or not latest
    )
    return {
        "generated_at": now,
        "phase": "3_trading_day_live_observation",
        "market_date": market_date,
        "pilot_day": pilot_day,
        "planned_trading_days": 3,
        "default_scan_status": _pilot_universe_status(state, market_date, "default"),
        "ai_scan_status": _pilot_universe_status(state, market_date, "ai"),
        "provider_error_count": len(provider_errors),
        "provider_429_count": _provider_429_count(provider_errors),
        "journal_total_count": len(today_entries),
        "journal_reviewed_count": sum(1 for item in today_entries if item.get("status") == "reviewed"),
        "journal_skipped_count": sum(1 for item in today_entries if item.get("status") == "skipped"),
        "journal_paper_observed_count": sum(1 for item in today_entries if item.get("status") == "paper-observed"),
        "journal_stock_kline_checked_count": sum(1 for item in today_entries if item.get("stock_kline_checked")),
        "journal_option_kline_checked_count": sum(1 for item in today_entries if item.get("option_kline_checked")),
        "journal_lens_checked_count": sum(1 for item in today_entries if item.get("lens_checked")),
        "review_step_complete_count": sum(1 for item in today_entries if item.get("review_step_complete")),
        "data_caution": data_caution,
        "high_confidence_allowed": bool(pilot_review.get("high_confidence_allowed")) and not data_caution,
        "llm_signal_core_enabled": False,
        "external_llm_calls_enabled": False,
        "scan_cooldown_seconds": PILOT_SCAN_COOLDOWN_SECONDS,
        "order_submission_wired": False,
        "state_path": str(_live_pilot_state_path(outputs_dir)),
        "acceptance_checks": [
            "Run Default 50 once per trading day.",
            "Run AI Watchlist once per trading day.",
            "Save journal review for every ATM ALERT or WATCH under review.",
            "Keep Data Caution when provider degraded, snapshot stale, or option candles are empty.",
            "Keep LLM Core locked and never auto-trigger broker/order workflows.",
        ],
        "safety": _safety_payload(),
    }


def _live_pilot_state_path(outputs_dir: str | Path) -> Path:
    output_path = Path(outputs_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path / PILOT_STATE_FILE


def _read_live_pilot_state(outputs_dir: str | Path) -> dict[str, Any]:
    path = _live_pilot_state_path(outputs_dir)
    if not path.exists():
        return {"generated_at": None, "market_dates": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"generated_at": None, "market_dates": {}}
    if not isinstance(payload, dict):
        return {"generated_at": None, "market_dates": {}}
    payload.setdefault("market_dates", {})
    return payload


def _write_live_pilot_state(outputs_dir: str | Path, state: dict[str, Any]) -> None:
    path = _live_pilot_state_path(outputs_dir)
    state["generated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _record_live_pilot_scan(payload: dict[str, Any], outputs_dir: str | Path) -> None:
    source_type = str(payload.get("source_type") or "")
    if "fixture" in source_type:
        return
    market_date = _payload_market_date(payload)
    universe = _normalize_universe(str(payload.get("universe") or "default"))
    state = _read_live_pilot_state(outputs_dir)
    market_bucket = (state.setdefault("market_dates", {})).setdefault(market_date, {"universes": {}})
    alerts = payload.get("atm_alerts") or []
    summary = payload.get("alert_summary") if isinstance(payload.get("alert_summary"), dict) else {}
    health = payload.get("live_data_health") if isinstance(payload.get("live_data_health"), dict) else {}
    pilot = payload.get("live_pilot_review") if isinstance(payload.get("live_pilot_review"), dict) else {}
    provider_errors = list(payload.get("provider_errors") or [])
    market_bucket.setdefault("universes", {})[universe] = {
        "status": "failed" if source_type == "live_read_only_unavailable" else "completed",
        "universe": universe,
        "label": "AI Watchlist" if universe == "ai" else "Default 50" if universe == "default" else "All",
        "run_id": payload.get("run_id"),
        "generated_at": payload.get("generated_at"),
        "source_type": source_type,
        "profile_id": payload.get("profile_id") or payload.get("profile"),
        "alert_count": len(alerts),
        "atm_alert_count": summary.get("high_priority_count", 0),
        "watch_count": summary.get("watch_count", 0),
        "pass_count": summary.get("pass_count", 0),
        "provider_error_count": len(provider_errors),
        "provider_429_count": _provider_429_count(provider_errors),
        "requested_symbol_count": health.get("requested_symbol_count"),
        "successful_symbol_count": health.get("successful_symbol_count"),
        "failed_symbol_count": health.get("failed_symbol_count"),
        "data_caution": bool(pilot.get("data_caution") or provider_errors or health.get("provider_degraded")),
        "high_confidence_allowed": bool(pilot.get("high_confidence_allowed")) and not provider_errors,
        "llm_signal_core_enabled": False,
        "order_submission_wired": False,
    }
    _write_live_pilot_state(outputs_dir, state)


def _pilot_universe_status(state: dict[str, Any], market_date: str, universe: str) -> dict[str, Any]:
    record = (((state.get("market_dates") or {}).get(market_date) or {}).get("universes") or {}).get(universe)
    if isinstance(record, dict):
        result = dict(record)
        result["cooldown"] = _cooldown_from_generated_at(result.get("generated_at"))
        return result
    return {
        "status": "pending",
        "universe": universe,
        "label": "AI Watchlist" if universe == "ai" else "Default 50",
        "run_id": None,
        "generated_at": None,
        "alert_count": 0,
        "atm_alert_count": 0,
        "watch_count": 0,
        "provider_error_count": 0,
        "provider_429_count": 0,
        "data_caution": True,
        "high_confidence_allowed": False,
        "cooldown": {"active": False, "remaining_seconds": 0},
    }


def _live_pilot_scan_cooldown(outputs_dir: str | Path, universe: str) -> dict[str, Any]:
    state = _read_live_pilot_state(outputs_dir)
    record = (((state.get("market_dates") or {}).get(_current_market_date()) or {}).get("universes") or {}).get(universe)
    if not isinstance(record, dict):
        return {"active": False, "remaining_seconds": 0}
    return _cooldown_from_generated_at(record.get("generated_at"))


def _cooldown_from_generated_at(generated_at: Any) -> dict[str, Any]:
    try:
        parsed = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
    except ValueError:
        return {"active": False, "remaining_seconds": 0}
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
    remaining = max(int(PILOT_SCAN_COOLDOWN_SECONDS - elapsed), 0)
    return {"active": remaining > 0, "remaining_seconds": remaining}


def _current_market_date() -> str:
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def _payload_market_date(payload: dict[str, Any]) -> str:
    pilot = payload.get("live_pilot_review") if isinstance(payload.get("live_pilot_review"), dict) else {}
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(pilot.get("market_date") or "")):
        return str(pilot["market_date"])
    generated_at = payload.get("generated_at")
    try:
        parsed = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    except ValueError:
        return _current_market_date()


def _read_latest_atm_report(outputs_dir: str | Path) -> dict[str, Any]:
    path = Path(outputs_dir) / "options-atm-alerts-report.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _provider_429_count(provider_errors: list[dict[str, Any]]) -> int:
    count = 0
    for item in provider_errors:
        text = f"{item.get('error', '')} {item.get('status', '')}".lower()
        if "429" in text or "too many requests" in text:
            count += 1
    return count


def score_contract(contract: OptionContract, underlying: UnderlyingSnapshot) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []

    liquidity = _liquidity_score(contract)
    checks.append({"name": "liquidity", "score": liquidity, "max_score": 20, "passed": liquidity >= 14})
    if liquidity < 10:
        blockers.append("Liquidity is too thin for v1.")

    spread = _spread_score(contract)
    checks.append({"name": "bid_ask_spread", "score": spread, "max_score": 20, "passed": spread >= 14})
    if contract.spread_pct > 12:
        blockers.append(f"Bid/ask spread is too wide at {contract.spread_pct:.2f}%.")

    dte = _dte_score(contract)
    checks.append({"name": "dte", "score": dte, "max_score": 10, "passed": dte >= 8})
    if contract.dte < 2 or contract.dte > 60:
        blockers.append(f"DTE {contract.dte} is outside the v1 options scan window.")

    greeks = _greeks_score(contract)
    checks.append({"name": "greeks", "score": greeks, "max_score": 15, "passed": greeks >= 10})
    if abs(contract.delta) < 0.20 or abs(contract.delta) > 0.65:
        blockers.append(f"Delta {contract.delta:.2f} is outside the controlled setup band.")

    iv = _iv_score(contract, underlying)
    checks.append({"name": "iv_level", "score": iv, "max_score": 15, "passed": iv >= 10})
    if contract.implied_volatility > 0.75 or underlying.iv_rank > 0.80:
        blockers.append("IV is elevated enough to require observation only.")

    event = _event_score(contract)
    checks.append({"name": "event_risk", "score": event, "max_score": 10, "passed": event >= 6})
    if contract.event_risk == "high":
        blockers.append("Event risk is high.")

    risk_reward = _risk_reward_score(contract)
    checks.append({"name": "risk_reward", "score": risk_reward, "max_score": 10, "passed": risk_reward >= 7})
    if contract.mid > 12:
        blockers.append("Premium is too large for v1 research risk.")

    preferred_side = _preferred_option_type(underlying)
    if preferred_side and contract.option_type != preferred_side:
        blockers.append(f"Contract side {contract.option_type} is not aligned with {underlying.trend}.")
    if underlying.momentum_score < 35:
        blockers.append(f"Underlying momentum score {underlying.momentum_score:.1f} is below v1 threshold.")

    total = round(sum(item["score"] for item in checks), 2)
    recommendation = _contract_recommendation(total, blockers)
    return {
        "option_symbol": contract.option_symbol,
        "underlying": contract.underlying,
        "recommendation": recommendation,
        "total_score": total,
        "checks": checks,
        "blockers": blockers,
        "preferred_side": preferred_side,
        "underlying_momentum_score": underlying.momentum_score,
        "underlying_change_pct": underlying.change_pct,
        "underlying_relative_volume": underlying.relative_volume,
        "contract": _contract_payload(contract, underlying, data_quality=_data_quality_for_underlying(underlying)),
        "agent_note": _agent_note(recommendation, blockers),
    }


def write_options_worthiness_report(payload: dict[str, Any], outputs_dir: str | Path) -> dict[str, str]:
    output_dir = Path(outputs_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "options-worthiness-report.md"
    json_path = output_dir / "options-worthiness-report.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_render_markdown(payload), encoding="utf-8")
    return {"report_path": str(md_path), "report_json_path": str(json_path)}


def write_options_atm_alerts_report(payload: dict[str, Any], outputs_dir: str | Path) -> dict[str, str]:
    output_dir = Path(outputs_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "options-atm-alerts-report.md"
    json_path = output_dir / "options-atm-alerts-report.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_render_atm_alerts_markdown(payload), encoding="utf-8")
    return {"report_path": str(md_path), "report_json_path": str(json_path)}


def _selected_symbols(symbols: list[str] | None, *, universe: str = "default") -> list[str]:
    base_symbols = symbols or OPTION_UNIVERSES[_normalize_universe(universe)]
    selected = [_normalize_symbol(symbol) for symbol in base_symbols]
    deduped: list[str] = []
    for symbol in selected:
        if symbol and symbol not in deduped:
            deduped.append(symbol)
    return deduped


def _normalize_universe(universe: str | None) -> str:
    value = str(universe or "default").lower().strip()
    return value if value in OPTION_UNIVERSES else "default"


def _universe_payload() -> dict[str, Any]:
    return {
        "default": {"label": "Default 50", "symbols": DEFAULT_OPTION_SYMBOLS},
        "ai": {"label": "AI Watchlist", "symbols": AI_OPTION_SYMBOLS},
        "all": {"label": "All", "symbols": ALL_OPTION_SYMBOLS},
    }


def _live_data_health(
    *,
    requested_symbols: list[str],
    successful_symbols: list[str],
    provider_errors: list[dict[str, Any]],
    source_type: str,
    chain_symbols: list[str] | None = None,
    successful_chain_symbols: list[str] | None = None,
) -> dict[str, Any]:
    requested = [_normalize_symbol(symbol) for symbol in requested_symbols if _normalize_symbol(symbol)]
    successful = list(dict.fromkeys(_normalize_symbol(symbol) for symbol in successful_symbols if _normalize_symbol(symbol)))
    error_symbols = list(
        dict.fromkeys(
            _normalize_symbol(item.get("symbol"))
            for item in provider_errors
            if isinstance(item, dict) and _normalize_symbol(item.get("symbol")) and _normalize_symbol(item.get("symbol")) != "-"
        )
    )
    failed = [symbol for symbol in requested if symbol not in successful]
    failed = list(dict.fromkeys([*failed, *(symbol for symbol in error_symbols if symbol not in successful)]))
    chain_requested = [
        _normalize_symbol(symbol)
        for symbol in (chain_symbols or [])
        if _normalize_symbol(symbol)
    ]
    chain_success = [
        _normalize_symbol(symbol)
        for symbol in (successful_chain_symbols or [])
        if _normalize_symbol(symbol)
    ]
    provider_degraded = bool(provider_errors or failed or ("partial" in source_type) or ("unavailable" in source_type))
    return {
        "source_type": source_type,
        "requested_symbol_count": len(requested),
        "successful_symbol_count": len(successful),
        "failed_symbol_count": len(failed),
        "successful_symbols": successful,
        "failed_symbols": failed,
        "provider_error_count": len(provider_errors),
        "provider_degraded": provider_degraded,
        "all_failed": bool(requested and not successful),
        "chain_requested_symbol_count": len(chain_requested),
        "chain_successful_symbol_count": len(chain_success),
        "chain_symbols": chain_requested,
        "successful_chain_symbols": chain_success,
        "frequency_profile": FREQUENCY_PROFILE,
    }


def _price_history_payload(
    *,
    generated_at: str,
    source_type: str,
    instrument_type: str,
    symbol: str,
    option_symbol: str | None,
    range_value: str,
    interval: str,
    candles: list[dict[str, Any]],
    provider_errors: list[dict[str, Any]],
    live_data_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "generated_at": generated_at,
        "source_type": source_type,
        "instrument_type": instrument_type,
        "symbol": symbol,
        "option_symbol": option_symbol,
        "range": range_value,
        "interval": interval,
        "candles": candles,
        "provider_errors": provider_errors,
        "provider_status": {
            "source_type": source_type,
            "provider_available": bool(candles and not provider_errors),
            "provider_error_count": len(provider_errors),
            "provider_errors": provider_errors,
            "decision_available": bool(candles),
        },
        "freshness": {
            "generated_at": generated_at,
            "age_seconds": 0.0,
            "max_age_seconds": 900,
            "is_fresh": True,
        },
        "safety": _safety_payload(),
    }
    if live_data_health is not None:
        payload["live_data_health"] = live_data_health
    return payload


def _fetch_yahoo_price_history(
    symbol: str,
    *,
    range_value: str,
    interval: str,
    timeout: float,
) -> list[dict[str, Any]]:
    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
        f"?range={urllib.parse.quote(range_value)}&interval={urllib.parse.quote(interval)}"
    )
    data = _http_json(url, timeout=timeout)
    result = (data.get("chart", {}).get("result") or [None])[0]
    if not result:
        raise ValueError("Yahoo chart returned no result.")
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    candles: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        open_value = _to_float(opens[index] if index < len(opens) else None)
        high_value = _to_float(highs[index] if index < len(highs) else None)
        low_value = _to_float(lows[index] if index < len(lows) else None)
        close_value = _to_float(closes[index] if index < len(closes) else None)
        if open_value is None or high_value is None or low_value is None or close_value is None:
            continue
        candles.append(
            {
                "open_time": int(float(timestamp) * 1000),
                "open": round(open_value, 4),
                "high": round(high_value, 4),
                "low": round(low_value, 4),
                "close": round(close_value, 4),
                "volume": int(_to_float(volumes[index] if index < len(volumes) else 0) or 0),
            }
        )
    return candles


def _fixture_underlying_candles(symbol: str, *, range_value: str, interval: str) -> list[dict[str, Any]]:
    snapshots = _underlying_fixtures()
    underlying = snapshots.get(symbol) or _empty_underlying(symbol)
    count = _history_candle_count(range_value, interval)
    step_ms = _history_interval_ms(interval)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start_ms = int((now - timedelta(milliseconds=step_ms * (count - 1))).timestamp() * 1000)
    seed = (ALL_OPTION_SYMBOLS.index(symbol) + 1) if symbol in ALL_OPTION_SYMBOLS else 7
    base = max(underlying.price, 1.0)
    trend = underlying.change_pct / 100
    candles: list[dict[str, Any]] = []
    previous_close = base * (1 - trend * 0.55)
    for index in range(count):
        progress = index / max(count - 1, 1)
        wave = math.sin((index + seed) * 0.41) * base * 0.0045
        drift = (progress - 0.5) * trend * base
        close = max(base + drift + wave, 0.25)
        open_value = previous_close
        high = max(open_value, close) + base * (0.002 + ((seed + index) % 5) * 0.00045)
        low = min(open_value, close) - base * (0.002 + ((seed + index) % 3) * 0.0005)
        candles.append(
            {
                "open_time": start_ms + index * step_ms,
                "open": round(open_value, 4),
                "high": round(high, 4),
                "low": round(max(low, 0.01), 4),
                "close": round(close, 4),
                "volume": int(max(100000, 550000 + seed * 29000 + abs(math.sin(index * 0.37 + seed)) * 850000)),
            }
        )
        previous_close = close
    return candles


def _fixture_option_candles(option_symbol: str, *, range_value: str, interval: str) -> list[dict[str, Any]]:
    parsed = _parse_option_symbol(option_symbol)
    if not parsed:
        return []
    detail = options_contract(option_symbol, source="fixture")
    contract = detail.get("contract")
    if not contract:
        return []
    underlying_candles = _fixture_underlying_candles(parsed["underlying"], range_value=range_value, interval=interval)
    underlying_price = float(contract.get("underlying_price") or 0.0) or float(detail.get("underlying", {}).get("price") or 1.0)
    base_mid = max(float(contract.get("mid") or 0.35), 0.05)
    side = str(contract.get("option_type") or parsed["option_type"])
    candles: list[dict[str, Any]] = []
    previous_close = base_mid
    for index, candle in enumerate(underlying_candles):
        move = (float(candle["close"]) - underlying_price) / max(underlying_price, 0.01)
        directional = move * (3.8 if side == "call" else -3.8)
        wave = math.sin(index * 0.53 + base_mid) * 0.055
        close = max(base_mid * (1 + directional + wave), 0.02)
        open_value = previous_close
        high = max(open_value, close) * 1.035
        low = min(open_value, close) * 0.965
        candles.append(
            {
                "open_time": candle["open_time"],
                "open": round(open_value, 4),
                "high": round(high, 4),
                "low": round(max(low, 0.01), 4),
                "close": round(close, 4),
                "volume": int(max(10, float(contract.get("volume") or 1000) / max(len(underlying_candles), 1) * (0.65 + abs(math.sin(index * 0.31))))),
            }
        )
        previous_close = close
    return candles


def _history_interval_ms(interval: str) -> int:
    return {"5m": 5 * 60 * 1000, "15m": 15 * 60 * 1000, "1d": 24 * 60 * 60 * 1000}.get(interval, 15 * 60 * 1000)


def _history_candle_count(range_value: str, interval: str) -> int:
    if interval == "1d":
        if range_value == "1y":
            return 252
        if range_value == "3mo":
            return 63
        return 22 if range_value == "1mo" else 5 if range_value == "5d" else 1
    if range_value == "1d":
        return 78 if interval == "5m" else 26
    if range_value == "1y":
        return 780 if interval == "5m" else 390
    if range_value == "3mo":
        return 780 if interval == "5m" else 390
    if range_value == "1mo":
        return 180 if interval == "5m" else 120
    return 390 if interval == "5m" else 130


def _normalize_symbol(symbol: str) -> str:
    return "".join(ch for ch in str(symbol).upper() if ch.isalnum())[:12]


def _daily_candidate_records(
    underlyings: list[UnderlyingSnapshot],
    errors: list[dict[str, Any]],
    scan_time: str,
    source_type: str,
) -> list[dict[str, Any]]:
    return [
        {
            "symbol": underlying.symbol,
            "name": underlying.name,
            "scan_time": scan_time,
            "quote_updated_at": underlying.updated_at,
            "price": underlying.price,
            "change_pct": underlying.change_pct,
            "relative_volume": underlying.relative_volume,
            "momentum_score": underlying.momentum_score,
            "scan_rank": underlying.scan_rank,
            "trend": underlying.trend,
            "theme_tags": list(underlying.theme_tags),
            "universe_groups": list(underlying.universe_groups),
            "preferred_side": _preferred_option_type(underlying) or "observe",
            "data_source": underlying.data_source,
            "data_quality": _data_quality_for_symbol(underlying.symbol, underlying, errors, True),
            "source_type": source_type,
            "suggested_observation_window": _suggested_observation_window(
                _data_quality_for_symbol(underlying.symbol, underlying, errors, True),
                [item for item in errors if item.get("symbol") == underlying.symbol],
            ),
        }
        for underlying in underlyings
    ]


def _data_quality_for_underlying(underlying: UnderlyingSnapshot) -> str:
    if underlying.data_source == "fixture_read_only":
        return "fixture"
    if underlying.data_source == "nasdaq_quote_public":
        return "fallback"
    if underlying.data_source == "unavailable":
        return "unavailable"
    return "live"


def _data_quality_for_symbol(
    symbol: str,
    underlying: UnderlyingSnapshot | None,
    errors: list[dict[str, Any]],
    has_chain_or_quote: bool,
) -> str:
    if underlying is None:
        return "unavailable"
    symbol_errors = [item for item in errors if item.get("symbol") == symbol]
    if underlying.data_source == "fixture_read_only":
        return "fixture"
    if any(item.get("fallback") for item in symbol_errors) or underlying.data_source == "nasdaq_quote_public":
        return "fallback" if has_chain_or_quote else "partial"
    if symbol_errors:
        return "partial" if has_chain_or_quote else "unavailable"
    return "live"


def _suggested_observation_window(data_quality: str, errors: list[dict[str, Any]]) -> dict[str, Any]:
    if data_quality in {"unavailable", "partial"} and not any(item.get("fallback") for item in errors):
        return {
            "label": "NO OBSERVATION",
            "timezone": "America/New_York",
            "start": None,
            "end": None,
            "reason": "Public quote or option-chain data is unavailable.",
        }
    return {
        "label": "US cash session 10:00-11:30 ET",
        "timezone": "America/New_York",
        "start": "10:00",
        "end": "11:30",
        "reason": "Avoid the first 30 minutes of spread instability; reassess before lunch liquidity fades.",
    }


def _filter_contracts_by_expiration(contracts: list[OptionContract], expiration: str | None) -> list[OptionContract]:
    if not expiration:
        return list(contracts)
    return [contract for contract in contracts if contract.expiration == expiration]


def _contract_payload(
    contract: OptionContract,
    underlying: UnderlyingSnapshot,
    *,
    data_quality: str,
) -> dict[str, Any]:
    payload = contract.to_payload()
    payload["side"] = contract.option_type
    payload["quote_updated_at"] = underlying.updated_at
    payload["underlying_price"] = underlying.price
    payload["data_quality"] = data_quality
    payload["moneyness"] = _moneyness(contract, underlying)
    payload["intrinsic_value"] = _intrinsic_value(contract, underlying)
    payload["distance_pct"] = round(((contract.strike - underlying.price) / underlying.price) * 100, 2) if underlying.price else None
    payload["model_inputs"] = {
        "underlying_price": underlying.price,
        "strike": contract.strike,
        "dte": contract.dte,
        "implied_volatility": contract.implied_volatility,
        "delta": contract.delta,
        "gamma": contract.gamma,
        "theta": contract.theta,
        "vega": contract.vega,
        "option_type": contract.option_type,
    }
    return payload


def _moneyness(contract: OptionContract, underlying: UnderlyingSnapshot) -> str:
    if not underlying.price:
        return "-"
    distance_pct = abs(contract.strike - underlying.price) / underlying.price * 100
    if distance_pct <= 1.0:
        return "ATM"
    if contract.option_type == "call":
        return "ITM" if underlying.price > contract.strike else "OTM"
    return "ITM" if underlying.price < contract.strike else "OTM"


def _intrinsic_value(contract: OptionContract, underlying: UnderlyingSnapshot) -> float:
    if contract.option_type == "call":
        return round(max(underlying.price - contract.strike, 0.0), 2)
    return round(max(contract.strike - underlying.price, 0.0), 2)


def _expiration_groups(contracts: list[OptionContract]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for contract in contracts:
        item = groups.setdefault(
            contract.expiration,
            {"expiration": contract.expiration, "dte": contract.dte, "contract_count": 0},
        )
        item["contract_count"] += 1
    return sorted(groups.values(), key=lambda item: (item["dte"], item["expiration"]))


def _broker_chain_rows(
    contracts: list[OptionContract],
    underlying: UnderlyingSnapshot,
    *,
    data_quality: str,
) -> list[dict[str, Any]]:
    rows: dict[tuple[str, float], dict[str, Any]] = {}
    for contract in contracts:
        key = (contract.expiration, contract.strike)
        row = rows.setdefault(
            key,
            {
                "expiration": contract.expiration,
                "dte": contract.dte,
                "strike": contract.strike,
                "distance_pct": round(((contract.strike - underlying.price) / underlying.price) * 100, 2) if underlying.price else None,
                "call": None,
                "put": None,
            },
        )
        row[contract.option_type] = _contract_payload(contract, underlying, data_quality=data_quality)
    return sorted(rows.values(), key=lambda item: (item["dte"], item["strike"]))


def _parse_option_symbol(option_symbol: str) -> dict[str, Any] | None:
    normalized = str(option_symbol).upper().strip()
    match = re.match(r"^([A-Z]+)(\d{6})([CP])(\d{8})$", normalized)
    if not match:
        return None
    underlying, yymmdd, side, strike_raw = match.groups()
    expiration = datetime.strptime(yymmdd, "%y%m%d").date().isoformat()
    return {
        "underlying": underlying,
        "expiration": expiration,
        "option_type": "call" if side == "C" else "put",
        "strike": int(strike_raw) / 1000,
    }


def _contract_from_payload(payload: dict[str, Any]) -> OptionContract:
    return OptionContract(
        option_symbol=str(payload["option_symbol"]),
        underlying=str(payload["underlying"]),
        expiration=str(payload["expiration"]),
        dte=int(payload["dte"]),
        strike=float(payload["strike"]),
        option_type=str(payload["option_type"]),
        bid=float(payload["bid"]),
        ask=float(payload["ask"]),
        volume=int(payload["volume"]),
        open_interest=int(payload["open_interest"]),
        implied_volatility=float(payload["implied_volatility"]),
        delta=float(payload["delta"]),
        gamma=float(payload["gamma"]),
        theta=float(payload["theta"]),
        vega=float(payload["vega"]),
        event_risk=str(payload["event_risk"]),
    )


def _build_model_surface(
    *,
    contract: dict[str, Any],
    underlying: dict[str, Any],
    price_steps: int,
    iv_steps: int,
) -> dict[str, Any]:
    raw_contract = _contract_from_payload(contract)
    spot = _to_float(contract.get("underlying_price")) or _to_float(underlying.get("price")) or raw_contract.strike
    base_iv = _to_float(contract.get("implied_volatility")) or 0.30
    base_iv = min(max(base_iv, 0.05), 3.0)
    price_count = _odd_step_count(price_steps, minimum=5, maximum=15)
    iv_count = _odd_step_count(iv_steps, minimum=5, maximum=13)
    price_axis = _linspace(round(spot * 0.90, 2), round(spot * 1.10, 2), price_count)
    iv_axis = _linspace(round(max(base_iv * 0.50, 0.05), 4), round(min(max(base_iv * 1.50, base_iv + 0.05), 4.0), 4), iv_count)
    model_dte = max(raw_contract.dte, 1)
    base_theoretical_price = _black_scholes_price(
        spot=spot,
        strike=raw_contract.strike,
        dte=model_dte,
        sigma=base_iv,
        option_type=raw_contract.option_type,
    )
    premium_reference = max(raw_contract.mid, 0.01)
    surface_rows: list[dict[str, Any]] = []
    min_pnl = math.inf
    max_pnl = -math.inf
    min_price = math.inf
    max_price = -math.inf
    for iv in iv_axis:
        points = []
        for price in price_axis:
            theoretical = _black_scholes_price(
                spot=price,
                strike=raw_contract.strike,
                dte=model_dte,
                sigma=iv,
                option_type=raw_contract.option_type,
            )
            pnl_per_share = theoretical - premium_reference
            pnl_per_contract = pnl_per_share * 100.0
            min_pnl = min(min_pnl, pnl_per_contract)
            max_pnl = max(max_pnl, pnl_per_contract)
            min_price = min(min_price, theoretical)
            max_price = max(max_price, theoretical)
            points.append(
                {
                    "underlying_price": round(price, 2),
                    "implied_volatility": round(iv, 4),
                    "theoretical_price": round(theoretical, 4),
                    "pnl_per_share": round(pnl_per_share, 4),
                    "pnl_per_contract": round(pnl_per_contract, 2),
                }
            )
        surface_rows.append({"implied_volatility": round(iv, 4), "points": points})

    base_greeks = _black_scholes_greeks(
        spot=spot,
        strike=raw_contract.strike,
        dte=model_dte,
        sigma=base_iv,
        option_type=raw_contract.option_type,
    )
    return {
        "model_type": "black_scholes_surface_v1",
        "orientation": "long_option_premium_reference",
        "price_axis": price_axis,
        "iv_axis": iv_axis,
        "surface": surface_rows,
        "base": {
            "underlying_price": round(spot, 2),
            "strike": raw_contract.strike,
            "option_type": raw_contract.option_type,
            "dte": raw_contract.dte,
            "model_dte": model_dte,
            "implied_volatility": round(base_iv, 4),
            "premium_reference": round(premium_reference, 4),
            "theoretical_price": round(base_theoretical_price, 4),
            "delta": round(base_greeks["delta"], 4),
            "gamma": round(base_greeks["gamma"], 5),
            "theta": round(base_greeks["theta"], 5),
            "vega": round(base_greeks["vega"], 5),
        },
        "summary": {
            "min_theoretical_price": round(min_price, 4) if min_price < math.inf else None,
            "max_theoretical_price": round(max_price, 4) if max_price > -math.inf else None,
            "min_pnl_per_contract": round(min_pnl, 2) if min_pnl < math.inf else None,
            "max_pnl_per_contract": round(max_pnl, 2) if max_pnl > -math.inf else None,
            "break_even_at_expiration": round(
                raw_contract.strike + premium_reference
                if raw_contract.option_type == "call"
                else raw_contract.strike - premium_reference,
                2,
            ),
        },
        "risk_notes": _model_surface_risk_notes(raw_contract, base_iv),
        "next_3d_inputs": {
            "x": "underlying_price",
            "y": "implied_volatility",
            "z": "pnl_per_contract",
            "color": "delta_or_pnl_sign",
        },
    }


def _build_model_decision_lens(
    *,
    model: dict[str, Any],
    contract: OptionContract,
    underlying: dict[str, Any],
    score: dict[str, Any],
) -> dict[str, Any]:
    points = [point for row in model.get("surface", []) for point in row.get("points", [])]
    base = model.get("base", {})
    spot = _to_float(base.get("underlying_price")) or contract.strike
    base_iv = _to_float(base.get("implied_volatility")) or contract.implied_volatility or 0.30
    premium_contract = max((_to_float(base.get("premium_reference")) or contract.mid or 0.01) * 100.0, 1.0)
    expected_move_pct = _decision_expected_move_pct(underlying)
    expected_price = spot * (1.0 + expected_move_pct)
    momentum = _to_float(underlying.get("momentum_score")) or 0.0
    expected_iv = min(max(base_iv * (1.0 + min(max(momentum, 0.0), 100.0) / 100.0 * 0.18), 0.05), 4.0)
    price_band = max(spot * (0.012 + min(abs(expected_move_pct), 0.06) * 0.75), 0.01)
    iv_band = max(base_iv * 0.18, 0.025)

    weighted: list[tuple[float, float]] = []
    profit_weight = 0.0
    total_weight = 0.0
    for point in points:
        price = _to_float(point.get("underlying_price")) or spot
        iv = _to_float(point.get("implied_volatility")) or base_iv
        pnl = _to_float(point.get("pnl_per_contract")) or 0.0
        price_weight = math.exp(-0.5 * ((price - expected_price) / price_band) ** 2)
        iv_weight = math.exp(-0.5 * ((iv - expected_iv) / iv_band) ** 2)
        weight = max(price_weight * iv_weight, 0.000001)
        weighted.append((pnl, weight))
        total_weight += weight
        if pnl > 0:
            profit_weight += weight

    expected_pnl = sum(pnl * weight for pnl, weight in weighted) / total_weight if total_weight else 0.0
    profit_probability = profit_weight / total_weight if total_weight else 0.0
    downside_p10 = _weighted_quantile(weighted, 0.10)
    upside_p90 = _weighted_quantile(weighted, 0.90)
    model_edge_pct = expected_pnl / premium_contract * 100.0
    aligned = _contract_aligned_with_expected_move(contract.option_type, expected_move_pct)
    agent_gate = score.get("recommendation") or RECOMMEND_NO_TRADE
    score_blockers = list(score.get("blockers") or [])
    buy_blockers: list[str] = []

    if agent_gate != RECOMMEND_TRADE:
        buy_blockers.append(f"Agent gate is {agent_gate}, not {RECOMMEND_TRADE}.")
    if not aligned:
        buy_blockers.append("Contract side is not aligned with the scenario-weighted directional move.")
    if expected_pnl < max(25.0, premium_contract * 0.08):
        buy_blockers.append("Scenario-weighted expected PnL does not clear the v1 edge threshold.")
    if profit_probability < 0.55:
        buy_blockers.append("Profit scenario weight is below 55%.")
    if downside_p10 < -premium_contract * 0.70:
        buy_blockers.append("Downside tail exceeds 70% of premium at the p10 scenario.")
    for blocker in score_blockers[:4]:
        if blocker not in buy_blockers:
            buy_blockers.append(str(blocker))

    if not buy_blockers:
        decision = "BUY CANDIDATE"
    elif expected_pnl > 0 and profit_probability >= 0.45 and agent_gate != RECOMMEND_NO_TRADE:
        decision = "WATCH"
    else:
        decision = "AVOID"

    confidence = "low"
    if decision == "BUY CANDIDATE" and profit_probability >= 0.62 and model_edge_pct >= 12:
        confidence = "medium"
    elif decision == "WATCH" and expected_pnl > 0:
        confidence = "guarded"

    return {
        "model_type": "scenario_weighted_buy_lens_v1",
        "decision": decision,
        "should_buy": decision == "BUY CANDIDATE",
        "confidence": confidence,
        "agent_gate": agent_gate,
        "score": score.get("total_score"),
        "prediction": {
            "expected_underlying_price": round(expected_price, 2),
            "expected_move_pct": round(expected_move_pct * 100.0, 2),
            "expected_implied_volatility": round(expected_iv, 4),
            "horizon_dte": contract.dte,
        },
        "metrics": {
            "expected_pnl_per_contract": round(expected_pnl, 2),
            "model_edge_pct_of_premium": round(model_edge_pct, 2),
            "profit_scenario_weight_pct": round(profit_probability * 100.0, 1),
            "downside_p10_pnl_per_contract": round(downside_p10, 2),
            "upside_p90_pnl_per_contract": round(upside_p90, 2),
            "premium_at_risk_per_contract": round(premium_contract, 2),
        },
        "buy_blockers": buy_blockers,
        "explanation": _decision_lens_explanation(decision, expected_pnl, profit_probability, buy_blockers),
        "method": "Scenario-weighted Black-Scholes grid using current momentum, IV, Agent gate, and long-premium PnL.",
        "visual_scale": {
            "metric": "pnl_per_contract",
            "unit": "USD",
            "bands": _decision_lens_color_bands(),
        },
        "safety": _safety_payload(),
    }


def _decision_lens_color_bands() -> list[dict[str, Any]]:
    return [
        {"label": "tail loss", "max_pnl_per_contract": -250, "color": "#7f1d1d"},
        {"label": "loss", "min_pnl_per_contract": -250, "max_pnl_per_contract": -75, "color": "#ef4444"},
        {"label": "premium drag", "min_pnl_per_contract": -75, "max_pnl_per_contract": -10, "color": "#f97316"},
        {"label": "near flat", "min_pnl_per_contract": -10, "max_pnl_per_contract": 10, "color": "#facc15"},
        {"label": "light edge", "min_pnl_per_contract": 10, "max_pnl_per_contract": 100, "color": "#84cc16"},
        {"label": "profit", "min_pnl_per_contract": 100, "max_pnl_per_contract": 350, "color": "#22c55e"},
        {"label": "strong edge", "min_pnl_per_contract": 350, "color": "#14b8a6"},
    ]


def _decision_expected_move_pct(underlying: dict[str, Any]) -> float:
    change_pct = _to_float(underlying.get("change_pct")) or 0.0
    momentum = max(_to_float(underlying.get("momentum_score")) or 0.0, 0.0)
    trend = str(underlying.get("trend") or "").lower()
    if trend.startswith("bullish"):
        direction = 1.0
    elif trend.startswith("bearish"):
        direction = -1.0
    elif change_pct > 0:
        direction = 1.0
    elif change_pct < 0:
        direction = -1.0
    else:
        direction = 0.0
    if direction == 0.0:
        return 0.0
    momentum_move = 0.005 + min(momentum, 100.0) / 100.0 * 0.025
    observed_move = min(abs(change_pct) / 100.0, 0.06)
    return direction * min(max(momentum_move, observed_move), 0.06)


def _contract_aligned_with_expected_move(option_type: str, expected_move_pct: float) -> bool:
    if abs(expected_move_pct) < 0.0025:
        return False
    if option_type == "call":
        return expected_move_pct > 0
    if option_type == "put":
        return expected_move_pct < 0
    return False


def _weighted_quantile(weighted_values: list[tuple[float, float]], quantile: float) -> float:
    if not weighted_values:
        return 0.0
    ordered = sorted(weighted_values, key=lambda item: item[0])
    total_weight = sum(max(weight, 0.0) for _, weight in ordered)
    if total_weight <= 0:
        index = min(max(int(round((len(ordered) - 1) * quantile)), 0), len(ordered) - 1)
        return ordered[index][0]
    threshold = total_weight * min(max(quantile, 0.0), 1.0)
    running = 0.0
    for value, weight in ordered:
        running += max(weight, 0.0)
        if running >= threshold:
            return value
    return ordered[-1][0]


def _decision_lens_explanation(
    decision: str,
    expected_pnl: float,
    profit_probability: float,
    blockers: list[str],
) -> str:
    if decision == "BUY CANDIDATE":
        return (
            f"Scenario lens favors a read-only buy candidate: expected PnL {expected_pnl:.2f} "
            f"with {profit_probability * 100:.1f}% weighted profitable scenarios."
        )
    if decision == "WATCH":
        primary = blockers[0] if blockers else "One or more v1 buy gates did not clear."
        return (
            f"Watch only: expected PnL is {expected_pnl:.2f} with "
            f"{profit_probability * 100:.1f}% weighted profitable scenarios, but {primary}"
        )
    primary = blockers[0] if blockers else "Scenario lens does not support a buy."
    return f"Avoid under v1: {primary}"


def _odd_step_count(value: int, *, minimum: int, maximum: int) -> int:
    count = min(max(int(value or minimum), minimum), maximum)
    return count if count % 2 == 1 else count + 1 if count < maximum else count - 1


def _linspace(start: float, end: float, count: int) -> list[float]:
    if count <= 1 or start == end:
        return [round(start, 4)]
    step = (end - start) / (count - 1)
    return [round(start + step * index, 4) for index in range(count)]


def _model_surface_risk_notes(contract: OptionContract, base_iv: float) -> list[str]:
    notes = [
        "Model assumes European-style Black-Scholes pricing and a long premium reference.",
        "Surface does not model liquidity shocks, spread widening, assignment, exercise, or commissions.",
    ]
    if contract.dte <= 1:
        notes.append("DTE is 0-1; model uses at least one calendar day to avoid expiry singularities.")
    if contract.spread_pct >= 20:
        notes.append(f"Bid/ask spread is wide at {contract.spread_pct:.2f}%; modeled PnL can overstate tradability.")
    if base_iv >= 1.0:
        notes.append("IV is extremely high; model output is sensitive to volatility compression.")
    return notes


def _build_atm_alerts_payload(
    *,
    generated_at: str,
    source_type: str,
    universe: str,
    selected: list[str],
    ranked: list[UnderlyingSnapshot],
    chains: dict[str, list[OptionContract]],
    provider_errors: list[dict[str, Any]],
    live_data_health: dict[str, Any] | None,
    signal_profile: dict[str, Any],
) -> dict[str, Any]:
    alerts: list[dict[str, Any]] = []
    for underlying in ranked:
        contracts = chains.get(underlying.symbol, [])
        data_quality = _data_quality_for_symbol(underlying.symbol, underlying, provider_errors, bool(contracts))
        alerts.extend(
            _atm_alert_records_for_underlying(
                underlying=underlying,
                contracts=contracts,
                data_quality=data_quality,
                source_type=source_type,
                signal_profile=signal_profile,
            )
        )
    alerts.sort(key=_atm_alert_sort_key)
    summary = _atm_alert_summary(alerts, signal_profile)
    run_id = _atm_alert_run_id(generated_at, universe, selected, source_type, signal_profile)
    payload = {
        "run_id": run_id,
        "generated_at": generated_at,
        "source_type": source_type,
        "module": "ATM Options Manual Signal Assistant v1",
        "strategy_id": signal_profile["strategy_id"],
        "profile": signal_profile["profile_id"],
        "profile_id": signal_profile["profile_id"],
        "universe": universe,
        "universes": _universe_payload(),
        "symbols": selected,
        "scanned_symbol_count": len(ranked),
        "frequency_profile": FREQUENCY_PROFILE,
        "llm_policy": _llm_policy_payload(),
        "atm_signal_profile": signal_profile,
        "daily_candidates": _daily_candidate_records(ranked, provider_errors, generated_at, source_type),
        "atm_alerts": alerts,
        "alert_summary": summary,
        "overall_alert_level": summary["overall_alert_level"],
        "provider_errors": provider_errors,
        "scanner": {
            "underlying_provider": "yahoo_chart_public" if source_type != "fixture_read_only" else "fixture_read_only",
            "options_provider": "nasdaq_option_chain_public" if source_type != "fixture_read_only" else "fixture_read_only",
            "ranking": "ATM contract fit, stock momentum, liquidity, IV/event risk, and 3D buy lens summary",
            "profile": signal_profile["profile_id"],
            "dte_window": signal_profile["dte_window"],
            "delta_band": signal_profile["delta_band"],
            "atm_moneyness_pct": signal_profile["atm_moneyness_pct"],
            "alert_score_threshold": signal_profile["alert_score_threshold"],
            "watch_score_threshold": signal_profile["watch_score_threshold"],
            "max_alert_spread_pct": signal_profile["max_alert_spread_pct"],
            "min_alert_volume": signal_profile["min_alert_volume"],
            "min_alert_open_interest": signal_profile["min_alert_open_interest"],
        },
        "manual_research_flow": [
            "Review Today's ATM Option Alerts.",
            "Confirm the stock setup on 1Y/1D and 5D/15m K-Line context.",
            "Check the selected ATM contract liquidity, spread, and option K-Line.",
            "Open 3D Buy Lens for final research confirmation.",
            "Use Alpaca Paper only through the gated manual intent/order API; Live remains disabled.",
        ],
        "limitations": _atm_alert_limitations(source_type),
        "safety": _safety_payload(),
    }
    if live_data_health is not None:
        payload["live_data_health"] = live_data_health
    return payload


def _attach_live_pilot_review(payload: dict[str, Any], outputs_dir: str | Path, db_path: str | Path | None = None) -> None:
    alerts = payload.get("atm_alerts") or []
    health = payload.get("live_data_health") if isinstance(payload.get("live_data_health"), dict) else {}
    source_type = str(payload.get("source_type") or "")
    is_fixture = source_type == "fixture_read_only"
    provider_degraded = bool(
        health.get("provider_degraded")
        or payload.get("provider_errors")
        or "unavailable" in source_type
        or "partial" in source_type
    )
    data_caution = is_fixture or provider_degraded
    caution_reasons: list[str] = []
    if is_fixture:
        caution_reasons.append("Fixture demo mode; use live entry for real pilot review.")
    if provider_degraded:
        caution_reasons.append("Public provider is degraded or partially unavailable.")
    if not alerts:
        caution_reasons.append("No ATM alerts are available for review.")
    if data_caution:
        for alert in alerts:
            alert["data_caution"] = True
            alert["confidence_label"] = "DATA CAUTION"
            warnings = list(alert.get("risk_warnings") or [])
            warning = (
                "Data Caution: fixture demo mode; use live entry before pilot review."
                if is_fixture
                else "Data Caution: provider degraded; do not treat this as high confidence."
            )
            if warning not in warnings:
                warnings.insert(0, warning)
            alert["risk_warnings"] = warnings
    else:
        for alert in alerts:
            alert["data_caution"] = False
            alert["confidence_label"] = "HIGH CONFIDENCE" if alert.get("alert_level") == ATM_ALERT and not is_fixture else alert.get("alert_level")
    journal_summary = journal_summary_for_alerts(outputs_dir, alerts, db_path=db_path)
    payload["live_pilot_review"] = {
        "phase": "3_trading_day_live_observation",
        "planned_trading_days": 3,
        "market_date": datetime.now(ZoneInfo("America/New_York")).date().isoformat(),
        "source_type": source_type,
        "profile_id": payload.get("profile_id") or payload.get("profile"),
        "review_allowed": bool(alerts) and not is_fixture,
        "high_confidence_allowed": bool(alerts) and not is_fixture and not data_caution,
        "data_caution": bool(caution_reasons),
        "data_caution_reasons": caution_reasons,
        "atm_alert_count": sum(1 for item in alerts if item.get("alert_level") == ATM_ALERT),
        "watch_count": sum(1 for item in alerts if item.get("alert_level") == ATM_WATCH),
        "pass_count": sum(1 for item in alerts if item.get("alert_level") == ATM_PASS),
        "journal": journal_summary,
        "acceptance_checks": [
            "Run live Default 50 scan once per trading day.",
            "Run live AI Watchlist scan once per trading day.",
            "Review only after stock K-Line, option K-Line, liquidity, and 3D Lens checks.",
            "Do not place orders inside kquant; record only manual observations.",
        ],
    }


def _atm_alert_records_for_underlying(
    *,
    underlying: UnderlyingSnapshot,
    contracts: list[OptionContract],
    data_quality: str,
    source_type: str,
    signal_profile: dict[str, Any],
) -> list[dict[str, Any]]:
    if not contracts:
        return []
    preferred_side = _preferred_option_type(underlying)
    sides = [preferred_side] if preferred_side else ["call", "put"]
    records = []
    for side in [item for item in sides if item]:
        contract = _select_atm_contract(contracts, underlying, side)
        if contract is None:
            continue
        records.append(
            _build_atm_alert_record(
                underlying,
                contract,
                data_quality=data_quality,
                source_type=source_type,
                signal_profile=signal_profile,
            )
        )
    return records


def _select_atm_contract(
    contracts: list[OptionContract],
    underlying: UnderlyingSnapshot,
    side: str,
) -> OptionContract | None:
    side_contracts = [contract for contract in contracts if contract.option_type == side]
    if not side_contracts:
        return None

    def sort_key(contract: OptionContract) -> tuple[float, float, float, float, float]:
        distance = _atm_distance_pct(contract, underlying)
        abs_delta = abs(contract.delta)
        delta_gap = abs(abs_delta - 0.50)
        dte_penalty = 0.0 if 2 <= contract.dte <= 21 else 100.0 + min(abs(contract.dte - 7), 60)
        liquidity = contract.volume + contract.open_interest * 0.08
        return (dte_penalty, distance, delta_gap, contract.spread_pct, -liquidity)

    return sorted(side_contracts, key=sort_key)[0]


def _build_atm_alert_record(
    underlying: UnderlyingSnapshot,
    contract: OptionContract,
    *,
    data_quality: str,
    source_type: str,
    signal_profile: dict[str, Any],
) -> dict[str, Any]:
    contract_payload = _contract_payload(contract, underlying, data_quality=data_quality)
    contract_score = score_contract(contract, underlying)
    model_lens = _atm_model_lens_summary(contract, underlying, contract_payload, contract_score)
    components = _atm_alert_components(contract, underlying, model_lens)
    alert_score = round(sum(components.values()), 1)
    alert_level = _atm_alert_level(contract, underlying, alert_score, model_lens, signal_profile)
    reasons = _atm_alert_reasons(underlying, contract, alert_score, model_lens)
    warnings = _atm_alert_warnings(underlying, contract, model_lens, contract_score, signal_profile)
    checklist = _atm_manual_checklist(alert_level, signal_profile)
    return {
        "symbol": underlying.symbol,
        "name": underlying.name,
        "side": contract.option_type,
        "option_symbol": contract.option_symbol,
        "strike": contract.strike,
        "expiration": contract.expiration,
        "dte": contract.dte,
        "moneyness": contract_payload.get("moneyness"),
        "moneyness_pct": _atm_distance_pct(contract, underlying),
        "delta": contract.delta,
        "mid": contract.mid,
        "bid": contract.bid,
        "ask": contract.ask,
        "spread_pct": contract.spread_pct,
        "volume": contract.volume,
        "open_interest": contract.open_interest,
        "implied_volatility": contract.implied_volatility,
        "underlying_price": underlying.price,
        "underlying_trend": underlying.trend,
        "underlying_momentum_score": underlying.momentum_score,
        "underlying_relative_volume": underlying.relative_volume,
        "scan_rank": underlying.scan_rank,
        "alert_score": alert_score,
        "alert_level": alert_level,
        "alert_components": components,
        "alert_reasons": reasons,
        "why_now": reasons,
        "risk_warnings": warnings,
        "manual_checklist": checklist,
        "contract_score": {
            "recommendation": contract_score.get("recommendation"),
            "total_score": contract_score.get("total_score"),
            "blockers": contract_score.get("blockers", []),
        },
        "model_lens_summary": model_lens,
        "manual_trade_notes": checklist,
        "data_quality": data_quality,
        "source_type": source_type,
        "profile": signal_profile["profile_id"],
        "safety": _safety_payload(),
    }


def _atm_model_lens_summary(
    contract: OptionContract,
    underlying: UnderlyingSnapshot,
    contract_payload: dict[str, Any],
    contract_score: dict[str, Any],
) -> dict[str, Any]:
    model = _build_model_surface(
        contract=contract_payload,
        underlying=underlying.to_payload(),
        price_steps=7,
        iv_steps=5,
    )
    lens = _build_model_decision_lens(
        model=model,
        contract=contract,
        underlying=underlying.to_payload(),
        score=contract_score,
    )
    metrics = lens.get("metrics") or {}
    prediction = lens.get("prediction") or {}
    return {
        "decision": lens.get("decision"),
        "confidence": lens.get("confidence"),
        "expected_pnl_per_contract": metrics.get("expected_pnl_per_contract"),
        "model_edge_pct_of_premium": metrics.get("model_edge_pct_of_premium"),
        "profit_scenario_weight_pct": metrics.get("profit_scenario_weight_pct"),
        "downside_p10_pnl_per_contract": metrics.get("downside_p10_pnl_per_contract"),
        "upside_p90_pnl_per_contract": metrics.get("upside_p90_pnl_per_contract"),
        "expected_move_pct": prediction.get("expected_move_pct"),
        "expected_underlying_price": prediction.get("expected_underlying_price"),
        "buy_blockers": list(lens.get("buy_blockers") or [])[:5],
        "explanation": lens.get("explanation"),
    }


def _atm_alert_components(
    contract: OptionContract,
    underlying: UnderlyingSnapshot,
    model_lens: dict[str, Any],
) -> dict[str, float]:
    distance = _atm_distance_pct(contract, underlying)
    abs_delta = abs(contract.delta)
    stock_setup = min(22.0, underlying.momentum_score * 0.16 + min(max(underlying.relative_volume, 0.0), 2.5) * 1.8)
    if _preferred_option_type(underlying) == contract.option_type:
        stock_setup += 2.0
    distance_score = 10.0 if distance <= 0.25 else 8.0 if distance <= 0.50 else 6.0 if distance <= 1.0 else 3.0 if distance <= 2.0 else 0.0
    delta_score = 8.0 if abs(abs_delta - 0.50) <= 0.05 else 6.0 if 0.40 <= abs_delta <= 0.60 else 3.0 if 0.30 <= abs_delta <= 0.70 else 0.0
    dte_score = 10.0 if 7 <= contract.dte <= 14 else 8.0 if 2 <= contract.dte <= 21 else 4.0 if 22 <= contract.dte <= 35 else 1.0
    liquidity = _liquidity_score(contract) * 0.50 + _spread_score(contract) * 0.50
    iv_event = _iv_score(contract, underlying) * 0.70 + _event_score(contract) * 0.45
    model_score = 0.0
    decision = str(model_lens.get("decision") or "")
    expected_pnl = _to_float(model_lens.get("expected_pnl_per_contract")) or 0.0
    profit_weight = _to_float(model_lens.get("profit_scenario_weight_pct")) or 0.0
    edge_pct = _to_float(model_lens.get("model_edge_pct_of_premium")) or 0.0
    if decision == "BUY CANDIDATE":
        model_score += 7.0
    elif decision == "WATCH":
        model_score += 4.0
    if expected_pnl > 0:
        model_score += min(expected_pnl / 75.0, 1.0) * 3.0
    if profit_weight >= 55:
        model_score += 3.0
    elif profit_weight >= 45:
        model_score += 1.5
    if edge_pct > 0:
        model_score += min(edge_pct / 15.0, 1.0) * 2.0
    return {
        "stock_setup": round(min(stock_setup, 22.0), 1),
        "atm_fit": round(distance_score + delta_score, 1),
        "dte": round(dte_score, 1),
        "liquidity_spread": round(min(liquidity, 20.0), 1),
        "iv_event": round(min(iv_event, 15.0), 1),
        "model_lens": round(min(model_score, 15.0), 1),
    }


def _atm_alert_level(
    contract: OptionContract,
    underlying: UnderlyingSnapshot,
    alert_score: float,
    model_lens: dict[str, Any],
    signal_profile: dict[str, Any],
) -> str:
    distance = _atm_distance_pct(contract, underlying)
    abs_delta = abs(contract.delta)
    dte_min, dte_max = signal_profile["dte_window"]
    delta_min, delta_max = signal_profile["delta_band"]
    dte_ok = dte_min <= contract.dte <= dte_max
    atm_ok = distance <= signal_profile["atm_moneyness_pct"] and delta_min <= abs_delta <= delta_max
    liquid_ok = (
        contract.spread_pct <= signal_profile["max_alert_spread_pct"]
        and contract.volume >= signal_profile["min_alert_volume"]
        and contract.open_interest >= signal_profile["min_alert_open_interest"]
    )
    model_ok = model_lens.get("decision") != "AVOID"
    if alert_score >= signal_profile["alert_score_threshold"] and dte_ok and atm_ok and liquid_ok and model_ok:
        return ATM_ALERT
    if alert_score >= signal_profile["watch_score_threshold"] and dte_ok and distance <= signal_profile["watch_moneyness_pct"]:
        return ATM_WATCH
    return ATM_PASS


def _atm_alert_reasons(
    underlying: UnderlyingSnapshot,
    contract: OptionContract,
    alert_score: float,
    model_lens: dict[str, Any],
) -> list[str]:
    return [
        f"{underlying.symbol} {underlying.trend} with momentum {underlying.momentum_score:.1f} and relative volume {underlying.relative_volume:.2f}.",
        f"{contract.option_type.upper()} is nearest ATM: strike {contract.strike:.2f}, distance {_atm_distance_pct(contract, underlying):.2f}%, delta {contract.delta:.2f}.",
        f"Liquidity check: volume {contract.volume}, OI {contract.open_interest}, spread {contract.spread_pct:.2f}%.",
        f"3D lens: {model_lens.get('decision', 'WATCH')} / expected PnL {model_lens.get('expected_pnl_per_contract', '-')}.",
        f"ATM alert score {alert_score:.1f}/100 for manual review.",
    ]


def _atm_alert_warnings(
    underlying: UnderlyingSnapshot,
    contract: OptionContract,
    model_lens: dict[str, Any],
    contract_score: dict[str, Any],
    signal_profile: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    distance = _atm_distance_pct(contract, underlying)
    abs_delta = abs(contract.delta)
    dte_min, dte_max = signal_profile["dte_window"]
    delta_min, delta_max = signal_profile["delta_band"]
    if distance > signal_profile["atm_moneyness_pct"]:
        warnings.append(f"Not inside strict ATM band: distance is {distance:.2f}%.")
    if abs_delta < delta_min or abs_delta > delta_max:
        warnings.append(f"Delta {contract.delta:.2f} is outside ATM target band {delta_min:.2f}-{delta_max:.2f}.")
    if contract.dte < dte_min or contract.dte > dte_max:
        warnings.append(f"DTE {contract.dte} is outside manual ATM window {dte_min}-{dte_max}.")
    if contract.spread_pct > signal_profile["max_alert_spread_pct"]:
        warnings.append(f"Spread {contract.spread_pct:.2f}% is above strict limit {signal_profile['max_alert_spread_pct']:.2f}%.")
    if contract.volume < signal_profile["min_alert_volume"] or contract.open_interest < signal_profile["min_alert_open_interest"]:
        warnings.append(
            f"Volume/OI is below strict floor {signal_profile['min_alert_volume']}/"
            f"{signal_profile['min_alert_open_interest']}."
        )
    if contract.implied_volatility > 0.75 or underlying.iv_rank > 0.80:
        warnings.append("IV is elevated; watch volatility crush risk.")
    if contract.event_risk == "high":
        warnings.append("Event risk is high.")
    if model_lens.get("decision") == "AVOID":
        warnings.append("3D Buy Lens is AVOID.")
    for blocker in list(contract_score.get("blockers") or [])[:3]:
        if blocker not in warnings:
            warnings.append(str(blocker))
    return warnings


def _atm_manual_checklist(alert_level: str, signal_profile: dict[str, Any]) -> list[str]:
    return [
        "Read-only ATM option alert; this is not an order instruction.",
        "Confirm the stock K-Line trend first: 1Y/1D context, then 5D/15m intraday structure.",
        "Confirm the option K-Line, bid/ask spread, volume, and open interest before any manual trade.",
        "Open 3D Buy Lens for scenario review and check expected PnL, profit weight, and downside P10.",
        f"Use {signal_profile['profile_id']} discipline: act only outside kquant, with your own manual order decision.",
    ]


def _atm_alert_summary(alerts: list[dict[str, Any]], signal_profile: dict[str, Any]) -> dict[str, Any]:
    counts = {
        ATM_ALERT: sum(1 for item in alerts if item.get("alert_level") == ATM_ALERT),
        ATM_WATCH: sum(1 for item in alerts if item.get("alert_level") == ATM_WATCH),
        ATM_PASS: sum(1 for item in alerts if item.get("alert_level") == ATM_PASS),
    }
    overall = ATM_ALERT if counts[ATM_ALERT] else ATM_WATCH if counts[ATM_WATCH] else ATM_PASS
    top = alerts[0] if alerts else None
    return {
        "overall_alert_level": overall,
        "total_alerts": len(alerts),
        "high_priority_count": counts[ATM_ALERT],
        "watch_count": counts[ATM_WATCH],
        "pass_count": counts[ATM_PASS],
        "top_symbol": top.get("symbol") if top else None,
        "top_option_symbol": top.get("option_symbol") if top else None,
        "top_score": top.get("alert_score") if top else None,
        "alert_channel": signal_profile["default_alert_channel"],
        "profile": signal_profile["profile_id"],
        "alert_score_threshold": signal_profile["alert_score_threshold"],
        "watch_score_threshold": signal_profile["watch_score_threshold"],
    }


def _atm_alert_run_id(generated_at: str, universe: str, selected: list[str], source_type: str, signal_profile: dict[str, Any]) -> str:
    cleaned_time = re.sub(r"[^0-9A-Za-z]", "", generated_at)[:18] or "now"
    universe_part = re.sub(r"[^0-9A-Za-z_-]", "", universe or "default")[:16] or "default"
    source_part = "fixture" if source_type == "fixture_read_only" else "live"
    return f"atm-{signal_profile['profile_id']}-{universe_part}-{source_part}-{len(selected)}-{cleaned_time}"


def _atm_alert_sort_key(alert: dict[str, Any]) -> tuple[int, float, int, str]:
    level_rank = {ATM_ALERT: 0, ATM_WATCH: 1, ATM_PASS: 2}.get(str(alert.get("alert_level")), 3)
    scan_rank = int(alert.get("scan_rank") or 999)
    return (level_rank, -float(alert.get("alert_score") or 0.0), scan_rank, str(alert.get("option_symbol") or ""))


def _atm_distance_pct(contract: OptionContract, underlying: UnderlyingSnapshot) -> float:
    if not underlying.price:
        return 999.0
    return round(abs(contract.strike - underlying.price) / underlying.price * 100.0, 2)


def _atm_alert_limitations(source_type: str) -> list[str]:
    source_note = (
        "Fixture mode uses deterministic read-only ATM alerts for offline demos."
        if source_type == "fixture_read_only"
        else "Live mode uses public Yahoo chart data and public Nasdaq option-chain data when available."
    )
    return [
        source_note,
        "ATM alerts are manual research prompts, not buy orders or broker instructions.",
        "The v1 ATM profile excludes 0DTE and multi-leg strategies.",
        "No broker key is read, no account state is fetched, and no order endpoint is used by this workflow.",
    ]


def _render_atm_alerts_markdown(payload: dict[str, Any]) -> str:
    provider_errors = payload.get("provider_errors") or []
    summary = payload.get("alert_summary") or {}
    signal_profile = payload.get("atm_signal_profile") or {}
    live_health = payload.get("live_data_health") if isinstance(payload.get("live_data_health"), dict) else {}
    pilot = payload.get("live_pilot_review") if isinstance(payload.get("live_pilot_review"), dict) else {}
    pilot_status = payload.get("live_pilot_status") if isinstance(payload.get("live_pilot_status"), dict) else {}
    llm_policy = payload.get("llm_policy") if isinstance(payload.get("llm_policy"), dict) else _llm_policy_payload()
    alerts = payload.get("atm_alerts") or []
    top_alerts = [item for item in alerts if item.get("alert_level") == ATM_ALERT]
    watch_alerts = [item for item in alerts if item.get("alert_level") == ATM_WATCH]
    pass_alerts = [item for item in alerts if item.get("alert_level") == ATM_PASS]
    lines = [
        "# ATM Options Daily Signal Report",
        "",
        f"- Run ID: `{payload.get('run_id', '-')}`",
        f"- Generated: `{payload.get('generated_at', '-')}`",
        f"- Source: `{payload.get('source_type', '-')}`",
        f"- Strategy: `{payload.get('strategy_id', '-')}`",
        f"- Profile: `{payload.get('profile_id') or payload.get('profile') or '-'}`",
        f"- Overall: `{payload.get('overall_alert_level', '-')}`",
        f"- Alert channel: `{summary.get('alert_channel', '-')}`",
        "",
        "## Daily Alert Summary",
        "",
        f"- Total alerts: `{summary.get('total_alerts', 0)}`",
        f"- ATM ALERT: `{summary.get('high_priority_count', 0)}`",
        f"- WATCH: `{summary.get('watch_count', 0)}`",
        f"- PASS: `{summary.get('pass_count', 0)}`",
        f"- Top: `{summary.get('top_symbol') or '-'} / {summary.get('top_option_symbol') or '-'}`",
        f"- Strict thresholds: score `{signal_profile.get('alert_score_threshold', '-')}`, spread `<= {signal_profile.get('max_alert_spread_pct', '-')}%`, volume/OI `>= {signal_profile.get('min_alert_volume', '-')}/{signal_profile.get('min_alert_open_interest', '-')}`",
        "",
        "## 3-Day Pilot Progress",
        "",
        f"- Market date: `{pilot_status.get('market_date') or pilot.get('market_date', '-')}`",
        f"- Pilot day: `{pilot_status.get('pilot_day', '-')}` / `{pilot_status.get('planned_trading_days', 3)}`",
        f"- Default 50 scan: `{((pilot_status.get('default_scan_status') or {}).get('status', 'pending'))}`",
        f"- AI Watchlist scan: `{((pilot_status.get('ai_scan_status') or {}).get('status', 'pending'))}`",
        f"- Journal reviewed today: `{pilot_status.get('journal_reviewed_count', 0)}`",
        f"- Review steps complete today: `{pilot_status.get('review_step_complete_count', 0)}`",
        "",
        "## Provider Error Summary",
        "",
        f"- Provider errors: `{len(provider_errors)}`",
        f"- Provider 429 errors: `{pilot_status.get('provider_429_count', _provider_429_count(provider_errors))}`",
        f"- Data caution: `{pilot_status.get('data_caution', pilot.get('data_caution', False))}`",
        f"- High confidence allowed: `{pilot_status.get('high_confidence_allowed', pilot.get('high_confidence_allowed', False))}`",
        "",
        "## Journal Coverage",
        "",
        f"- Total journal entries today: `{pilot_status.get('journal_total_count', 0)}`",
        f"- Reviewed / skipped / paper-observed: `{pilot_status.get('journal_reviewed_count', 0)}` / `{pilot_status.get('journal_skipped_count', 0)}` / `{pilot_status.get('journal_paper_observed_count', 0)}`",
        f"- Stock K-Line checked: `{pilot_status.get('journal_stock_kline_checked_count', pilot_status.get('stock_kline_checked_count', 0))}`",
        f"- Option K-Line checked: `{pilot_status.get('journal_option_kline_checked_count', pilot_status.get('option_kline_checked_count', 0))}`",
        f"- 3D Lens checked: `{pilot_status.get('journal_lens_checked_count', pilot_status.get('lens_checked_count', 0))}`",
        "",
        "## LLM / AI Review Policy",
        "",
        f"- LLM signal core enabled: `{llm_policy.get('llm_signal_core_enabled', False)}`",
        f"- External LLM calls enabled: `{llm_policy.get('external_llm_calls_enabled', False)}`",
        f"- Core signal engine: `{llm_policy.get('core_signal_engine', '-')}`",
        f"- AI review assistant: `{llm_policy.get('review_assistant_status', '-')}`",
        "- LLMs must not set alert scores, alert levels, scans, or any broker/order action.",
        "",
        "## LLM Core Locked Policy",
        "",
        "- The signal core remains deterministic and read-only during Live Pilot.",
        "- Future AI review can summarize journal notes only after pilot quality is stable.",
        "",
    ]
    if pilot:
        journal = pilot.get("journal") if isinstance(pilot.get("journal"), dict) else {}
        lines.extend(
            [
                "## Live Pilot Review",
                "",
                f"- Phase: `{pilot.get('phase', '-')}`",
                f"- Market date: `{pilot.get('market_date', '-')}`",
                f"- Planned trading days: `{pilot.get('planned_trading_days', '-')}`",
                f"- Review allowed: `{pilot.get('review_allowed', False)}`",
                f"- High confidence allowed: `{pilot.get('high_confidence_allowed', False)}`",
                f"- Data caution: `{pilot.get('data_caution', False)}`",
                f"- Journal matches: `{journal.get('matching_entry_count', 0)}`",
                "",
            ]
        )
        for reason in pilot.get("data_caution_reasons") or []:
            lines.append(f"- Data caution reason: {reason}")
        if pilot.get("data_caution_reasons"):
            lines.append("")
    if live_health:
        lines.extend(
            [
                "## Live Data Health",
                "",
                f"- Requested symbols: `{live_health.get('requested_symbol_count', '-')}`",
                f"- Successful symbols: `{live_health.get('successful_symbol_count', '-')}`",
                f"- Failed symbols: `{live_health.get('failed_symbol_count', '-')}`",
                f"- Provider degraded: `{live_health.get('provider_degraded', 'unknown')}`",
                f"- Chain symbols checked: `{live_health.get('chain_requested_symbol_count', '-')}`",
                f"- Chain symbols successful: `{live_health.get('chain_successful_symbol_count', '-')}`",
                "",
            ]
        )
    if provider_errors:
        lines.extend(["## Provider Errors", ""])
        for item in provider_errors[:20]:
            lines.append(f"- {item.get('symbol', '-')}/{item.get('provider', '-')}: {item.get('error', '-')}")
        lines.append("")
    lines.extend(["## Top ATM Alerts", ""])
    for item in top_alerts[:12]:
        lines.extend(
            [
                f"### {item.get('symbol', '-')} {str(item.get('side', '-')).upper()} - {item.get('alert_level', '-')}",
                "",
                f"- Contract: `{item.get('option_symbol', '-')}`",
                f"- Score: `{item.get('alert_score', 0):.1f}/100`",
                f"- Strike/DTE/ATM distance: `{item.get('strike', '-')}` / `{item.get('dte', '-')}` / `{item.get('moneyness_pct', '-')}%`",
                f"- Bid/ask/mid/spread: `{item.get('bid', '-')}` / `{item.get('ask', '-')}` / `{item.get('mid', '-')}` / `{item.get('spread_pct', '-')}%`",
                f"- Volume/OI: `{item.get('volume', '-')}` / `{item.get('open_interest', '-')}`",
                f"- 3D lens: `{(item.get('model_lens_summary') or {}).get('decision', '-')}`",
                "",
                "Why Now:",
            ]
        )
        lines.extend([f"- {reason}" for reason in (item.get("why_now") or item.get("alert_reasons") or [])[:5]])
        lines.extend(["", "Risk Warnings:"])
        lines.extend([f"- {warning}" for warning in (item.get("risk_warnings") or ["No primary warning from ATM v1."])[:5]])
        lines.extend(["", "Manual Checklist:"])
        lines.extend([f"- {note}" for note in (item.get("manual_checklist") or item.get("manual_trade_notes") or [])[:5]])
        lines.append("")
    if not top_alerts:
        lines.extend(["No strict ATM ALERT signals were generated from the current provider data.", ""])
    lines.extend(["## Watchlist", ""])
    for item in watch_alerts[:20]:
        warning = (item.get("risk_warnings") or ["manual review required"])[0]
        lines.append(f"- `{item.get('symbol')}` `{item.get('option_symbol')}` score `{item.get('alert_score')}`: {warning}")
    if not watch_alerts:
        lines.append("No WATCH alerts were generated.")
    lines.extend(["", "## Rejected / PASS Reasons", ""])
    for item in pass_alerts[:20]:
        warning = (item.get("risk_warnings") or ["score below strict local threshold"])[0]
        lines.append(f"- `{item.get('symbol')}` `{item.get('option_symbol')}` score `{item.get('alert_score')}`: {warning}")
    if not pass_alerts:
        lines.append("No PASS alerts were generated.")
    lines.extend(["", "## 3D Lens Summary", ""])
    for item in alerts[:20]:
        lens = item.get("model_lens_summary") or {}
        lines.append(
            f"- `{item.get('symbol')}` `{item.get('option_symbol')}`: `{lens.get('decision', '-')}`, "
            f"expected PnL `{lens.get('expected_pnl_per_contract', '-')}`, "
            f"profit weight `{lens.get('profit_scenario_weight_pct', '-')}`, "
            f"downside P10 `{lens.get('downside_p10_pnl_per_contract', '-')}`"
        )
    if not alerts:
        lines.append("No ATM alerts or 3D Lens summaries were generated.")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Signal generation is research-only and cannot auto-submit orders.",
            "- No broker key is read by the signal core.",
            "- Alpaca Paper order APIs are separate, manually confirmed, and audit logged.",
            "- No Testnet or Live order is used.",
            "",
        ]
    )
    return "\n".join(lines)


def _fixture_worthiness_report(selected: list[str], *, universe: str = "default") -> dict[str, Any]:
    snapshots = _underlying_fixtures()
    chains = _contract_fixtures()
    evaluations = []
    selected_snapshots: list[UnderlyingSnapshot] = []
    for symbol in selected:
        if symbol not in snapshots:
            continue
        selected_snapshots.append(snapshots[symbol])
        contracts = chains[symbol]
        scored = [score_contract(contract, snapshots[symbol]) for contract in contracts]
        scored.sort(key=lambda item: item["total_score"], reverse=True)
        best = scored[0] if scored else None
        evaluations.append(
            {
                "symbol": symbol,
                "underlying": snapshots[symbol].to_payload(),
                "preferred_side": _preferred_option_type(snapshots[symbol]),
                "recommendation": best["recommendation"] if best else RECOMMEND_NO_TRADE,
                "best_contract": best,
                "contracts": scored,
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_type": "fixture_read_only",
        "module": "US Options Lab v1",
        "universe": universe,
        "universes": _universe_payload(),
        "frequency_profile": FREQUENCY_PROFILE,
        "symbols": selected,
        "daily_candidates": _daily_candidate_records(
            _rank_underlyings(selected_snapshots),
            [],
            datetime.now(timezone.utc).isoformat(),
            "fixture_read_only",
        ),
        "overall_recommendation": _overall_recommendation(evaluations),
        "evaluations": evaluations,
        "limitations": _limitations("fixture"),
        "safety": _safety_payload(),
    }


def _live_underlying_snapshots(symbols: list[str], *, timeout: float) -> tuple[dict[str, UnderlyingSnapshot], list[dict[str, str]]]:
    snapshots: dict[str, UnderlyingSnapshot] = {}
    errors: list[dict[str, str]] = []
    if not symbols:
        return snapshots, errors

    def fetch_one(symbol: str) -> tuple[str, UnderlyingSnapshot | None, list[dict[str, str]]]:
        symbol_errors: list[dict[str, str]] = []
        try:
            return symbol, _fetch_yahoo_snapshot(symbol, timeout=timeout), symbol_errors
        except Exception as exc:
            try:
                snapshot = _fetch_nasdaq_quote_snapshot(symbol, timeout=timeout)
                symbol_errors.append({"symbol": symbol, "provider": "yahoo_chart", "error": str(exc), "fallback": "nasdaq_quote"})
                return symbol, snapshot, symbol_errors
            except Exception as fallback_exc:
                symbol_errors.append({"symbol": symbol, "provider": "yahoo_chart", "error": str(exc)})
                symbol_errors.append({"symbol": symbol, "provider": "nasdaq_quote", "error": str(fallback_exc)})
                return symbol, None, symbol_errors

    with ThreadPoolExecutor(max_workers=min(max(len(symbols), 1), 8)) as executor:
        futures = [executor.submit(fetch_one, symbol) for symbol in symbols]
        for future in as_completed(futures):
            symbol, snapshot, symbol_errors = future.result()
            if snapshot is not None:
                snapshots[symbol] = snapshot
            errors.extend(symbol_errors)
    return snapshots, errors


def _rank_underlyings(snapshots: list[UnderlyingSnapshot]) -> list[UnderlyingSnapshot]:
    ranked = sorted(snapshots, key=lambda item: (item.momentum_score, abs(item.change_pct), item.relative_volume), reverse=True)
    return [replace(item, scan_rank=index) for index, item in enumerate(ranked, start=1)]


def _fetch_yahoo_snapshot(symbol: str, *, timeout: float) -> UnderlyingSnapshot:
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=5d&interval=1d"
    data = _http_json(url, timeout=timeout)
    result = (data.get("chart", {}).get("result") or [None])[0]
    if not result:
        raise ValueError("Yahoo chart returned no result.")
    meta = result.get("meta") or {}
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = [_to_float(item) for item in quote.get("close") or []]
    closes = [item for item in closes if item is not None and item > 0]
    volumes = [_to_float(item) for item in quote.get("volume") or []]
    volumes = [item for item in volumes if item is not None and item >= 0]
    price = _to_float(meta.get("regularMarketPrice")) or (closes[-1] if closes else None)
    previous = _to_float(meta.get("chartPreviousClose")) or (closes[-2] if len(closes) >= 2 else None)
    if price is None:
        raise ValueError("Yahoo chart returned no usable price.")
    change_pct = round(((price - previous) / previous) * 100, 2) if previous else 0.0
    latest_volume = _to_float(meta.get("regularMarketVolume")) or (volumes[-1] if volumes else 0.0)
    previous_volumes = [item for item in volumes[:-1] if item > 0]
    avg_volume = sum(previous_volumes) / len(previous_volumes) if previous_volumes else latest_volume or 1.0
    relative_volume = round(latest_volume / avg_volume, 2) if avg_volume else 1.0
    realized_vol = _realized_volatility(closes)
    iv_rank = _estimated_iv_rank(realized_vol)
    momentum_score = _momentum_score(change_pct, relative_volume)
    trend = _trend(change_pct, relative_volume, momentum_score)
    timestamp = meta.get("regularMarketTime") or ((result.get("timestamp") or [None])[-1])
    return UnderlyingSnapshot(
        symbol=symbol,
        name=str(meta.get("longName") or meta.get("shortName") or symbol),
        price=round(float(price), 2),
        change_pct=change_pct,
        iv_rank=iv_rank,
        trend=trend,
        data_source="yahoo_chart_public",
        updated_at=_iso_from_epoch(timestamp),
        momentum_score=momentum_score,
        relative_volume=relative_volume,
        theme_tags=_theme_tags(symbol),
        universe_groups=_universe_groups(symbol),
    )


def _fetch_nasdaq_quote_snapshot(symbol: str, *, timeout: float) -> UnderlyingSnapshot:
    asset_class = "etf" if symbol in ETF_SYMBOLS else "stocks"
    url = f"https://api.nasdaq.com/api/quote/{urllib.parse.quote(symbol)}/info?assetclass={asset_class}"
    data = _http_json(url, timeout=timeout, referer=f"https://www.nasdaq.com/market-activity/{asset_class}/{symbol.lower()}")
    quote = data.get("data") or {}
    primary = quote.get("primaryData") or {}
    price = _to_float(primary.get("lastSalePrice"))
    if price is None:
        raise ValueError("Nasdaq quote returned no usable price.")
    change_pct = _to_float(primary.get("percentageChange")) or 0.0
    volume = _to_float(primary.get("volume")) or 0.0
    relative_volume = 1.0
    momentum_score = _momentum_score(change_pct, relative_volume)
    trend = _trend(change_pct, relative_volume, momentum_score)
    return UnderlyingSnapshot(
        symbol=symbol,
        name=str(quote.get("companyName") or symbol),
        price=round(float(price), 2),
        change_pct=round(change_pct, 2),
        iv_rank=0.50,
        trend=trend,
        data_source="nasdaq_quote_public",
        updated_at=str(primary.get("lastTradeTimestamp") or datetime.now(timezone.utc).isoformat()),
        momentum_score=momentum_score,
        relative_volume=relative_volume,
        theme_tags=_theme_tags(symbol),
        universe_groups=_universe_groups(symbol),
    )


def _fetch_live_chain(symbol: str, underlying: UnderlyingSnapshot, *, timeout: float) -> list[OptionContract]:
    asset_class = "etf" if symbol in ETF_SYMBOLS else "stocks"
    url = (
        f"https://api.nasdaq.com/api/quote/{urllib.parse.quote(symbol)}/option-chain"
        f"?assetclass={asset_class}&limit=450"
    )
    data = _http_json(url, timeout=timeout, referer=f"https://www.nasdaq.com/market-activity/{asset_class}/{symbol.lower()}/option-chain")
    rows = (((data.get("data") or {}).get("table") or {}).get("rows") or [])
    if not rows:
        raise ValueError("Nasdaq option chain returned no rows.")
    contracts = _parse_nasdaq_chain(symbol, underlying, rows)
    if not contracts:
        raise ValueError("Nasdaq option chain returned no parseable contracts with bid/ask.")
    return contracts


def _parse_nasdaq_chain(symbol: str, underlying: UnderlyingSnapshot, rows: list[dict[str, Any]]) -> list[OptionContract]:
    contracts: list[OptionContract] = []
    current_expiry_group: str | None = None
    for row in rows:
        if row.get("expirygroup"):
            current_expiry_group = str(row["expirygroup"])
        strike = _to_float(row.get("strike"))
        if strike is None or strike <= 0:
            continue
        expiration = _parse_expiration(row.get("expiryDate"), current_expiry_group)
        if expiration is None:
            continue
        dte = max((expiration - date.today()).days, 0)
        for option_type, prefix in (("call", "c"), ("put", "p")):
            bid = _to_float(row.get(f"{prefix}_Bid"))
            ask = _to_float(row.get(f"{prefix}_Ask"))
            if bid is None or ask is None or ask <= 0 or ask < bid:
                continue
            mid = (bid + ask) / 2
            iv = _implied_volatility(
                market_price=mid,
                spot=underlying.price,
                strike=strike,
                dte=dte,
                option_type=option_type,
            )
            if iv is None:
                continue
            greeks = _black_scholes_greeks(
                spot=underlying.price,
                strike=strike,
                dte=dte,
                sigma=iv,
                option_type=option_type,
            )
            contracts.append(
                OptionContract(
                    option_symbol=_format_option_symbol(symbol, expiration, option_type, strike),
                    underlying=symbol,
                    expiration=expiration.isoformat(),
                    dte=dte,
                    strike=round(strike, 2),
                    option_type=option_type,
                    bid=round(float(bid), 2),
                    ask=round(float(ask), 2),
                    volume=_to_int(row.get(f"{prefix}_Volume")),
                    open_interest=_to_int(row.get(f"{prefix}_Openinterest")),
                    implied_volatility=round(iv, 3),
                    delta=round(greeks["delta"], 3),
                    gamma=round(greeks["gamma"], 4),
                    theta=round(greeks["theta"], 4),
                    vega=round(greeks["vega"], 4),
                    event_risk=_event_risk_for_dte(dte),
                )
            )
    return contracts


def _http_json(url: str, *, timeout: float, referer: str | None = None) -> dict[str, Any]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.nasdaq.com" if "nasdaq.com" in url else "https://finance.yahoo.com",
        "Referer": referer or ("https://www.nasdaq.com/" if "nasdaq.com" in url else "https://finance.yahoo.com/"),
    }
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except Exception:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl._create_unverified_context()) as response:
            return json.load(response)


def _parse_expiration(value: Any, current_group: str | None) -> date | None:
    full_candidates = [item for item in [current_group, value] if item]
    for candidate in full_candidates:
        text = str(candidate).strip()
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%b %d", "%B %d"):
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        year = date.today().year
        if current_group:
            match = re.search(r"(20\d{2})", current_group)
            if match:
                year = int(match.group(1))
        candidate = parsed.replace(year=year)
        if candidate < date.today():
            candidate = candidate.replace(year=year + 1)
        return candidate
    return None


def _format_option_symbol(symbol: str, expiration: date, option_type: str, strike: float) -> str:
    side = "C" if option_type == "call" else "P"
    return f"{symbol}{expiration:%y%m%d}{side}{int(round(strike * 1000)):08d}"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"--", "N/A", "null", "None"}:
        return None
    text = text.replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: Any) -> int:
    parsed = _to_float(value)
    return int(parsed) if parsed is not None else 0


def _iso_from_epoch(value: Any) -> str:
    timestamp = _to_float(value)
    if timestamp is None:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _realized_volatility(closes: list[float]) -> float:
    if len(closes) < 3:
        return 0.30
    returns = []
    for prev, cur in zip(closes, closes[1:]):
        if prev > 0 and cur > 0:
            returns.append(math.log(cur / prev))
    if len(returns) < 2:
        return 0.30
    avg = sum(returns) / len(returns)
    variance = sum((item - avg) ** 2 for item in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(252)


def _estimated_iv_rank(realized_vol: float) -> float:
    return round(min(max((realized_vol - 0.12) / 0.70, 0.0), 1.0), 2)


def _momentum_score(change_pct: float, relative_volume: float) -> float:
    price_component = min(abs(change_pct) / 4.0 * 55.0, 55.0)
    volume_component = min(max(relative_volume - 1.0, 0.0) * 30.0, 30.0)
    direction_component = 15.0 if abs(change_pct) >= 1.0 else (8.0 if abs(change_pct) >= 0.5 else 0.0)
    return round(min(price_component + volume_component + direction_component, 100.0), 1)


def _trend(change_pct: float, relative_volume: float, momentum_score: float) -> str:
    if change_pct >= 0.75 and momentum_score >= 25:
        return "bullish_momentum" if relative_volume >= 1.0 else "bullish_low_volume"
    if change_pct <= -0.75 and momentum_score >= 25:
        return "bearish_momentum" if relative_volume >= 1.0 else "bearish_low_volume"
    return "neutral"


def _preferred_option_type(underlying: UnderlyingSnapshot) -> str | None:
    if underlying.trend.startswith("bullish"):
        return "call"
    if underlying.trend.startswith("bearish"):
        return "put"
    return None


def _build_evaluations(
    underlyings: list[UnderlyingSnapshot],
    chains: dict[str, list[OptionContract]],
) -> list[dict[str, Any]]:
    evaluations: list[dict[str, Any]] = []
    for underlying in underlyings:
        preferred_side = _preferred_option_type(underlying)
        contracts = chains.get(underlying.symbol, [])
        filtered = [contract for contract in contracts if preferred_side is None or contract.option_type == preferred_side]
        if not filtered and contracts:
            filtered = contracts
        scored = [score_contract(contract, underlying) for contract in filtered]
        scored.sort(key=lambda item: item["total_score"], reverse=True)
        best = scored[0] if scored else None
        evaluations.append(
            {
                "symbol": underlying.symbol,
                "underlying": underlying.to_payload(),
                "preferred_side": preferred_side,
                "recommendation": best["recommendation"] if best else RECOMMEND_NO_TRADE,
                "best_contract": best,
                "contracts": scored,
                "scan_reason": _scan_reason(underlying, preferred_side),
            }
        )
    evaluations.sort(
        key=lambda item: (
            _recommendation_rank(item["recommendation"]),
            (item.get("best_contract") or {}).get("total_score", 0),
            item["underlying"].get("momentum_score", 0),
        ),
        reverse=True,
    )
    return evaluations


def _scan_reason(underlying: UnderlyingSnapshot, preferred_side: str | None) -> str:
    side = preferred_side or "two-sided observation"
    return (
        f"{underlying.symbol} rank {underlying.scan_rank}: {underlying.trend}, "
        f"change {underlying.change_pct:.2f}%, relative volume {underlying.relative_volume:.2f}, "
        f"momentum score {underlying.momentum_score:.1f}; preferred side {side}."
    )


def _recommendation_rank(value: str) -> int:
    return {RECOMMEND_TRADE: 3, RECOMMEND_OBSERVE: 2, RECOMMEND_NO_TRADE: 1}.get(value, 0)


def _black_scholes_price(spot: float, strike: float, dte: int, sigma: float, option_type: str, risk_free_rate: float = 0.045) -> float:
    t = max(dte, 1) / 365.0
    if spot <= 0 or strike <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    if option_type == "call":
        return spot * _norm_cdf(d1) - strike * math.exp(-risk_free_rate * t) * _norm_cdf(d2)
    return strike * math.exp(-risk_free_rate * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def _implied_volatility(
    *,
    market_price: float,
    spot: float,
    strike: float,
    dte: int,
    option_type: str,
) -> float | None:
    if market_price <= 0 or spot <= 0 or strike <= 0:
        return None
    low = 0.01
    high = 4.0
    for _ in range(60):
        mid = (low + high) / 2
        price = _black_scholes_price(spot, strike, dte, mid, option_type)
        if abs(price - market_price) < 0.005:
            return mid
        if price > market_price:
            high = mid
        else:
            low = mid
    result = (low + high) / 2
    if result <= 0.011 or result >= 3.99:
        return None
    return result


def _black_scholes_greeks(
    *,
    spot: float,
    strike: float,
    dte: int,
    sigma: float,
    option_type: str,
    risk_free_rate: float = 0.045,
) -> dict[str, float]:
    t = max(dte, 1) / 365.0
    sqrt_t = math.sqrt(t)
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * sigma * sigma) * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    pdf = _norm_pdf(d1)
    gamma = pdf / (spot * sigma * sqrt_t)
    vega = spot * pdf * sqrt_t / 100.0
    if option_type == "call":
        delta = _norm_cdf(d1)
        theta = (
            -(spot * pdf * sigma) / (2 * sqrt_t)
            - risk_free_rate * strike * math.exp(-risk_free_rate * t) * _norm_cdf(d2)
        ) / 365.0
    else:
        delta = _norm_cdf(d1) - 1
        theta = (
            -(spot * pdf * sigma) / (2 * sqrt_t)
            + risk_free_rate * strike * math.exp(-risk_free_rate * t) * _norm_cdf(-d2)
        ) / 365.0
    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _norm_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def _event_risk_for_dte(dte: int) -> str:
    if dte <= 3:
        return "high"
    if dte <= 14:
        return "medium"
    return "low"


def _empty_underlying(symbol: str) -> UnderlyingSnapshot:
    return UnderlyingSnapshot(
        symbol=symbol,
        name=symbol,
        price=0.0,
        change_pct=0.0,
        iv_rank=0.0,
        trend="unavailable",
        data_source="unavailable",
        updated_at=datetime.now(timezone.utc).isoformat(),
        theme_tags=_theme_tags(symbol),
        universe_groups=_universe_groups(symbol),
    )


AI_THEME_TAGS = {
    "NVDA": ("ai_compute", "ai_semis"),
    "AMD": ("ai_compute", "ai_semis"),
    "AVGO": ("ai_infra", "ai_semis"),
    "MSFT": ("ai_cloud", "ai_software"),
    "GOOGL": ("ai_cloud", "ai_software"),
    "META": ("ai_cloud", "ai_software"),
    "AMZN": ("ai_cloud", "ai_infra"),
    "ORCL": ("ai_cloud", "ai_software"),
    "CRM": ("ai_software",),
    "ADBE": ("ai_software",),
    "PLTR": ("ai_software", "ai_infra"),
    "SMCI": ("ai_compute", "ai_infra"),
    "MU": ("ai_semis",),
    "QCOM": ("ai_semis",),
    "INTC": ("ai_semis",),
    "ARM": ("ai_compute", "ai_semis"),
    "MRVL": ("ai_infra", "ai_semis"),
    "TSM": ("ai_semis",),
    "ASML": ("ai_semis",),
    "ANET": ("ai_infra",),
    "DELL": ("ai_compute", "ai_infra"),
    "NOW": ("ai_software",),
    "SNOW": ("ai_software", "ai_cloud"),
    "DDOG": ("ai_infra", "ai_software"),
    "MDB": ("ai_software", "ai_cloud"),
    "CRWD": ("ai_security",),
    "PANW": ("ai_security",),
    "NET": ("ai_security", "ai_infra"),
    "AI": ("ai_software",),
    "PATH": ("ai_software",),
}


def _theme_tags(symbol: str) -> tuple[str, ...]:
    return AI_THEME_TAGS.get(_normalize_symbol(symbol), ())


def _universe_groups(symbol: str) -> tuple[str, ...]:
    normalized = _normalize_symbol(symbol)
    groups = []
    if normalized in DEFAULT_OPTION_SYMBOLS:
        groups.append("default")
    if normalized in AI_OPTION_SYMBOLS:
        groups.append("ai")
    if groups:
        groups.append("all")
    return tuple(groups)


OPTION_FIXTURE_PROFILES: list[tuple[str, str, float]] = [
    ("SPY", "SPDR S&P 500 ETF Trust", 542.18),
    ("QQQ", "Invesco QQQ Trust", 462.74),
    ("IWM", "iShares Russell 2000 ETF", 203.62),
    ("DIA", "SPDR Dow Jones Industrial Average ETF", 392.45),
    ("AAPL", "Apple Inc.", 214.31),
    ("MSFT", "Microsoft Corp.", 451.22),
    ("NVDA", "NVIDIA Corp.", 128.76),
    ("TSLA", "Tesla Inc.", 184.25),
    ("AMZN", "Amazon.com Inc.", 188.42),
    ("META", "Meta Platforms Inc.", 506.81),
    ("GOOGL", "Alphabet Inc.", 176.64),
    ("AMD", "Advanced Micro Devices Inc.", 153.37),
    ("AVGO", "Broadcom Inc.", 173.25),
    ("NFLX", "Netflix Inc.", 655.18),
    ("COST", "Costco Wholesale Corp.", 851.72),
    ("JPM", "JPMorgan Chase & Co.", 205.14),
    ("BAC", "Bank of America Corp.", 39.48),
    ("WFC", "Wells Fargo & Co.", 58.91),
    ("GS", "Goldman Sachs Group Inc.", 462.2),
    ("MS", "Morgan Stanley", 99.64),
    ("XOM", "Exxon Mobil Corp.", 113.82),
    ("CVX", "Chevron Corp.", 156.44),
    ("COP", "ConocoPhillips", 111.58),
    ("UNH", "UnitedHealth Group Inc.", 507.38),
    ("LLY", "Eli Lilly and Co.", 883.6),
    ("MRK", "Merck & Co. Inc.", 128.42),
    ("JNJ", "Johnson & Johnson", 148.18),
    ("ABBV", "AbbVie Inc.", 171.37),
    ("HD", "Home Depot Inc.", 338.2),
    ("WMT", "Walmart Inc.", 68.74),
    ("MCD", "McDonald's Corp.", 260.41),
    ("NKE", "Nike Inc.", 94.62),
    ("BA", "Boeing Co.", 181.48),
    ("CAT", "Caterpillar Inc.", 329.55),
    ("GE", "GE Aerospace", 161.7),
    ("DIS", "Walt Disney Co.", 101.86),
    ("T", "AT&T Inc.", 18.62),
    ("V", "Visa Inc.", 276.74),
    ("MA", "Mastercard Inc.", 452.68),
    ("CRM", "Salesforce Inc.", 245.93),
    ("ORCL", "Oracle Corp.", 124.52),
    ("ADBE", "Adobe Inc.", 468.34),
    ("INTC", "Intel Corp.", 31.42),
    ("MU", "Micron Technology Inc.", 132.81),
    ("QCOM", "Qualcomm Inc.", 203.18),
    ("SMCI", "Super Micro Computer Inc.", 816.92),
    ("PLTR", "Palantir Technologies Inc.", 24.76),
    ("COIN", "Coinbase Global Inc.", 238.14),
    ("SHOP", "Shopify Inc.", 66.58),
    ("UBER", "Uber Technologies Inc.", 71.34),
    ("ARM", "Arm Holdings plc", 145.4),
    ("MRVL", "Marvell Technology Inc.", 74.32),
    ("TSM", "Taiwan Semiconductor Manufacturing Co.", 169.8),
    ("ASML", "ASML Holding N.V.", 944.26),
    ("ANET", "Arista Networks Inc.", 318.74),
    ("DELL", "Dell Technologies Inc.", 137.42),
    ("NOW", "ServiceNow Inc.", 742.66),
    ("SNOW", "Snowflake Inc.", 134.85),
    ("DDOG", "Datadog Inc.", 119.36),
    ("MDB", "MongoDB Inc.", 241.55),
    ("CRWD", "CrowdStrike Holdings Inc.", 372.6),
    ("PANW", "Palo Alto Networks Inc.", 315.7),
    ("NET", "Cloudflare Inc.", 82.14),
    ("AI", "C3.ai Inc.", 27.38),
    ("PATH", "UiPath Inc.", 12.84),
]


def _underlying_fixtures() -> dict[str, UnderlyingSnapshot]:
    now = datetime.now(timezone.utc).isoformat()
    snapshots: dict[str, UnderlyingSnapshot] = {}
    for index, (symbol, name, price) in enumerate(OPTION_FIXTURE_PROFILES, start=1):
        if symbol == "SPY":
            change_pct, iv_rank, momentum_score, relative_volume, trend = -0.42, 0.38, 24.0, 1.08, "bearish-to-neutral"
        elif symbol == "QQQ":
            change_pct, iv_rank, momentum_score, relative_volume, trend = -0.76, 0.52, 36.0, 1.18, "bearish"
        else:
            cycle = ((index * 7) % 21) - 10
            change_pct = round(cycle * 0.18, 2)
            relative_volume = round(0.82 + ((index * 5) % 13) * 0.055, 2)
            iv_rank = round(0.24 + ((index * 3) % 17) * 0.027, 2)
            momentum_score = _momentum_score(change_pct, relative_volume)
            trend = _trend(change_pct, relative_volume, momentum_score)
        snapshots[symbol] = UnderlyingSnapshot(
            symbol=symbol,
            name=name,
            price=price,
            change_pct=change_pct,
            iv_rank=iv_rank,
            trend=trend,
            data_source="fixture_read_only",
            updated_at=now,
            momentum_score=momentum_score,
            relative_volume=relative_volume,
            scan_rank=index,
            theme_tags=_theme_tags(symbol),
            universe_groups=_universe_groups(symbol),
        )
    return snapshots


def _contract_fixtures() -> dict[str, list[OptionContract]]:
    snapshots = _underlying_fixtures()
    fixtures = {symbol: _synthetic_fixture_contracts(snapshot) for symbol, snapshot in snapshots.items()}
    fixtures["SPY"] = [
        OptionContract("SPY260717P00535000", "SPY", "2026-07-17", 35, 535.0, "put", 6.1, 6.32, 28400, 122000, 0.236, -0.42, 0.018, -0.072, 0.82, "medium"),
        OptionContract("SPY260717P00525000", "SPY", "2026-07-17", 35, 525.0, "put", 3.92, 4.08, 19100, 90400, 0.248, -0.31, 0.015, -0.061, 0.74, "medium"),
        OptionContract("SPY260717C00550000", "SPY", "2026-07-17", 35, 550.0, "call", 5.35, 5.65, 14800, 73200, 0.221, 0.39, 0.017, -0.068, 0.79, "medium"),
        *fixtures["SPY"][:4],
    ]
    fixtures["QQQ"] = [
        OptionContract("QQQ260717P00455000", "QQQ", "2026-07-17", 35, 455.0, "put", 7.65, 8.35, 7200, 33200, 0.312, -0.44, 0.022, -0.096, 0.69, "medium"),
        OptionContract("QQQ260626P00450000", "QQQ", "2026-06-26", 14, 450.0, "put", 3.8, 4.35, 3100, 18500, 0.344, -0.33, 0.026, -0.119, 0.42, "high"),
        OptionContract("QQQ260717C00475000", "QQQ", "2026-07-17", 35, 475.0, "call", 6.9, 7.55, 4200, 21400, 0.301, 0.38, 0.021, -0.101, 0.66, "medium"),
        *fixtures["QQQ"][:4],
    ]
    return fixtures


def _synthetic_fixture_contracts(underlying: UnderlyingSnapshot) -> list[OptionContract]:
    expirations = [("2026-06-26", 14), ("2026-07-17", 35)]
    strikes = sorted({_round_strike(underlying.price * factor) for factor in (0.94, 0.98, 1.0, 1.02, 1.06)})
    contracts: list[OptionContract] = []
    for expiration, dte in expirations:
        for strike in strikes:
            for option_type in ("call", "put"):
                contracts.append(_synthetic_fixture_contract(underlying, expiration, dte, strike, option_type))
    contracts.sort(key=lambda item: (item.dte, abs(item.strike - underlying.price), item.option_type))
    return contracts


def _synthetic_fixture_contract(
    underlying: UnderlyingSnapshot,
    expiration: str,
    dte: int,
    strike: float,
    option_type: str,
) -> OptionContract:
    distance = (strike - underlying.price) / max(underlying.price, 0.01)
    abs_distance = abs(distance)
    base_iv = round(min(max(0.18 + underlying.iv_rank * 0.28 + abs_distance * 0.6, 0.12), 0.78), 3)
    time_value = underlying.price * base_iv * math.sqrt(max(dte, 1) / 365) * (0.18 + max(0.0, 0.05 - abs_distance))
    intrinsic = max(underlying.price - strike, 0.0) if option_type == "call" else max(strike - underlying.price, 0.0)
    mid = max(intrinsic + time_value, 0.28)
    spread = max(min(mid * 0.055, 0.75), 0.04)
    bid = round(max(mid - spread / 2, 0.01), 2)
    ask = round(max(mid + spread / 2, bid + 0.01), 2)
    delta_raw = 0.46 + distance * 3.8 if option_type == "put" else 0.46 - distance * 3.8
    delta_base = max(0.18, min(0.72, delta_raw))
    delta = -delta_base if option_type == "put" else delta_base
    liquidity_seed = ALL_OPTION_SYMBOLS.index(underlying.symbol) + 1 if underlying.symbol in ALL_OPTION_SYMBOLS else 10
    volume = int(max(450, 18000 / (1 + abs_distance * 18) + liquidity_seed * 57))
    open_interest = int(max(2500, volume * (4.4 + (liquidity_seed % 5) * 0.45)))
    event_risk = "high" if underlying.symbol in {"TSLA", "NVDA", "SMCI", "COIN", "ARM", "AI", "SNOW"} and dte <= 14 else "medium"
    return OptionContract(
        _option_symbol(underlying.symbol, expiration, option_type, strike),
        underlying.symbol,
        expiration,
        dte,
        strike,
        option_type,
        bid,
        ask,
        volume,
        open_interest,
        base_iv,
        round(delta, 3),
        round(0.012 + base_iv * 0.028, 4),
        round(-max(mid * 0.012, 0.015), 3),
        round(max(0.08, underlying.price * 0.0012), 3),
        event_risk,
    )


def _round_strike(value: float) -> float:
    step = 10.0 if value >= 700 else 5.0 if value >= 80 else 2.5 if value >= 25 else 1.0
    return round(round(value / step) * step, 2)


def _option_symbol(symbol: str, expiration: str, option_type: str, strike: float) -> str:
    expiry = datetime.strptime(expiration, "%Y-%m-%d").strftime("%y%m%d")
    side = "C" if option_type == "call" else "P"
    return f"{symbol}{expiry}{side}{int(round(strike * 1000)):08d}"


def _liquidity_score(contract: OptionContract) -> float:
    if contract.volume >= 10000 and contract.open_interest >= 50000:
        return 20.0
    if contract.volume >= 5000 and contract.open_interest >= 20000:
        return 16.0
    if contract.volume >= 1000 and contract.open_interest >= 10000:
        return 12.0
    return 6.0


def _spread_score(contract: OptionContract) -> float:
    if contract.spread_pct <= 5:
        return 20.0
    if contract.spread_pct <= 8:
        return 16.0
    if contract.spread_pct <= 12:
        return 10.0
    return 4.0


def _dte_score(contract: OptionContract) -> float:
    if 7 <= contract.dte <= 45:
        return 10.0
    if 2 <= contract.dte <= 60:
        return 7.0
    return 3.0


def _greeks_score(contract: OptionContract) -> float:
    score = 0.0
    abs_delta = abs(contract.delta)
    if 0.30 <= abs_delta <= 0.50:
        score += 8.0
    elif 0.20 <= abs_delta <= 0.65:
        score += 5.0
    theta_drag = abs(contract.theta) / max(contract.mid, 0.01)
    if theta_drag <= 0.025:
        score += 5.0
    elif theta_drag <= 0.04:
        score += 3.0
    if contract.gamma <= 0.035:
        score += 2.0
    return score


def _iv_score(contract: OptionContract, underlying: UnderlyingSnapshot) -> float:
    if 0.18 <= contract.implied_volatility <= 0.45 and underlying.iv_rank <= 0.60:
        return 15.0
    if contract.implied_volatility <= 0.65 and underlying.iv_rank <= 0.80:
        return 10.0
    return 4.0


def _event_score(contract: OptionContract) -> float:
    return {"low": 10.0, "medium": 6.0, "high": 2.0}.get(contract.event_risk, 2.0)


def _risk_reward_score(contract: OptionContract) -> float:
    if 1.0 <= contract.mid <= 8.0 and abs(contract.delta) >= 0.30:
        return 10.0
    if 0.4 <= contract.mid <= 12.0:
        return 7.0
    return 3.0


def _contract_recommendation(total: float, blockers: list[str]) -> str:
    if not blockers and total >= 85:
        return RECOMMEND_TRADE
    if total >= 65 and len(blockers) <= 2:
        return RECOMMEND_OBSERVE
    return RECOMMEND_NO_TRADE


def _overall_recommendation(evaluations: list[dict[str, Any]]) -> str:
    recommendations = {item["recommendation"] for item in evaluations}
    if RECOMMEND_TRADE in recommendations:
        return RECOMMEND_TRADE
    if RECOMMEND_OBSERVE in recommendations:
        return RECOMMEND_OBSERVE
    return RECOMMEND_NO_TRADE


def _agent_note(recommendation: str, blockers: list[str]) -> str:
    if recommendation == RECOMMEND_TRADE:
        return "Read-only setup passes v1 filters; broker execution is not wired and Live remains locked."
    if recommendation == RECOMMEND_OBSERVE:
        return "Worth monitoring, but v1 does not authorize an options trade."
    return "Do not trade this setup under v1 filters."


def _limitations(source: str) -> list[str]:
    if source == "fixture":
        return [
            "Options Lab fixture mode uses deterministic read-only sample data for tests and offline demos.",
            "No broker key is read, no order endpoint is wired, and Live remains locked.",
            "Trade worthiness is a research filter, not permission to trade.",
        ]
    return [
        "Live mode reads public Yahoo chart data and public Nasdaq option-chain data when available.",
        "Greeks and implied volatility are local Black-Scholes estimates from public bid/ask/mid prices.",
        "Signal generation reads no broker key, fetches no broker account state, and cannot auto-submit orders.",
        "Manual Alpaca Paper order APIs are separately gated by contract detail, journal checklist, limit price, and explicit confirmation.",
        "Live order submission is not wired.",
        "Trade worthiness is a research filter for Agent review, not permission to trade.",
    ]


def _safety_payload() -> dict[str, Any]:
    return {
        "broker_key_required": False,
        "broker_trading_key_required": False,
        "order_submission_wired": False,
        "manual_alpaca_paper_api_available": True,
        "paper_order_submission_wired": True,
        "paper_order_requires_manual_confirmation": True,
        "live_locked": True,
        "live_order_submission_enabled": False,
        "llm_signal_core_enabled": False,
        "external_llm_calls_enabled": False,
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    freshness = payload.get("freshness") if isinstance(payload.get("freshness"), dict) else {}
    provider = payload.get("provider_status") if isinstance(payload.get("provider_status"), dict) else {}
    provider_errors = payload.get("provider_errors") or provider.get("provider_errors") or []
    live_health = payload.get("live_data_health") if isinstance(payload.get("live_data_health"), dict) else {}
    lines = [
        "# US Options Trade Worthiness Report",
        "",
        f"- Generated: `{payload.get('generated_at', '-')}`",
        f"- Source: `{payload.get('source_type', '-')}`",
        f"- Overall: `{payload.get('overall_recommendation', '-')}`",
        f"- Snapshot: `{payload.get('snapshot_id', 'not attached')}`",
        "",
        "## Data Freshness / Provider Status",
        "",
        f"- Fresh: `{freshness.get('is_fresh', 'unknown')}`",
        f"- Age seconds: `{freshness.get('age_seconds', '-')}`",
        f"- Provider available: `{provider.get('provider_available', 'unknown')}`",
        f"- Provider error count: `{provider.get('provider_error_count', len(provider_errors))}`",
        f"- Decision data available: `{provider.get('decision_available', bool(payload.get('evaluations')))}`",
        "",
    ]
    if live_health:
        lines.extend(
            [
                "## Live Data Health",
                "",
                f"- Requested symbols: `{live_health.get('requested_symbol_count', '-')}`",
                f"- Successful symbols: `{live_health.get('successful_symbol_count', '-')}`",
                f"- Failed symbols: `{live_health.get('failed_symbol_count', '-')}`",
                f"- Provider degraded: `{live_health.get('provider_degraded', 'unknown')}`",
                f"- Chain symbols checked: `{live_health.get('chain_requested_symbol_count', '-')}`",
                f"- Chain symbols successful: `{live_health.get('chain_successful_symbol_count', '-')}`",
                f"- Frequency profile: `{FREQUENCY_PROFILE['label']}`",
                "",
            ]
        )
        failed_symbols = live_health.get("failed_symbols") or []
        if failed_symbols:
            lines.extend([f"- Failed symbol list: `{', '.join(failed_symbols[:20])}`", ""])
    scanner = payload.get("scanner")
    if scanner:
        lines.extend(["## Scanner", "", "```json", json.dumps(scanner, indent=2, ensure_ascii=False), "```", ""])
    if provider_errors:
        lines.extend(["## Provider Errors", ""])
        for item in provider_errors:
            lines.append(f"- {item.get('symbol', '-')}/{item.get('provider', '-')}: {item.get('error', '-')}")
        lines.append("")
    lines.extend(["## Evaluations", ""])
    for item in payload.get("evaluations") or []:
        best = item.get("best_contract") or {}
        contract = best.get("contract") or {}
        lines.extend(
            [
                f"### {item['symbol']} - {item['recommendation']}",
                "",
                f"- Scan reason: {item.get('scan_reason', '-')}",
                f"- Best contract: `{best.get('option_symbol', '-')}`",
                f"- Score: `{best.get('total_score', 0):.1f}/100`",
                f"- Type/strike/DTE: `{contract.get('option_type', '-')}` `{contract.get('strike', '-')}` / `{contract.get('dte', '-')}`",
                f"- Bid/ask/mid/spread: `{contract.get('bid', '-')}` / `{contract.get('ask', '-')}` / `{contract.get('mid', '-')}` / `{contract.get('spread_pct', '-')}%`",
                f"- IV/delta/theta: `{contract.get('implied_volatility', '-')}` / `{contract.get('delta', '-')}` / `{contract.get('theta', '-')}`",
                f"- Agent note: {best.get('agent_note', '-')}",
                "",
            ]
        )
        blockers = best.get("blockers") or []
        if blockers:
            lines.append("Blockers:")
            lines.extend(f"- {blocker}" for blocker in blockers)
            lines.append("")
    lines.extend(["## Safety", "", "```json", json.dumps(payload.get("safety") or {}, indent=2, ensure_ascii=False), "```", ""])
    lines.extend(["## Limitations", ""])
    lines.extend(f"- {item}" for item in payload.get("limitations", []))
    lines.append("")
    return "\n".join(lines)
