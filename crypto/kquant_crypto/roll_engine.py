from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from typing import Any

from .evaluation_models import stable_hash


CRYPTO_ROLL_STRATEGY_VERSION = "crypto_roll_v1.0.0"
ROLL_POLICY_VERSION = "crypto_roll_policy_v1.0.0"


class RollAction(StrEnum):
    ROLL_BUY = "ROLL_BUY"
    ROLL_ADD = "ROLL_ADD"
    HOLD_CORE = "HOLD_CORE"
    ROTATE_TO = "ROTATE_TO"
    REDUCE = "REDUCE"
    WAIT = "WAIT"
    EXIT_REVIEW = "EXIT_REVIEW"
    DATA_BLOCKED = "DATA_BLOCKED"


ROLLABLE_ASSET_TYPES = frozenset({"crypto_spot", "cex_spot", "crypto_etf", "crypto_leveraged_etf", "listed_crypto_proxy", "crypto_equity_proxy"})
LISTED_CRYPTO_ASSET_TYPES = frozenset({"crypto_etf", "crypto_leveraged_etf", "listed_crypto_proxy", "crypto_equity_proxy"})
VALID_SOURCE_STATUS = frozenset({"live", "closed", "complete", "verified"})
VALID_MARKET_STATES = frozenset({"BULL", "ACCUMULATION", "DISTRIBUTION", "BEAR_STRESS"})

ROLL_ASSET_MAP: dict[str, dict[str, str]] = {
    "BTC": {"instrument_id": "binance:spot:BTCUSDT", "asset_type": "crypto_spot"},
    "ETH": {"instrument_id": "binance:spot:ETHUSDT", "asset_type": "crypto_spot"},
    "SOL": {"instrument_id": "binance:spot:SOLUSDT", "asset_type": "crypto_spot"},
    "ETHU": {"instrument_id": "listed:US:ETHU", "asset_type": "crypto_leveraged_etf"},
    "MSTR": {"instrument_id": "listed:US:MSTR", "asset_type": "crypto_equity_proxy"},
    "MSTU": {"instrument_id": "listed:US:MSTU", "asset_type": "crypto_leveraged_etf"},
    "AAVE": {"instrument_id": "binance:spot:AAVEUSDT", "asset_type": "crypto_spot"},
    "ENA": {"instrument_id": "binance:spot:ENAUSDT", "asset_type": "crypto_spot"},
    "ZEC": {"instrument_id": "binance:spot:ZECUSDT", "asset_type": "crypto_spot"},
    "PUMP": {"instrument_id": "binance:spot:PUMPUSDT", "asset_type": "crypto_spot"},
}


def canonical_roll_symbol(symbol: str) -> str:
    normalized = str(symbol or "").upper().replace("/USDT", "").replace("USDT", "")
    return normalized


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _number(value: object, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if isfinite(parsed) else default


def _text_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = ()
    return tuple(str(item) for item in values if str(item).strip())


@dataclass(frozen=True)
class RollInput:
    """Point-in-time input contract for the deterministic roll policy.

    ``realized_profit`` is the only value that can become roll capital. A
    floating gain is evidence, not spendable capital, and a floating loss
    explicitly prevents an add action.
    """

    asset_id: str
    symbol: str
    asset_type: str
    as_of_time: str
    data_cutoff_time: str
    source_status: str
    coverage: float
    hard_veto: bool
    market_state: str
    state_probability: float
    target_before_stop_probability: float
    positive_return_probability: float
    drawdown_probability: float
    strategy_version: str = CRYPTO_ROLL_STRATEGY_VERSION
    instrument_id: str = ""
    realized_profit: float = 0.0
    floating_pnl: float = 0.0
    current_exposure: float = 0.0
    proposed_capital: float = 0.0
    probability_improvement: float = 0.0
    instrument_data_status: str = ""
    underlying_proxy_used: bool = False
    current_score: float | None = None
    rotation_score: float | None = None
    rotation_target: str | None = None
    feature_snapshot_id: str = ""
    model_version: str = ""
    source_snapshot_ids: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    research_only: bool = True

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "RollInput":
        drawdown_probability = _number(value.get("drawdown_probability"))
        return cls(
            asset_id=str(value.get("asset_id") or ""),
            symbol=str(value.get("symbol") or ""),
            asset_type=str(value.get("asset_type") or ""),
            instrument_id=str(value.get("instrument_id") or ""),
            as_of_time=str(value.get("as_of_time") or ""),
            data_cutoff_time=str(value.get("data_cutoff_time") or value.get("as_of_time") or ""),
            source_status=str(value.get("source_status") or "unknown").lower(),
            coverage=_number(value.get("coverage"), 0.0) or 0.0,
            hard_veto=bool(value.get("hard_veto")),
            market_state=str(value.get("market_state") or "unknown").upper(),
            state_probability=_number(value.get("state_probability"), 0.0) or 0.0,
            target_before_stop_probability=_number(value.get("target_before_stop_probability"), 0.0) or 0.0,
            positive_return_probability=_number(value.get("positive_return_probability"), 0.0) or 0.0,
            drawdown_probability=1.0 if drawdown_probability is None else drawdown_probability,
            strategy_version=str(value.get("strategy_version") or CRYPTO_ROLL_STRATEGY_VERSION),
            realized_profit=_number(value.get("realized_profit"), 0.0) or 0.0,
            floating_pnl=_number(value.get("floating_pnl"), 0.0) or 0.0,
            current_exposure=_number(value.get("current_exposure"), 0.0) or 0.0,
            proposed_capital=_number(value.get("proposed_capital"), 0.0) or 0.0,
            probability_improvement=_number(value.get("probability_improvement"), 0.0) or 0.0,
            instrument_data_status=str(value.get("instrument_data_status") or "").lower(),
            underlying_proxy_used=bool(value.get("underlying_proxy_used")),
            current_score=_number(value.get("current_score")),
            rotation_score=_number(value.get("rotation_score")),
            rotation_target=str(value.get("rotation_target") or "") or None,
            feature_snapshot_id=str(value.get("feature_snapshot_id") or ""),
            model_version=str(value.get("model_version") or ""),
            source_snapshot_ids=_text_tuple(value.get("source_snapshot_ids")),
            missing_fields=_text_tuple(value.get("missing_fields")),
            warnings=_text_tuple(value.get("warnings")),
            research_only=bool(value.get("research_only", True)),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "symbol": self.symbol,
            "asset_type": self.asset_type,
            "instrument_id": self.instrument_id,
            "as_of_time": self.as_of_time,
            "data_cutoff_time": self.data_cutoff_time,
            "source_status": self.source_status,
            "coverage": self.coverage,
            "hard_veto": self.hard_veto,
            "market_state": self.market_state,
            "state_probability": self.state_probability,
            "target_before_stop_probability": self.target_before_stop_probability,
            "positive_return_probability": self.positive_return_probability,
            "drawdown_probability": self.drawdown_probability,
            "strategy_version": self.strategy_version,
            "realized_profit": self.realized_profit,
            "floating_pnl": self.floating_pnl,
            "current_exposure": self.current_exposure,
            "proposed_capital": self.proposed_capital,
            "probability_improvement": self.probability_improvement,
            "instrument_data_status": self.instrument_data_status,
            "underlying_proxy_used": self.underlying_proxy_used,
            "current_score": self.current_score,
            "rotation_score": self.rotation_score,
            "rotation_target": self.rotation_target,
            "feature_snapshot_id": self.feature_snapshot_id,
            "model_version": self.model_version,
            "source_snapshot_ids": list(self.source_snapshot_ids),
            "missing_fields": list(self.missing_fields),
            "warnings": list(self.warnings),
            "research_only": self.research_only,
        }


@dataclass(frozen=True)
class RollDecision:
    roll_id: str
    asset_id: str
    symbol: str
    asset_type: str
    strategy_version: str
    policy_version: str
    action: str
    status: str
    rationale: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    roll_capital: float
    remaining_risk: float
    as_of_time: str
    data_cutoff_time: str
    source_status: str
    coverage: float
    feature_snapshot_id: str
    model_version: str
    source_snapshot_ids: tuple[str, ...]
    hard_veto: bool
    research_only: bool = True
    payload: dict[str, Any] = field(default_factory=dict)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "roll_id": self.roll_id,
            "asset_id": self.asset_id,
            "symbol": self.symbol,
            "asset_type": self.asset_type,
            "strategy_version": self.strategy_version,
            "policy_version": self.policy_version,
            "action": self.action,
            "status": self.status,
            "rationale": self.rationale,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "roll_capital": self.roll_capital,
            "remaining_risk": self.remaining_risk,
            "as_of_time": self.as_of_time,
            "data_cutoff_time": self.data_cutoff_time,
            "source_status": self.source_status,
            "coverage": self.coverage,
            "feature_snapshot_id": self.feature_snapshot_id,
            "model_version": self.model_version,
            "source_snapshot_ids": list(self.source_snapshot_ids),
            "hard_veto": self.hard_veto,
            "research_only": self.research_only,
            "payload": self.payload,
        }


def _valid_probability(value: float) -> bool:
    return isfinite(float(value)) and 0.0 <= float(value) <= 1.0


def evaluate_roll(value: RollInput | dict[str, Any]) -> RollDecision:
    """Evaluate a crypto roll plan without calling a model or a provider.

    The output is deterministic for a given input. It is a research decision
    only; the function never emits an alert, creates a Paper position, or
    accesses an account or wallet.
    """

    item = value if isinstance(value, RollInput) else RollInput.from_mapping(value)
    canonical_symbol = canonical_roll_symbol(item.symbol)
    blockers: list[str] = []
    warnings = list(item.warnings)
    state = item.market_state
    as_of = _parse_time(item.as_of_time)
    cutoff = _parse_time(item.data_cutoff_time)
    if not item.asset_id or not item.symbol or not item.asset_type:
        blockers.append("asset_identity_missing")
    if item.strategy_version != CRYPTO_ROLL_STRATEGY_VERSION:
        blockers.append("strategy_version_mismatch")
    if item.asset_type not in ROLLABLE_ASSET_TYPES:
        blockers.append("asset_type_not_supported")
    mapped = ROLL_ASSET_MAP.get(canonical_symbol)
    if mapped is None:
        blockers.append("asset_mapping_missing")
    else:
        expected_asset_id = f"asset:{canonical_symbol.lower()}"
        if item.asset_id.strip().lower() != expected_asset_id:
            blockers.append("asset_identity_mismatch")
        if item.instrument_id and item.instrument_id != mapped["instrument_id"]:
            blockers.append("instrument_mapping_mismatch")
        if item.asset_type != mapped["asset_type"]:
            blockers.append("asset_type_mapping_mismatch")
    if item.asset_type in LISTED_CRYPTO_ASSET_TYPES:
        if not item.instrument_id:
            blockers.append("actual_instrument_required")
        if item.instrument_data_status != "actual":
            blockers.append("listed_instrument_data_unavailable")
        if item.underlying_proxy_used:
            blockers.append("underlying_proxy_substitution_forbidden")
    if item.source_status not in VALID_SOURCE_STATUS:
        blockers.append("source_status_not_verified")
    if not 0.0 < item.coverage <= 1.0:
        blockers.append("coverage_insufficient")
    elif item.coverage < 0.95:
        blockers.append("coverage_below_policy")
    if item.hard_veto:
        blockers.append("upstream_hard_veto")
    if state not in VALID_MARKET_STATES:
        blockers.append("market_state_unknown")
    if as_of is None or cutoff is None:
        blockers.append("timestamp_missing")
    elif cutoff > as_of:
        blockers.append("future_data_cutoff")
    if item.missing_fields:
        blockers.append("required_fields_missing")
    if not item.feature_snapshot_id:
        blockers.append("feature_snapshot_id_missing")
    if not item.model_version:
        blockers.append("model_version_missing")
    probabilities = (
        item.state_probability,
        item.target_before_stop_probability,
        item.positive_return_probability,
        item.drawdown_probability,
    )
    if any(not _valid_probability(number) for number in probabilities):
        blockers.append("probability_out_of_range")
    if item.research_only is not True:
        blockers.append("research_only_contract_required")

    if blockers:
        action = RollAction.DATA_BLOCKED
        rationale = "Required point-in-time evidence is not complete; no roll action is allowed."
        roll_capital = 0.0
    else:
        realized_profit = max(0.0, float(item.realized_profit))
        floating_loss = float(item.floating_pnl) < 0.0
        roll_capital = min(realized_profit, max(0.0, float(item.proposed_capital)))
        if floating_loss:
            roll_capital = 0.0
        if state == "BEAR_STRESS" or item.drawdown_probability >= 0.70:
            action = RollAction.EXIT_REVIEW if item.current_exposure > 0 else RollAction.WAIT
            rationale = "Stress probability is elevated; review exit or remain unallocated."
        elif item.rotation_target and item.rotation_score is not None and item.current_score is not None and item.rotation_score > item.current_score + 0.10 and not floating_loss and realized_profit > 0:
            action = RollAction.ROTATE_TO
            rationale = "A stronger candidate is available and only realized profit may be rotated."
            warnings.append(f"rotation_target:{item.rotation_target}")
        elif item.current_exposure <= 0:
            if state in {"BULL", "ACCUMULATION"} and item.target_before_stop_probability >= 0.62 and item.positive_return_probability >= 0.58:
                action = RollAction.ROLL_BUY
                rationale = "Market state and target-before-stop evidence meet the initial roll threshold."
            else:
                action = RollAction.WAIT
                rationale = "State or probability evidence is not strong enough for an initial roll."
        elif floating_loss:
            warnings.append("floating_loss_no_add")
            if item.drawdown_probability >= 0.50 or state == "DISTRIBUTION":
                action = RollAction.REDUCE
                rationale = "The position is floating at a loss and risk evidence calls for reduction review."
            else:
                action = RollAction.HOLD_CORE
                rationale = "The position is floating at a loss; adding capital is prohibited."
        elif item.probability_improvement < 0.05:
            action = RollAction.HOLD_CORE
            rationale = "Realized profit exists, but the probability has not improved enough to roll again."
        elif state in {"BULL", "ACCUMULATION"} and item.target_before_stop_probability >= 0.62 and roll_capital > 0:
            action = RollAction.ROLL_ADD
            rationale = "Realized profit, improving probability, and a supportive state permit a research roll."
        else:
            action = RollAction.WAIT
            rationale = "The existing position remains under review until state and probability align."
        if action not in {RollAction.ROLL_BUY, RollAction.ROLL_ADD, RollAction.ROTATE_TO}:
            roll_capital = 0.0

    remaining_risk = max(0.0, float(item.current_exposure) - roll_capital)
    payload = {
        "input_hash": stable_hash(item.to_mapping()),
        "instrument_id": item.instrument_id,
        "market_state": state,
        "probability_improvement": item.probability_improvement,
        "realized_profit_only": True,
        "floating_loss_blocks_add": float(item.floating_pnl) < 0.0,
        "data_quality_gate": not blockers,
        "listed_instrument_data_status": item.instrument_data_status or "unknown",
        "underlying_proxy_used": item.underlying_proxy_used,
        "eval_required": True,
        "evaluation_status": "not_evaluated",
        "allowed_alert": False,
        "allowed_paper": False,
        "allowed_shadow": False,
    }
    roll_id = f"roll_{stable_hash({**payload, 'action': action.value, 'as_of_time': item.as_of_time})[:20]}"
    return RollDecision(
        roll_id=roll_id,
        asset_id=item.asset_id,
        symbol=item.symbol,
        asset_type=item.asset_type,
        strategy_version=CRYPTO_ROLL_STRATEGY_VERSION,
        policy_version=ROLL_POLICY_VERSION,
        action=action.value,
        status="blocked" if blockers else "research_only",
        rationale=rationale,
        blockers=tuple(blockers),
        warnings=tuple(dict.fromkeys(warnings)),
        roll_capital=roll_capital,
        remaining_risk=remaining_risk,
        as_of_time=item.as_of_time,
        data_cutoff_time=item.data_cutoff_time,
        source_status=item.source_status,
        coverage=item.coverage,
        feature_snapshot_id=item.feature_snapshot_id,
        model_version=item.model_version,
        source_snapshot_ids=item.source_snapshot_ids,
        hard_veto=item.hard_veto,
        research_only=True,
        payload=payload,
    )


__all__ = [
    "CRYPTO_ROLL_STRATEGY_VERSION",
    "ROLL_POLICY_VERSION",
    "RollAction",
    "RollInput",
    "RollDecision",
    "ROLL_ASSET_MAP",
    "LISTED_CRYPTO_ASSET_TYPES",
    "canonical_roll_symbol",
    "evaluate_roll",
]
