from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class StrategyManifest:
    strategy_version: str
    market_type: str
    direction: str
    signal_interval: str
    status: str
    executable: bool
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "strategy_version": self.strategy_version,
            "market_type": self.market_type,
            "direction": self.direction,
            "signal_interval": self.signal_interval,
            "status": self.status,
            "executable": self.executable,
            "notes": list(self.notes),
        }


STRATEGY_MANIFESTS: Final[tuple[StrategyManifest, ...]] = (
    StrategyManifest(
        strategy_version="crypto_spot_momentum_v2.1.0",
        market_type="spot",
        direction="long",
        signal_interval="1h_setup_5m_trigger",
        status="research_challenger",
        executable=True,
        notes=("Requires its own locked OOS PASS before Testnet admission.",),
    ),
    StrategyManifest(
        strategy_version="crypto_spot_momentum_v2.0.0",
        market_type="spot",
        direction="long",
        signal_interval="1h_setup_5m_trigger",
        status="frozen_baseline",
        executable=True,
        notes=("Execution remains blocked until the locked OOS gate passes.",),
    ),
    StrategyManifest(
        strategy_version="crypto_early_v1.0.0",
        market_type="spot",
        direction="long",
        signal_interval="1h",
        status="frozen_baseline",
        executable=True,
        notes=("Historical and testnet gates must pass before execution.",),
    ),
    StrategyManifest(
        strategy_version="crypto_roll_v1.0.0",
        market_type="spot",
        direction="long",
        signal_interval="1h",
        status="frozen_baseline",
        executable=True,
        notes=("Historical and testnet gates must pass before execution.",),
    ),
    StrategyManifest(
        strategy_version="crypto_perpetual_long_v1.0.0",
        market_type="perpetual",
        direction="long",
        signal_interval="1h",
        status="research_pending",
        executable=False,
        notes=("Requires an independent perpetual-data validation run.",),
    ),
    StrategyManifest(
        strategy_version="crypto_perpetual_long_v2.0.0",
        market_type="perpetual",
        direction="long",
        signal_interval="1h_setup_5m_trigger",
        status="research_pending",
        executable=True,
        notes=("Only independently validated and allowlisted perpetual candidates may execute.",),
    ),
    StrategyManifest(
        strategy_version="crypto_perpetual_short_v1.0.0",
        market_type="perpetual",
        direction="short",
        signal_interval="1h",
        status="not_implemented",
        executable=False,
        notes=("A long policy must never be mechanically inverted to create this strategy.",),
    ),
)


def strategy_manifest(strategy_version: str) -> StrategyManifest | None:
    return next((item for item in STRATEGY_MANIFESTS if item.strategy_version == strategy_version), None)


def list_strategy_manifests() -> list[dict[str, object]]:
    return [item.as_dict() for item in STRATEGY_MANIFESTS]
