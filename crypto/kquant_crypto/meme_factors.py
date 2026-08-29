from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .evaluation_models import stable_hash


MEME_FACTOR_VERSION = "crypto_meme_factor_v1.0.0"
MEME_FACTOR_WEIGHTS = {
    "meme_volume_acceleration": 20.0,
    "meme_buy_pressure": 20.0,
    "meme_liquidity_growth": 20.0,
    "meme_price_momentum": 20.0,
    "meme_holder_growth": 10.0,
    "meme_security_pass": 10.0,
}
MEME_STAGES = (
    "DISCOVERED",
    "SAFETY_PENDING",
    "EARLY_WATCH",
    "ARMED",
    "PAPER_BUY_REVIEW",
    "LIQUIDITY_RISK",
    "RUG_RISK",
    "INVALIDATED",
)


@dataclass(frozen=True)
class MemeObservation:
    asset_id: str
    as_of: str
    price_usd: float | None
    liquidity_usd: float | None
    volume_5m_usd: float | None
    buys_5m: int | None
    sells_5m: int | None
    holder_count: int | None = None
    top10_concentration: float | None = None
    security_status: str = "unknown"


@dataclass(frozen=True)
class MemeFactorSnapshot:
    asset_id: str
    as_of: str | None
    factor_version: str
    values: dict[str, float | None]
    contributions: dict[str, float]
    missing_factor_ids: tuple[str, ...]
    setup_score: float
    trigger_score: float | None
    stage: str
    blockers: tuple[dict[str, Any], ...]
    warnings: tuple[dict[str, Any], ...]
    content_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "as_of": self.as_of,
            "factor_version": self.factor_version,
            "values": self.values,
            "contributions": self.contributions,
            "missing_factor_ids": list(self.missing_factor_ids),
            "setup_score": self.setup_score,
            "trigger_score": self.trigger_score,
            "stage": self.stage,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "content_hash": self.content_hash,
        }


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous <= 0:
        return None
    return current / previous - 1.0


def _clip(value: float | None, low: float = 0.0, high: float = 1.0) -> float | None:
    if value is None:
        return None
    return max(low, min(high, value))


def compute_meme_factors(
    history: Sequence[MemeObservation],
    *,
    as_of: str | None = None,
) -> MemeFactorSnapshot:
    """Compute DEX/MEME launch factors using only observations at ``as_of``.

    The function is intentionally independent of notifications and EVAL. It
    produces transparent evidence; EVAL remains responsible for safety,
    liquidity and Paper/Shadow permission.
    """

    if not history:
        return _snapshot("", None, {}, {}, (), "DISCOVERED", ({"code": "history_missing"},), ())
    ordered = sorted((item for item in history if as_of is None or item.as_of <= as_of), key=lambda item: item.as_of)
    current = ordered[-1] if ordered else None
    if current is None:
        return _snapshot(history[0].asset_id, as_of, {}, {}, (), "DISCOVERED", ({"code": "as_of_not_available"},), ())
    previous = ordered[-2] if len(ordered) > 1 else None
    if previous is None:
        return _snapshot(current.asset_id, current.as_of, {}, {}, (), "DISCOVERED", ({"code": "insufficient_history"},), ())

    total_trades = (current.buys_5m or 0) + (current.sells_5m or 0)
    buy_pressure = ((current.buys_5m or 0) - (current.sells_5m or 0)) / total_trades if total_trades else None
    values: dict[str, float | None] = {
        "meme_volume_acceleration": _growth(current.volume_5m_usd, previous.volume_5m_usd),
        "meme_buy_pressure": buy_pressure,
        "meme_liquidity_growth": _growth(current.liquidity_usd, previous.liquidity_usd),
        "meme_price_momentum": _growth(current.price_usd, previous.price_usd),
        "meme_holder_growth": _growth(float(current.holder_count) if current.holder_count is not None else None, float(previous.holder_count) if previous.holder_count is not None else None),
        "meme_security_pass": 1.0 if current.security_status.lower() in {"passed", "pass", "safe"} else None,
    }
    missing = tuple(sorted(key for key, value in values.items() if value is None))
    contributions: dict[str, float] = {}
    for key, weight in MEME_FACTOR_WEIGHTS.items():
        value = values[key]
        if value is None:
            continue
        normalized = _clip(value if key != "meme_buy_pressure" else (value + 1.0) / 2.0)
        if normalized is not None:
            contributions[key] = normalized * weight
    setup_score = round(sum(contributions.values()), 4)
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    security = current.security_status.lower()
    liquidity_growth = values["meme_liquidity_growth"]
    if security in {"blocked", "rug_risk", "honeypot"}:
        blockers.append({"code": "security_blocked"})
    elif security not in {"passed", "pass", "safe", "live"}:
        blockers.append({"code": "security_pending"})
    if liquidity_growth is not None and liquidity_growth <= -0.50:
        blockers.append({"code": "liquidity_withdrawal"})
    if current.top10_concentration is not None and current.top10_concentration > 0.70:
        warnings.append({"code": "holder_concentration_high"})
    if current.liquidity_usd is not None and current.liquidity_usd < 50_000:
        warnings.append({"code": "liquidity_low"})

    if any(item["code"] == "liquidity_withdrawal" for item in blockers):
        stage = "LIQUIDITY_RISK"
    elif any(item["code"] == "security_blocked" for item in blockers):
        stage = "RUG_RISK"
    elif any(item["code"] == "security_pending" for item in blockers):
        stage = "SAFETY_PENDING"
    elif values.get("meme_price_momentum") is not None and values["meme_price_momentum"] < -0.20 and (values.get("meme_buy_pressure") or 0) < 0:
        stage = "INVALIDATED"
    elif setup_score >= 72 and not missing:
        stage = "PAPER_BUY_REVIEW"
    elif setup_score >= 60:
        stage = "ARMED" if not missing else "EARLY_WATCH"
    else:
        stage = "EARLY_WATCH" if setup_score >= 40 else "DISCOVERED"
    trigger_score = round(setup_score, 4) if not missing else None
    return _snapshot(current.asset_id, current.as_of, values, contributions, missing, stage, blockers, warnings, setup_score, trigger_score)


def _snapshot(
    asset_id: str,
    as_of: str | None,
    values: dict[str, float | None],
    contributions: dict[str, float],
    missing: tuple[str, ...],
    stage: str,
    blockers: Sequence[dict[str, Any]],
    warnings: Sequence[dict[str, Any]],
    setup_score: float = 0.0,
    trigger_score: float | None = None,
) -> MemeFactorSnapshot:
    payload = {
        "asset_id": asset_id,
        "as_of": as_of,
        "factor_version": MEME_FACTOR_VERSION,
        "values": values,
        "contributions": contributions,
        "missing": list(missing),
        "stage": stage,
    }
    return MemeFactorSnapshot(
        asset_id=asset_id,
        as_of=as_of,
        factor_version=MEME_FACTOR_VERSION,
        values=values,
        contributions=contributions,
        missing_factor_ids=missing,
        setup_score=round(setup_score, 4),
        trigger_score=trigger_score,
        stage=stage,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        content_hash=stable_hash(payload),
    )
