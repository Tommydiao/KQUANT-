from __future__ import annotations

from pathlib import Path
from typing import Any


CATALOG_VERSION = "crypto_universe_v1.1.0"
DEFAULT_CEX_TIERS: dict[str, tuple[str, ...]] = {
    "CORE": ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    "MAJOR_ALT": (
        "BNBUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
        "TRXUSDT", "LTCUSDT", "BCHUSDT", "UNIUSDT", "AAVEUSDT", "NEARUSDT", "ATOMUSDT",
    ),
    "CEX_HIGH_BETA": ("SUIUSDT", "INJUSDT", "SEIUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "TIAUSDT"),
    "MEME": ("DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "WIFUSDT", "BONKUSDT", "FLOKIUSDT"),
}
DEFAULT_DEX_CHAINS = ("solana", "ethereum", "base", "bsc")
DEFAULT_CEX_SYMBOLS = tuple(symbol for values in DEFAULT_CEX_TIERS.values() for symbol in values)


def _normalise_symbol(value: Any) -> str | None:
    symbol = str(value or "").strip().upper().replace("/", "").replace("-", "")
    if not symbol or len(symbol) < 6 or not symbol.isalnum():
        return None
    return symbol


def _fallback_catalog() -> dict[str, Any]:
    return {
        "version": CATALOG_VERSION,
        "cex": {tier: list(symbols) for tier, symbols in DEFAULT_CEX_TIERS.items()},
        "dex_chains": list(DEFAULT_DEX_CHAINS),
    }


def load_universe_catalog(root_dir: Path) -> dict[str, Any]:
    """Load the versioned public watchlist, failing back to safe defaults."""

    path = root_dir / "config" / "crypto_universe.yml"
    if not path.exists():
        return _fallback_catalog()
    try:
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, ImportError):
        return _fallback_catalog()
    if not isinstance(raw, dict):
        return _fallback_catalog()
    cex: dict[str, list[str]] = {}
    raw_cex = raw.get("cex")
    if isinstance(raw_cex, dict):
        for raw_tier, raw_symbols in raw_cex.items():
            tier = str(raw_tier).strip().upper()
            if not tier or not isinstance(raw_symbols, list):
                continue
            values = [_normalise_symbol(item) for item in raw_symbols]
            cex[tier] = list(dict.fromkeys(item for item in values if item))
    if not cex:
        return _fallback_catalog()
    chains = raw.get("dex_chains")
    dex_chains = [str(item).strip().lower() for item in chains] if isinstance(chains, list) else list(DEFAULT_DEX_CHAINS)
    return {
        "version": str(raw.get("version") or CATALOG_VERSION),
        "cex": cex,
        "dex_chains": list(dict.fromkeys(item for item in dex_chains if item)),
    }


def configured_cex_symbols(root_dir: Path) -> tuple[str, ...]:
    catalog = load_universe_catalog(root_dir)
    return tuple(dict.fromkeys(symbol for values in catalog["cex"].values() for symbol in values))


def cex_symbol_tiers(root_dir: Path) -> dict[str, str]:
    catalog = load_universe_catalog(root_dir)
    result: dict[str, str] = {}
    for tier, symbols in catalog["cex"].items():
        for symbol in symbols:
            result.setdefault(symbol, tier)
    return result
