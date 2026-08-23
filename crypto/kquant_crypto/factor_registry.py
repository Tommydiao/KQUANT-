from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .db.migrations import connect, migrate
from .evaluation_models import stable_hash


FACTOR_VERSION = "crypto_factor_v1.0.1"
MEME_FACTOR_VERSION = "crypto_meme_factor_v1.0.0"


@dataclass(frozen=True)
class FactorDefinition:
    factor_id: str
    factor_group: str
    formula: str
    lookback: str
    source_fields: tuple[str, ...]
    factor_version: str = FACTOR_VERSION
    status: str = "registered"

    def as_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "factor_version": self.factor_version,
            "factor_group": self.factor_group,
            "formula": self.formula,
            "lookback": self.lookback,
            "source_fields": list(self.source_fields),
            "status": self.status,
        }


CORE_FACTOR_DEFINITIONS = (
    FactorDefinition("trend_ema_reclaim", "trend", "close > ema20 and ema9 > ema20", "9/20 bars", ("close", "ema9", "ema20")),
    FactorDefinition("trend_ema_slope", "trend", "(ema20 / ema20_prev_n) - 1", "20 bars", ("ema20", "ema20_prev_n")),
    FactorDefinition("relative_strength_btc", "relative_strength", "asset_return_n - btc_return_n", "5/24 bars", ("asset_return_n", "btc_return_n")),
    FactorDefinition("relative_strength_eth", "relative_strength", "asset_return_n - eth_return_n", "5/24 bars", ("asset_return_n", "eth_return_n")),
    FactorDefinition("momentum_acceleration", "momentum", "return_fast - return_slow", "6/24 bars", ("return_fast", "return_slow")),
    FactorDefinition("volume_acceleration", "volume", "relative_volume_fast - 1", "20 bars", ("relative_volume_fast",)),
    FactorDefinition("cvd_bias", "order_flow", "cvd / max(abs(buy_volume)+abs(sell_volume), eps)", "rolling session", ("cvd", "buy_volume", "sell_volume")),
    FactorDefinition("volatility_compression", "volatility", "atr_fast / atr_slow", "14/50 bars", ("atr_fast", "atr_slow")),
    FactorDefinition("oi_price_alignment", "derivatives", "sign(price_return) == sign(oi_change)", "24 bars", ("price_return", "oi_change")),
    FactorDefinition("funding_extreme", "derivatives", "abs(funding_rate) <= policy_limit", "current", ("funding_rate",)),
    FactorDefinition("liquidity_spread", "execution", "spread_bps <= policy_limit", "current", ("spread_bps",)),
    FactorDefinition("breakout_distance", "structure", "close / range_high_n - 1", "20 bars", ("close", "range_high_n")),
)


MEME_FACTOR_DEFINITIONS = (
    FactorDefinition("meme_volume_acceleration", "meme_volume", "current_volume_5m / previous_volume_5m - 1", "adjacent 5m snapshots", ("volume_5m_usd", "previous_volume_5m_usd"), MEME_FACTOR_VERSION),
    FactorDefinition("meme_buy_pressure", "meme_order_flow", "(buys_5m - sells_5m) / (buys_5m + sells_5m)", "current 5m snapshot", ("buys_5m", "sells_5m"), MEME_FACTOR_VERSION),
    FactorDefinition("meme_liquidity_growth", "meme_liquidity", "current_liquidity_usd / previous_liquidity_usd - 1", "adjacent 5m snapshots", ("liquidity_usd", "previous_liquidity_usd"), MEME_FACTOR_VERSION),
    FactorDefinition("meme_price_momentum", "meme_momentum", "current_price_usd / previous_price_usd - 1", "adjacent 5m snapshots", ("price_usd", "previous_price_usd"), MEME_FACTOR_VERSION),
    FactorDefinition("meme_holder_growth", "meme_holders", "current_holder_count / previous_holder_count - 1", "available holder snapshots", ("holder_count", "previous_holder_count"), MEME_FACTOR_VERSION),
    FactorDefinition("meme_security_pass", "meme_security", "security_status in {passed, pass, safe}", "point-in-time security snapshot", ("security_status",), MEME_FACTOR_VERSION),
)


class FactorRegistry:
    def __init__(self, db_path: Path, definitions: tuple[FactorDefinition, ...] = CORE_FACTOR_DEFINITIONS):
        self.db_path = db_path
        self.definitions = definitions

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(item.factor_id for item in self.definitions if item.status == "registered")

    @property
    def factor_version(self) -> str:
        return self.definitions[0].factor_version if self.definitions else FACTOR_VERSION

    def validate(self, factor_ids: list[str] | tuple[str, ...]) -> list[str]:
        return sorted(set(factor_ids) - set(self.ids))

    def register(self) -> None:
        migrate(self.db_path)
        now = datetime.now(UTC).isoformat()
        with connect(self.db_path) as conn:
            for definition in self.definitions:
                conn.execute(
                    """
                    INSERT INTO crypto_factor_definitions(
                      factor_id,factor_version,factor_group,formula,lookback,
                      source_fields_json,status,created_at
                    ) VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(factor_id) DO UPDATE SET
                      factor_version=excluded.factor_version,
                      formula=excluded.formula,
                      lookback=excluded.lookback,
                      source_fields_json=excluded.source_fields_json,
                      status=excluded.status
                    """,
                    (definition.factor_id, definition.factor_version, definition.factor_group, definition.formula, definition.lookback, json.dumps(list(definition.source_fields), ensure_ascii=True), definition.status, now),
                )

    def get_snapshot(self, factor_snapshot_id: str) -> dict[str, Any] | None:
        migrate(self.db_path)
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM crypto_factor_snapshots WHERE factor_snapshot_id=?",
                (factor_snapshot_id,),
            ).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["values"] = json.loads(value.pop("values_json"))
        value["contributions"] = json.loads(value.pop("contributions_json"))
        value["missing_factor_ids"] = json.loads(value.pop("missing_factor_ids_json"))
        return value

    def latest_snapshot(self, asset_id: str) -> dict[str, Any] | None:
        migrate(self.db_path)
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT factor_snapshot_id FROM crypto_factor_snapshots WHERE asset_id=? ORDER BY as_of_time DESC, created_at DESC LIMIT 1",
                (asset_id,),
            ).fetchone()
        return self.get_snapshot(row["factor_snapshot_id"]) if row else None

    def snapshot(self, *, asset_id: str, strategy_version: str, as_of_time: str, values: dict[str, Any], contributions: dict[str, float], missing_factor_ids: list[str] | None = None) -> dict[str, Any]:
        unknown = self.validate(list(values))
        if unknown:
            raise ValueError(f"Unknown factor IDs: {', '.join(unknown)}")
        missing = sorted(set(missing_factor_ids or []))
        payload = {"asset_id": asset_id, "strategy_version": strategy_version, "factor_version": self.factor_version, "as_of_time": as_of_time, "values": values, "contributions": contributions, "missing": missing}
        digest = stable_hash(payload)
        snapshot = {
            "factor_snapshot_id": f"factor_{uuid4().hex}",
            "asset_id": asset_id,
            "strategy_version": strategy_version,
            "factor_version": self.factor_version,
            "as_of_time": as_of_time,
            "available_at": as_of_time,
            "values": values,
            "contributions": contributions,
            "missing_factor_ids": missing,
            "content_hash": digest,
        }
        migrate(self.db_path)
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO crypto_factor_snapshots(factor_snapshot_id,asset_id,strategy_version,factor_version,as_of_time,available_at,values_json,contributions_json,missing_factor_ids_json,content_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (snapshot["factor_snapshot_id"], asset_id, strategy_version, self.factor_version, as_of_time, as_of_time, json.dumps(values, ensure_ascii=True, sort_keys=True), json.dumps(contributions, ensure_ascii=True, sort_keys=True), json.dumps(missing, ensure_ascii=True), digest, datetime.now(UTC).isoformat()),
            )
        return snapshot

    def list_definitions(self) -> list[dict[str, Any]]:
        return [item.as_dict() for item in self.definitions]


def score_registered_factors(registry: FactorRegistry, values: dict[str, float | None], weights: dict[str, float]) -> dict[str, Any]:
    unknown = registry.validate(list(weights))
    if unknown:
        raise ValueError(f"Unknown factor IDs: {', '.join(unknown)}")
    contributions: dict[str, float] = {}
    missing: list[str] = []
    for factor_id, weight in weights.items():
        value = values.get(factor_id)
        if value is None:
            missing.append(factor_id)
        else:
            contributions[factor_id] = float(value) * float(weight)
    return {"score": sum(contributions.values()), "contributions": contributions, "missing_factor_ids": sorted(missing), "factor_version": registry.factor_version}


class MemeFactorRegistry(FactorRegistry):
    """Versioned DEX/MEME factor namespace kept separate from CEX factors."""

    def __init__(self, db_path: Path):
        super().__init__(db_path, definitions=MEME_FACTOR_DEFINITIONS)
