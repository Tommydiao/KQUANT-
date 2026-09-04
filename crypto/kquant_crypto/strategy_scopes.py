from __future__ import annotations

from typing import Final

from .strategy_momentum_v2 import SETUP_WEIGHTS


# These factors require fields that are not present in public spot OHLCV
# klines. They remain part of the live runtime and are deliberately excluded
# from the historical OHLCV evidence chain.
HISTORICAL_LIVE_ONLY_FACTOR_IDS: Final[tuple[str, ...]] = (
    "cvd_bias",
    "oi_price_alignment",
    "funding_extreme",
    "liquidity_spread",
)

HISTORICAL_OHLCV_SCOPE: Final[str] = "ohlcv_only_limited"
HISTORICAL_OHLCV_STRATEGY_VERSION: Final[str] = "crypto_historical_ohlcv_v1.0.0"
HISTORICAL_SPOT_OHLCV_STRATEGY_VERSION: Final[str] = "crypto_historical_spot_long_v1.0.0"
HISTORICAL_PERPETUAL_OHLCV_STRATEGY_VERSION: Final[str] = "crypto_historical_perpetual_ohlcv_long_v1.0.0"

HISTORICAL_OHLCV_WEIGHTS: Final[dict[str, float]] = {
    factor_id: float(weight)
    for factor_id, weight in SETUP_WEIGHTS.items()
    if factor_id not in HISTORICAL_LIVE_ONLY_FACTOR_IDS
}

HISTORICAL_OHLCV_LIMITATIONS: Final[tuple[str, ...]] = (
    "Public Binance spot klines provide OHLCV only for this replay.",
    "CVD, open interest, funding, and live spread factors are excluded.",
    "This is limited historical evidence and is not equivalent to the live policy.",
)

HISTORICAL_DERIVATIVE_SCOPE: Final[str] = "ohlcv_plus_derivatives_limited"
HISTORICAL_DERIVATIVE_STRATEGY_VERSION: Final[str] = "crypto_historical_derivatives_v1.0.0"
HISTORICAL_DERIVATIVE_EXCLUDED_FACTOR_IDS: Final[tuple[str, ...]] = (
    "cvd_bias",
    "liquidity_spread",
)
HISTORICAL_DERIVATIVE_WEIGHTS: Final[dict[str, float]] = {
    factor_id: float(weight)
    for factor_id, weight in SETUP_WEIGHTS.items()
    if factor_id not in HISTORICAL_DERIVATIVE_EXCLUDED_FACTOR_IDS
}
HISTORICAL_DERIVATIVE_LIMITATIONS: Final[tuple[str, ...]] = (
    "Funding and Open Interest come from a public historical REST replay.",
    "available_at is currently a source-time proxy, not an exchange publication-time proof.",
    "CVD and live spread factors remain excluded from this limited evidence chain.",
)

HISTORICAL_FUNDING_SCOPE: Final[str] = "ohlcv_plus_funding_limited"
HISTORICAL_FUNDING_STRATEGY_VERSION: Final[str] = "crypto_historical_perpetual_funding_long_v1.0.0"
HISTORICAL_FUNDING_EXCLUDED_FACTOR_IDS: Final[tuple[str, ...]] = (
    "cvd_bias",
    "oi_price_alignment",
    "liquidity_spread",
)
HISTORICAL_FUNDING_WEIGHTS: Final[dict[str, float]] = {
    factor_id: float(weight)
    for factor_id, weight in SETUP_WEIGHTS.items()
    if factor_id not in HISTORICAL_FUNDING_EXCLUDED_FACTOR_IDS
}
