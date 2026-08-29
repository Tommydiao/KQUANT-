from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .evaluation_agent import EvaluationAgent
from .evaluation_models import EVAL_POLICY_VERSION, stable_hash
from .factor_engine import FactorMarketInput, OHLCVBar, compute_factor_values
from .factor_registry import FactorRegistry, score_registered_factors
from .market_buffer import Candle
from .market_models import NormalizedMarketEvent
from .market_runtime import MarketDataRuntime
from .market_regime_runtime import MarketRegimeRuntime
from .model_registry import ModelArtifactRegistry
from .realtime_supervisor import RealtimeSupervisor
from .signal_agent import SetupStage, SignalProposal, propose_signal
from .trade_plan_agent import build_trade_plan_draft


STRATEGY_VERSION = "crypto_early_v1.0.0"

# These are deliberately explicit and versioned with the runtime.  They are
# research weights, not a live trading authorization.  EVAL remains closed
# until data, security, model and Paper gates are independently passed.
SETUP_WEIGHTS: dict[str, float] = {
    "trend_ema_reclaim": 25.0,
    "trend_ema_slope": 500.0,
    "relative_strength_btc": 120.0,
    "relative_strength_eth": 120.0,
    "momentum_acceleration": 100.0,
    "volume_acceleration": 20.0,
    "cvd_bias": 10.0,
    "volatility_compression": 5.0,
    "oi_price_alignment": 5.0,
    "funding_extreme": 5.0,
    "liquidity_spread": 5.0,
    "breakout_distance": -25.0,
}


def _bar(value: Candle) -> OHLCVBar:
    return OHLCVBar(close=value.close, high=value.high, low=value.low, volume=value.volume)


def _return(bars: tuple[Candle, ...], lookback: int) -> float | None:
    if len(bars) <= lookback:
        return None
    previous = bars[-1 - lookback].close
    return None if previous == 0 else bars[-1].close / previous - 1.0


def _atr(bars: tuple[Candle, ...], period: int = 14) -> float | None:
    if len(bars) <= period:
        return None
    ranges: list[float] = []
    for index in range(1, len(bars)):
        current = bars[index]
        previous_close = bars[index - 1].close
        ranges.append(max(
            current.high - current.low,
            abs(current.high - previous_close),
            abs(current.low - previous_close),
        ))
    return sum(ranges[-period:]) / period if ranges[-period:] else None


def _instrument_symbol(instrument_id: str) -> str:
    return instrument_id.rsplit(":", 1)[-1].upper()


class CEXSignalRuntime:
    """Turn completed CEX candles into EVAL-reviewed research drafts.

    This component intentionally stops at the deterministic EVAL boundary.
    It never calls a notification transport directly and never has account,
    wallet, or order capabilities.
    """

    def __init__(
        self,
        db_path: Path,
        market_runtime: MarketDataRuntime,
        factor_registry: FactorRegistry,
        instruction_supervisor: RealtimeSupervisor,
        *,
        benchmark_symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT"),
        universe_snapshot_id: str | None = None,
        regime_runtime: MarketRegimeRuntime | None = None,
    ):
        self.db_path = db_path
        self.market_runtime = market_runtime
        self.factor_registry = factor_registry
        self.instruction_supervisor = instruction_supervisor
        self.evaluator = EvaluationAgent(db_path, factor_registry, ModelArtifactRegistry(db_path))
        self.benchmark_symbols = benchmark_symbols
        self.universe_snapshot_id = universe_snapshot_id or "universe:cex_core_v1"
        self.regime_runtime = regime_runtime
        self.last_processed: dict[str, str] = {}
        self.events_seen = 0
        self.candidates_seen = 0
        self.evaluations_created = 0
        self.skipped_insufficient_history = 0
        self.last_error: str | None = None
        self.last_evaluation_at: str | None = None

    def on_market_event(self, event: NormalizedMarketEvent) -> dict[str, Any] | None:
        """Process a newly closed 1m event; failures stay local to the runtime."""

        self.events_seen += 1
        if event.event_type != "kline" or event.market_type != "spot":
            return None
        if str(event.payload.get("interval") or "") not in {"1m", "1", "1M"}:
            return None
        if not bool(event.payload.get("closed")):
            return None
        try:
            return self._process_closed_5m(event)
        except Exception as exc:  # a bad candidate must never stop market ingestion
            self.last_error = type(exc).__name__
            return {"status": "error", "error": self.last_error, "instrument_id": event.instrument_id}

    def _process_closed_5m(self, event: NormalizedMarketEvent) -> dict[str, Any] | None:
        latest = self.market_runtime.buffer.latest_closed(event.instrument_id, "5m")
        if latest is None:
            return None
        if self.last_processed.get(event.instrument_id) == latest.start_time:
            return {"status": "duplicate", "instrument_id": event.instrument_id, "candle": latest.start_time}
        self.last_processed[event.instrument_id] = latest.start_time

        bars = self.market_runtime.buffer.closed_history(event.instrument_id, "5m")
        if len(bars) < 60:
            self.skipped_insufficient_history += 1
            return {"status": "insufficient_history", "instrument_id": event.instrument_id, "bars": len(bars)}

        snapshot = self.market_runtime.snapshot(event.instrument_id)
        benchmark_bars: dict[str, tuple[OHLCVBar, ...]] = {}
        for symbol in self.benchmark_symbols:
            instrument_id = self._find_spot_instrument(event.venue, symbol)
            if instrument_id:
                benchmark_bars[symbol.removesuffix("USDT")] = tuple(
                    _bar(item) for item in self.market_runtime.buffer.closed_history(instrument_id, "5m")
                )

        derivative = snapshot.get("derivative") or {}
        market_input = FactorMarketInput(
            bars=tuple(_bar(item) for item in bars),
            benchmark_bars=benchmark_bars,
            cvd=(snapshot.get("order_flow") or {}).get("cvd"),
            buy_volume=(snapshot.get("order_flow") or {}).get("buy_volume"),
            sell_volume=(snapshot.get("order_flow") or {}).get("sell_volume"),
            funding_rate=self._number(derivative.get("funding_rate")),
            spread_bps=self._number(snapshot.get("spread_bps")),
        )
        values = compute_factor_values(market_input)
        scored = score_registered_factors(self.factor_registry, values, SETUP_WEIGHTS)

        confirmation_bars = self.market_runtime.buffer.closed_history(event.instrument_id, "1H")
        trigger_score: float | None = None
        if len(confirmation_bars) >= 20:
            confirmation_input = FactorMarketInput(
                bars=tuple(_bar(item) for item in confirmation_bars),
                benchmark_bars={
                    key: tuple(_bar(item) for item in self.market_runtime.buffer.closed_history(
                        self._find_spot_instrument(event.venue, symbol) or "", "1H"
                    ))
                    for key, symbol in (("BTC", "BTCUSDT"), ("ETH", "ETHUSDT"))
                    if self._find_spot_instrument(event.venue, symbol)
                },
                spread_bps=self._number(snapshot.get("spread_bps")),
            )
            confirmation_values = compute_factor_values(confirmation_input)
            trigger_score = float(score_registered_factors(self.factor_registry, confirmation_values, SETUP_WEIGHTS)["score"])

        trust = str(snapshot.get("trust") or event.provider_status).lower()
        data_quality = "live" if trust == "live" and (snapshot.get("age_seconds") is None or float(snapshot["age_seconds"]) <= 30) else "stale"
        bid = self._number(snapshot.get("bid"))
        ask = self._number(snapshot.get("ask"))
        spread_bps = self._number(snapshot.get("spread_bps"))
        liquidity = "pass" if bid is not None and ask is not None and spread_bps is not None and spread_bps <= 80 else "unavailable"
        five_bar_return = _return(bars, 5)
        ema20 = self._ema(tuple(item.close for item in bars), 20)
        ema20_deviation = None if ema20 in (None, 0) else bars[-1].close / ema20 - 1.0
        signal = propose_signal(
            self.factor_registry,
            asset_id=event.asset_id,
            symbol=_instrument_symbol(event.instrument_id),
            asset_type="cex_spot",
            strategy_version=STRATEGY_VERSION,
            factor_values=values,
            weights=SETUP_WEIGHTS,
            trigger_score=trigger_score,
            five_day_return=five_bar_return,
            ema20_deviation=ema20_deviation,
            data_quality_status=data_quality,
            security_status="unknown",
            liquidity_status=liquidity,
            market_regime=str((self.regime_runtime.latest() if self.regime_runtime else {}).get("regime") or "DATA_CAUTION"),
            as_of_time=latest.start_time,
        )
        if signal.stage == SetupStage.MONITORING.value:
            return {"status": "monitoring", "signal": signal.to_mapping()}

        self.candidates_seen += 1
        factor_snapshot = self.factor_registry.snapshot(
            asset_id=signal.asset_id,
            strategy_version=STRATEGY_VERSION,
            as_of_time=signal.as_of_time,
            values=values,
            contributions=scored["contributions"],
            missing_factor_ids=scored["missing_factor_ids"],
        )
        atr = _atr(bars)
        if atr is None or atr <= 0 or bars[-1].close <= 0:
            return {"status": "candidate_without_plan", "signal": signal.to_mapping(), "reason": "atr_unavailable"}
        close = bars[-1].close
        entry_zone = [close * 0.995, close * 1.005]
        stop_zone = [max(0.0, close - 1.5 * atr), max(0.0, close - atr)]
        target_zone = [close + 2.5 * atr, close + 3.5 * atr]
        risk_reward = 2.0
        candle_key = f"{event.instrument_id}:{latest.start_time}:{STRATEGY_VERSION}"
        plan_id = f"plan_{stable_hash(candle_key)[:24]}"
        regime_snapshot = self.regime_runtime.latest() if self.regime_runtime else None
        bindings = {
            "market": f"market:{event.instrument_id}:{latest.start_time}",
            "regime": str(regime_snapshot.get("regime_snapshot_id") if regime_snapshot else f"regime:pending:{latest.start_time}"),
            "factor": factor_snapshot["content_hash"],
            "security": f"security:unknown:{signal.asset_id}",
            "liquidity": f"liquidity:{event.instrument_id}:{latest.start_time}",
            "derivative": f"derivative:pending:{latest.start_time}",
            "signal": f"signal:{signal.material_state_hash}",
            "plan": plan_id,
            "model": "model:rules_pending_oos_gate",
            "universe": self.universe_snapshot_id,
            "eval_policy": EVAL_POLICY_VERSION,
        }
        draft = build_trade_plan_draft(
            signal,
            entry_zone=entry_zone,
            stop_zone=stop_zone,
            target_zone=target_zone,
            risk_reward=risk_reward,
            source_snapshot_ids=list(bindings.values()),
            factor_snapshot_hash=factor_snapshot["content_hash"],
            snapshot_bindings=bindings,
            valid_minutes=30,
            model_status="pending",
            requested_execution_class="paper_only",
            as_of_time=latest.start_time,
            plan_id=plan_id,
        )
        payload = {
            **draft.payload,
            "provider_status": event.provider_status,
            "closed_candle": True,
            "closed_candle_time": latest.start_time,
            "forming_candle": False,
            "bbo_valid": bid is not None and ask is not None,
            "depth_status": "available" if bid is not None and ask is not None else "unavailable",
            "spread_bps": spread_bps,
            "funding_rate": self._number(derivative.get("funding_rate")),
            "factor_snapshot_id": factor_snapshot["factor_snapshot_id"],
            "trigger_score": trigger_score,
            "supporting_factors": list(signal.supporting_factors),
            "opposing_factors": list(signal.opposing_factors),
        }
        draft = replace(draft, payload=payload)
        evaluation = self.evaluator.evaluate(draft).to_mapping()
        result = self.instruction_supervisor.accept_evaluation(evaluation)
        self.evaluations_created += 1
        self.last_evaluation_at = evaluation["evaluated_at"]
        return {"status": "evaluated", "signal": signal.to_mapping(), "evaluation": evaluation, **result}

    def _find_spot_instrument(self, venue: str, symbol: str) -> str | None:
        exact = f"{venue}:spot:{symbol.upper()}"
        if exact in self.market_runtime.buffer.instruments():
            return exact
        suffix = f":spot:{symbol.upper()}"
        return next((item for item in self.market_runtime.buffer.instruments() if item.endswith(suffix)), None)

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _ema(values: tuple[float, ...], period: int) -> float | None:
        if len(values) < period:
            return None
        current = sum(values[:period]) / period
        alpha = 2.0 / (period + 1)
        for value in values[period:]:
            current = alpha * value + (1.0 - alpha) * current
        return current

    def status(self) -> dict[str, Any]:
        return {
            "status": "running",
            "strategy_version": STRATEGY_VERSION,
            "universe_snapshot_id": self.universe_snapshot_id,
            "events_seen": self.events_seen,
            "candidates_seen": self.candidates_seen,
            "evaluations_created": self.evaluations_created,
            "skipped_insufficient_history": self.skipped_insufficient_history,
            "last_evaluation_at": self.last_evaluation_at,
            "last_error": self.last_error,
            "paper_enabled": False,
            "shadow_enabled": False,
            "order_submission": False,
        }
