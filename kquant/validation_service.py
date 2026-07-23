from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .backtest_audit import build_backtest_audit, write_backtest_audit
from .portfolio_backtest import (
    PortfolioConfig,
    buy_and_hold_benchmark,
    ema_trend_benchmark,
    portfolio_performance_metrics,
    simulate_cash_portfolio,
)
from .stock_store import connect, default_db_path
from .strategy_registry import definition_for_profile, register_strategy_version
from .strategy_validation import (
    BacktestConfig,
    evaluate_long_trade,
    evaluate_long_trade_scenarios,
    summarize_by_dimensions,
    summarize_outcomes,
    walk_forward_split,
)
from .validation_robustness import (
    concentration_report,
    evidence_score,
    market_regime_report,
    parameter_sensitivity_report,
    rolling_walk_forward_windows,
    statistical_confidence_report,
)


POLICY_VERSION = "deterministic_action_policy_v3"
CONFIG_VERSION = "backtest_costs_v1"
SUPPORTED_PROFILES = {"tactical_1w_v1", "high_beta_growth_v1"}
BUY_ACTIONS = {"AI_BUY_CANDIDATE", "AI_PULLBACK_BUY", "AI_PROBE_BUY"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append((value - result[-1]) * alpha + result[-1])
    return result


def _rsi(values: list[float], period: int = 14) -> list[float]:
    result = [50.0] * len(values)
    if len(values) <= period:
        return result
    gains = [max(values[index] - values[index - 1], 0.0) for index in range(1, len(values))]
    losses = [max(values[index - 1] - values[index], 0.0) for index in range(1, len(values))]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for index in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[index]) / period
        avg_loss = (avg_loss * (period - 1) + losses[index]) / period
        rs = avg_gain / avg_loss if avg_loss else 999.0
        result[index + 1] = 100 - 100 / (1 + rs)
    return result


def _atr(candles: list[dict[str, Any]], period: int = 14) -> list[float]:
    if not candles:
        return []
    ranges: list[float] = []
    previous_close = _float(candles[0].get("close"))
    for candle in candles:
        high = _float(candle.get("high"))
        low = _float(candle.get("low"))
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        previous_close = _float(candle.get("close"))
    result: list[float] = []
    for index in range(len(ranges)):
        start = max(0, index - period + 1)
        window = ranges[start : index + 1]
        result.append(sum(window) / len(window))
    return result


def _closed_candles(payload: dict[str, Any], start: str | None, end: str | None) -> list[dict[str, Any]]:
    rows = []
    for raw in payload.get("candles") or []:
        item = dict(raw)
        stamp = str(item.get("open_time") or "")
        day = stamp[:10]
        if item.get("bar_state") == "forming_candle":
            continue
        if start and day < start:
            continue
        if end and day > end:
            continue
        if all(_float(item.get(key)) > 0 for key in ("open", "high", "low", "close")):
            rows.append(item)
    return sorted(rows, key=lambda item: str(item.get("open_time") or ""))


def _hourly_confirmation_map(candles: list[dict[str, Any]]) -> dict[str, bool]:
    closes = [_float(item.get("close")) for item in candles]
    ema9 = _ema(closes, 9)
    result: dict[str, bool] = {}
    for index, candle in enumerate(candles):
        result[str(candle.get("open_time") or "")[:10]] = closes[index] >= ema9[index]
    return result


def _regime_map(candles: list[dict[str, Any]]) -> dict[str, str]:
    closes = [_float(item.get("close")) for item in candles]
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    return {
        str(item.get("open_time") or "")[:10]: (
            "RISK_ON" if closes[index] > ema50[index] > ema200[index]
            else "RISK_OFF" if closes[index] < ema200[index]
            else "DATA_CAUTION"
        )
        for index, item in enumerate(candles)
    }


def _policy_signals(
    candles: list[dict[str, Any]],
    *,
    profile: str,
    hourly_confirmation: dict[str, bool],
    regime_by_day: dict[str, str],
    metadata: dict[str, str],
    data_source: str,
    signal_start: str | None = None,
    signal_end: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    active_parameters = dict(parameters or {})
    ema_fast_period = max(2, int(active_parameters.get("ema_fast", 20)))
    ema_medium_period = max(ema_fast_period + 1, int(active_parameters.get("ema_medium", 50)))
    ema_long_period = max(ema_medium_period + 1, int(active_parameters.get("ema_long", 200)))
    min_relative_volume = _float(active_parameters.get("min_relative_volume"), 1.15)
    atr_stop_factor = _float(active_parameters.get("atr_stop_multiplier_factor"), 1.0)
    risk_reward_factor = _float(active_parameters.get("risk_reward_factor"), 1.0)
    closes = [_float(item.get("close")) for item in candles]
    volumes = [_float(item.get("volume")) for item in candles]
    ema20 = _ema(closes, ema_fast_period)
    ema50 = _ema(closes, ema_medium_period)
    ema200 = _ema(closes, ema_long_period)
    rsi14, atr14 = _rsi(closes), _atr(candles)
    signals: list[dict[str, Any]] = []
    horizon = 5 if profile == "tactical_1w_v1" else 20
    for index in range(max(ema_long_period, 200), len(candles) - 1):
        candle = candles[index]
        signal_day = str(candle.get("open_time") or "")[:10]
        if signal_start and signal_day < signal_start:
            continue
        if signal_end and signal_day > signal_end:
            continue
        close = closes[index]
        atr_value = atr14[index]
        if close <= 0 or atr_value <= 0:
            continue
        prior_high = max(closes[index - 20 : index])
        avg_volume = sum(volumes[index - 20 : index]) / 20 if index >= 20 else 0.0
        relative_volume = volumes[index] / avg_volume if avg_volume > 0 else 0.0
        near_ema = min(abs(close - ema20[index]), abs(close - ema50[index])) / close <= 0.025
        reclaimed = closes[index - 1] < ema20[index - 1] and close >= ema20[index]
        breakout = close > prior_high and relative_volume >= min_relative_volume
        trend = close > ema50[index] and ema50[index] > ema200[index]
        hourly_ok = hourly_confirmation.get(signal_day, profile != "tactical_1w_v1")
        action = "AI_WAIT"
        if trend and breakout and hourly_ok:
            action = "AI_BUY_CANDIDATE"
        elif trend and near_ema and 42 <= rsi14[index] <= 65 and hourly_ok:
            action = "AI_PULLBACK_BUY" if profile == "tactical_1w_v1" else "AI_PROBE_BUY"
        elif trend and reclaimed:
            action = "AI_REVERSAL_WATCH"
        elif trend and close >= prior_high * 0.985:
            action = "AI_BREAKOUT_WATCH"
        elif close < ema50[index] and closes[index - 1] >= ema50[index - 1]:
            action = "AI_EXIT_REVIEW"
        if action == "AI_WAIT" and index % 5:
            continue
        stop = close - (1.35 if profile == "tactical_1w_v1" else 1.8) * atr_stop_factor * atr_value
        target = close + 2.0 * risk_reward_factor * (close - stop)
        outcome = evaluate_long_trade(candles, index, stop, target, horizon, BacktestConfig())
        if not outcome.get("completed"):
            continue
        outcome["execution_scenarios"] = evaluate_long_trade_scenarios(
            candles,
            index,
            stop,
            target,
            horizon,
            average_dollar_volume=close * avg_volume,
        )
        volatility_pct = atr_value / close * 100
        volatility_bucket = "low" if volatility_pct < 2 else "medium" if volatility_pct < 4 else "high"
        signals.append(
            {
                **outcome,
                "profile": profile,
                "action": action,
                "symbol": metadata["symbol"],
                "signal_time": candle.get("open_time"),
                "market_regime": regime_by_day.get(signal_day, "DATA_CAUTION"),
                "sector": metadata.get("sector", "Unknown"),
                "stock_layer": metadata.get("layer", "Unknown"),
                "volatility_bucket": volatility_bucket,
                "data_source": data_source,
                "policy_version": POLICY_VERSION,
                "evidence_source": "historical_policy_replay",
                "relative_volume": round(relative_volume, 4),
                "rsi14": round(rsi14[index], 4),
                "atr_pct": round(volatility_pct, 4),
                "hourly_confirmation": bool(hourly_ok),
                "policy_parameters": active_parameters,
            }
        )
    return signals


def run_strategy_validation(
    *,
    profiles: list[str],
    start: str | None,
    end: str | None,
    universe: str,
    symbols: list[str] | None,
    db_path: Path | None = None,
    outputs_dir: Path | None = None,
) -> dict[str, Any]:
    from .stock_signals import api_stock_candles, api_stock_universe, profile_config

    selected_profiles = [profile for profile in profiles if profile in SUPPORTED_PROFILES]
    if not selected_profiles:
        raise ValueError(f"profiles must contain one of: {sorted(SUPPORTED_PROFILES)}")
    db = db_path or default_db_path()
    strategy_records = {
        profile: register_strategy_version(db, definition_for_profile(profile, profile_config(profile)))
        for profile in selected_profiles
    }
    universe_payload = api_stock_universe(universe=universe, db_path=db)
    universe_point_in_time = dict(universe_payload.get("point_in_time") or {
        "historical_membership_complete": False,
        "survivorship_limited": True,
        "limitation": (
            "The universe provider supplied no point-in-time membership metadata; "
            "historical replay is survivorship-limited."
        ),
    })
    universe_limitations = []
    if universe_point_in_time.get("survivorship_limited", True):
        universe_limitations.append(
            "Historical membership composition is incomplete; this replay uses a current/runtime universe snapshot and is survivorship-limited."
        )
    stock_rows = list(universe_payload.get("stocks") or universe_payload.get("universe") or [])
    requested = {item.upper() for item in symbols or []}
    if requested:
        stock_rows = [item for item in stock_rows if str(item.get("symbol", "")).upper() in requested]
    if not stock_rows:
        raise ValueError("The selected universe contains no symbols.")
    symbol_list = [str(item["symbol"]).upper() for item in stock_rows]
    dataset_id = _stable_id("dataset", POLICY_VERSION, universe, start or "", end or "", *symbol_list)
    run_id = _stable_id("validation", dataset_id, _now())
    spy_payload = api_stock_candles("SPY", "5y", "1d", "live", db)
    qqq_payload = api_stock_candles("QQQ", "5y", "1d", "live", db)
    regime_by_day = _regime_map(_closed_candles(spy_payload, None, end))
    all_trades: list[dict[str, Any]] = []
    replay_inputs: list[dict[str, Any]] = []
    provider_errors: list[dict[str, str]] = []
    for stock in stock_rows:
        symbol = str(stock["symbol"]).upper()
        daily_payload = api_stock_candles(symbol, "5y", "1d", "live", db)
        daily = _closed_candles(daily_payload, None, end)
        if len(daily) < 220:
            provider_errors.append({"symbol": symbol, "reason": "fewer than 220 closed daily bars"})
            continue
        hourly_payload = api_stock_candles(symbol, "2y", "1h", "live", db)
        hourly = _closed_candles(hourly_payload, None, end)
        hourly_confirmation = _hourly_confirmation_map(hourly)
        metadata = {
            "symbol": symbol,
            "sector": str(stock.get("sector") or "Unknown"),
            "layer": str(stock.get("layer") or stock.get("primary_layer") or "Unknown"),
        }
        for profile in selected_profiles:
            replay_input = {
                "candles": daily,
                "profile": profile,
                "hourly_confirmation": hourly_confirmation,
                "regime_by_day": regime_by_day,
                "metadata": metadata,
                "data_source": str(daily_payload.get("source_type") or "unknown"),
            }
            replay_inputs.append(replay_input)
            all_trades.extend(
                _policy_signals(
                    **replay_input,
                    signal_start=start,
                    signal_end=end,
                )
            )
    for profile in selected_profiles:
        profile_rows = [item for item in all_trades if item["profile"] == profile]
        embargo = 5 if profile == "tactical_1w_v1" else 20
        split = walk_forward_split(profile_rows, embargo_bars=embargo)
        for split_name, rows in split.items():
            for item in rows:
                item["split_name"] = split_name
    all_trades = [item for item in all_trades if item.get("split_name")]

    def replay_variant(overrides: dict[str, Any]) -> list[dict[str, Any]]:
        variant_rows: list[dict[str, Any]] = []
        for replay_input in replay_inputs:
            variant_rows.extend(
                _policy_signals(
                    **replay_input,
                    signal_start=start,
                    signal_end=end,
                    parameters=overrides,
                )
            )
        return variant_rows

    sensitivity = parameter_sensitivity_report(replay_variant) if replay_inputs else {
        "stable": False,
        "variants": [],
        "not_an_optimization_search": True,
    }
    config = BacktestConfig()
    created_at = _now()
    with connect(db) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO strategy_validation_datasets(
              dataset_id, evidence_source, policy_version, universe, start_date,
              end_date, symbols_json, config_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dataset_id, "historical_policy_replay", POLICY_VERSION, universe,
                start or "", end or "", json.dumps(symbol_list),
                json.dumps({
                    **config.__dict__, "config_version": CONFIG_VERSION, "split": "60/20/20", "embargo": "max_horizon",
                    "strategy_versions": {profile: record.strategy_version for profile, record in strategy_records.items()},
                    "strategy_config_hashes": {profile: record.config_hash for profile, record in strategy_records.items()},
                    "universe_point_in_time": universe_point_in_time,
                    "data_limitations": universe_limitations,
                }),
                created_at,
            ),
        )
        for item in all_trades:
            trade_id = _stable_id("trade", dataset_id, item["profile"], item["symbol"], item["signal_time"])
            conn.execute(
                """
                INSERT OR REPLACE INTO strategy_validation_trades(
                  trade_id, run_id, dataset_id, evidence_source, policy_version, strategy_version, strategy_config_hash, profile,
                  action, symbol, signal_time, entry_time, exit_time, split_name,
                  market_regime, sector, stock_layer, volatility_bucket, data_source,
                  outcome, realized_r, target_first, stop_first, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade_id, run_id, dataset_id, "historical_policy_replay", POLICY_VERSION,
                    strategy_records[item["profile"]].strategy_version, strategy_records[item["profile"]].config_hash,
                    item["profile"], item["action"], item["symbol"], item["signal_time"],
                    item.get("entry_time"), item.get("exit_time"), item["split_name"],
                    item["market_regime"], item["sector"], item["stock_layer"],
                    item["volatility_bucket"], item["data_source"], item["outcome"],
                    item["realized_r"], int(bool(item["target_first"])), int(bool(item["stop_first"])),
                    json.dumps(item, ensure_ascii=True), created_at,
                ),
            )
        for profile in selected_profiles:
            for split_name in ("train", "validation", "test"):
                rows = [item for item in all_trades if item["profile"] == profile and item["split_name"] == split_name]
                summary = summarize_outcomes(rows)
                record_id = _stable_id("summary", run_id, profile, split_name)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO strategy_validation_runs(
                      run_id, profile, action, split_name, sample_count, win_rate,
                      average_r, profit_factor, max_drawdown_r, confidence_low,
                      confidence_high, payload_json, created_at, dataset_id,
                      evidence_source, policy_version, config_version, strategy_version, strategy_config_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id, profile, "ALL", split_name, summary["sample_count"],
                        summary["win_rate"], summary["average_r"], summary["profit_factor"],
                        summary["max_drawdown_r"], summary["confidence_interval_95"][0],
                        summary["confidence_interval_95"][1], json.dumps(summary), created_at,
                        dataset_id, "historical_policy_replay", POLICY_VERSION, CONFIG_VERSION,
                        strategy_records[profile].strategy_version, strategy_records[profile].config_hash,
                    ),
                )
        conn.commit()
    summary = summarize_outcomes(all_trades)
    portfolio = simulate_cash_portfolio(all_trades, PortfolioConfig())
    portfolio_metrics = portfolio_performance_metrics(portfolio)
    benchmark_spy = buy_and_hold_benchmark(_closed_candles(spy_payload, start, end), "SPY buy-and-hold")
    benchmark_qqq = buy_and_hold_benchmark(_closed_candles(qqq_payload, start, end), "QQQ buy-and-hold")
    test_rows = [item for item in all_trades if item.get("split_name") == "test"]
    test_summary = summarize_outcomes(test_rows)
    rolling = {
        profile: rolling_walk_forward_windows(
            [item for item in all_trades if item["profile"] == profile],
            embargo_bars=5 if profile == "tactical_1w_v1" else 20,
        )
        for profile in selected_profiles
    }
    regime = market_regime_report(all_trades)
    concentration = concentration_report(all_trades)
    confidence = statistical_confidence_report(all_trades, trial_count=len(sensitivity.get("variants") or []))
    evidence = evidence_score(
        test_summary=test_summary,
        sensitivity=sensitivity,
        regime=regime,
        concentration=concentration,
        portfolio_metrics=portfolio_metrics,
        benchmark_return_pct=_float(benchmark_spy.get("total_return_pct")) if benchmark_spy.get("available") else None,
    )
    audit = build_backtest_audit(
        dataset_id=dataset_id,
        policy_version=POLICY_VERSION,
        strategy_versions={profile: record.strategy_version for profile, record in strategy_records.items()},
        strategy_config_hashes={profile: record.config_hash for profile, record in strategy_records.items()},
        config={
            **config.__dict__,
            "config_version": CONFIG_VERSION,
            "split": "60/20/20",
            "portfolio": portfolio["portfolio_config"],
        },
        symbols=symbol_list,
        trades=all_trades,
    )
    payload = {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "evidence_source": "historical_policy_replay",
        "policy_version": POLICY_VERSION,
        "strategy_versions": {profile: record.strategy_version for profile, record in strategy_records.items()},
        "strategy_config_hashes": {profile: record.config_hash for profile, record in strategy_records.items()},
        "profiles": selected_profiles,
        "universe": universe,
        "universe_point_in_time": universe_point_in_time,
        "data_limitations": universe_limitations,
        "symbols_requested": len(symbol_list),
        "symbols_with_data": len({item["symbol"] for item in all_trades}),
        "provider_errors": provider_errors,
        "summary": summary,
        "by_dimension": summarize_by_dimensions(all_trades),
        "portfolio_backtest": {
            "metrics": portfolio_metrics,
            "execution_count": len(portfolio["executions"]),
            "rejected_candidate_count": len(portfolio["rejected"]),
            "cash_only": True,
        },
        "benchmarks": {
            "spy_buy_and_hold": benchmark_spy,
            "qqq_buy_and_hold": benchmark_qqq,
            "spy_ema20_ema50": ema_trend_benchmark(_closed_candles(spy_payload, start, end)),
            "deterministic_policy_only": {
                "available": True,
                "description": "Uses rule-policy replay only; no LLM ranking or account data.",
                "sample_count": summary["sample_count"],
                "average_r": summary["average_r"],
            },
        },
        "robustness": {
            "rolling_walk_forward": rolling,
            "parameter_sensitivity": sensitivity,
            "market_regimes": regime,
            "concentration": concentration,
            "statistical_confidence": confidence,
            "evidence_score": evidence,
            "research_only": True,
        },
        "reproducibility_audit": audit,
        "created_at": created_at,
    }
    output = outputs_dir or Path("outputs")
    output.mkdir(parents=True, exist_ok=True)
    (output / "strategy-validation-v3-latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["reproducibility_audit"]["report_paths"] = write_backtest_audit(audit, summary, output, run_id=run_id)
    (output / "strategy-validation-v3-latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _load_historical_trades(db_path: Path, profile: str | None = None, action: str | None = None) -> tuple[str | None, list[dict[str, Any]]]:
    with connect(db_path) as conn:
        dataset = conn.execute(
            "SELECT dataset_id FROM strategy_validation_datasets WHERE evidence_source='historical_policy_replay' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if not dataset:
            return None, []
        query = "SELECT payload_json FROM strategy_validation_trades WHERE dataset_id = ?"
        params: list[Any] = [dataset["dataset_id"]]
        if profile:
            query += " AND profile = ?"
            params.append(profile)
        if action:
            query += " AND action = ?"
            params.append(action)
        rows = conn.execute(query, params).fetchall()
    return str(dataset["dataset_id"]), [json.loads(row["payload_json"]) for row in rows]


def _load_prospective_outcomes(db_path: Path, profile: str | None = None, action: str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        query = """
          SELECT e.profile, e.action, e.market_regime, e.data_source, e.symbol,
                 o.realized_r, o.target_first, o.stop_first, o.completed, o.outcome,
                 e.signal_time
          FROM ai_action_events e JOIN ai_action_outcomes o ON o.event_key=e.event_key
          WHERE o.completed=1
        """
        params: list[Any] = []
        if profile:
            query += " AND e.profile = ?"
            params.append(profile)
        if action:
            query += " AND e.action = ?"
            params.append(action)
        rows = [dict(row) for row in conn.execute(query, params).fetchall()]
    for row in rows:
        row.update(
            {
                "evidence_source": "prospective_llm_actions",
                "completed": bool(row.get("completed")),
                "target_first": bool(row.get("target_first")),
                "stop_first": bool(row.get("stop_first")),
            }
        )
    return rows


def api_strategy_validation_latest(db_path: Path | None = None, profile: str | None = None) -> dict[str, Any]:
    db = db_path or default_db_path()
    dataset_id, historical = _load_historical_trades(db, profile)
    prospective = _load_prospective_outcomes(db, profile)
    return {
        "dataset_id": dataset_id,
        "profile": profile or "all",
        "evidence": {
            "historical_policy_replay": {
                "summary": summarize_outcomes(historical),
                "by_dimension": summarize_by_dimensions(historical),
            },
            "prospective_llm_actions": {
                "summary": summarize_outcomes(prospective),
                "by_dimension": summarize_by_dimensions(prospective),
            },
        },
        "evidence_mixed": False,
        "read_only": True,
    }


def api_strategy_validation_action(action: str, db_path: Path | None = None, profile: str | None = None) -> dict[str, Any]:
    normalized = action.strip().upper()
    db = db_path or default_db_path()
    dataset_id, historical = _load_historical_trades(db, profile, normalized)
    prospective = _load_prospective_outcomes(db, profile, normalized)
    return {
        "action": normalized,
        "profile": profile or "all",
        "dataset_id": dataset_id,
        "historical_policy_replay": summarize_outcomes(historical),
        "prospective_llm_actions": summarize_outcomes(prospective),
        "evidence_mixed": False,
    }
