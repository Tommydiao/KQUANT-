from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


CATALOG_VERSION = "crypto_universe_v1.2.0"
DEFAULT_CEX_TIERS: dict[str, tuple[str, ...]] = {
    "CORE": ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    "MAJOR_ALT": (
        "BNBUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
        "TRXUSDT", "LTCUSDT", "BCHUSDT", "UNIUSDT", "AAVEUSDT", "NEARUSDT", "ATOMUSDT", "ZECUSDT",
    ),
    "CEX_HIGH_BETA": ("SUIUSDT", "INJUSDT", "SEIUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "TIAUSDT"),
    "MEME": ("DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "WIFUSDT", "BONKUSDT", "FLOKIUSDT", "PUMPUSDT"),
}
DEFAULT_DEX_CHAINS = ("solana", "ethereum", "base", "bsc")
DEFAULT_CEX_SYMBOLS = tuple(symbol for values in DEFAULT_CEX_TIERS.values() for symbol in values)


@dataclass(frozen=True)
class InstrumentDefinition:
    symbol: str
    venue: str
    market_type: str
    tier: str
    listed_since: str | None = None
    listing_status: str = "verify_at_runtime"
    research_status: str = "observation"
    execution_stage: str = "RESEARCH_ONLY"
    risk_fraction_cap: float = 0.01
    risk_tags: tuple[str, ...] = ()

    @property
    def instrument_id(self) -> str:
        return f"{self.venue}:{self.market_type}:{self.symbol}"

    @property
    def asset_id(self) -> str:
        base = self.symbol[:-4] if self.symbol.endswith("USDT") else self.symbol
        return f"asset:{base.lower()}"

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["instrument_id"] = self.instrument_id
        value["asset_id"] = self.asset_id
        value["risk_tags"] = list(self.risk_tags)
        return value


CANDIDATE_INSTRUMENTS: tuple[InstrumentDefinition, ...] = (
    InstrumentDefinition("ZECUSDT", "binance", "spot", "MAJOR_ALT", "2019-03-21T04:00:00+00:00", risk_fraction_cap=0.005, risk_tags=("privacy_asset", "policy_sensitive"), research_status="candidate"),
    InstrumentDefinition("ARBUSDT", "binance", "spot", "CEX_HIGH_BETA", "2023-03-23T17:00:00+00:00", risk_fraction_cap=0.005, risk_tags=("high_beta",), research_status="candidate"),
    InstrumentDefinition("PUMPUSDT", "binance", "spot", "MEME", "2025-09-11T12:30:00+00:00", risk_fraction_cap=0.0025, risk_tags=("seed_tag", "meme", "high_volatility"), research_status="candidate"),
    InstrumentDefinition("HYPEUSDT", "binance", "perpetual", "CEX_HIGH_BETA", "2025-05-30T10:30:00+00:00", risk_fraction_cap=0.0025, risk_tags=("perpetual_only", "high_beta", "deleveraging_sensitive"), research_status="candidate"),
)


def _normalise_symbol(value: Any) -> str | None:
    symbol = str(value or "").strip().upper().replace("/", "").replace("-", "")
    if not symbol or len(symbol) < 6 or not symbol.isalnum():
        return None
    return symbol


def _fallback_catalog() -> dict[str, Any]:
    return {
        "version": CATALOG_VERSION,
        "cex": {tier: list(symbols) for tier, symbols in DEFAULT_CEX_TIERS.items()},
        "instruments": [item.as_dict() for item in CANDIDATE_INSTRUMENTS],
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
    instruments: list[dict[str, Any]] = []
    raw_instruments = raw.get("instruments")
    if isinstance(raw_instruments, list):
        for item in raw_instruments:
            if not isinstance(item, dict):
                continue
            symbol = _normalise_symbol(item.get("symbol"))
            venue = str(item.get("venue") or "").strip().lower()
            market_type = str(item.get("market_type") or "").strip().lower()
            tier = str(item.get("tier") or "").strip().upper()
            if not symbol or venue != "binance" or market_type not in {"spot", "perpetual"} or not tier:
                continue
            try:
                risk_cap = max(0.0, min(0.01, float(item.get("risk_fraction_cap", 0.01))))
            except (TypeError, ValueError):
                continue
            definition = InstrumentDefinition(
                symbol=symbol,
                venue=venue,
                market_type=market_type,
                tier=tier,
                listed_since=str(item.get("listed_since") or "").strip() or None,
                listing_status=str(item.get("listing_status") or "verify_at_runtime"),
                research_status=str(item.get("research_status") or "observation"),
                execution_stage=str(item.get("execution_stage") or "RESEARCH_ONLY").upper(),
                risk_fraction_cap=risk_cap,
                risk_tags=tuple(str(tag).strip().lower() for tag in item.get("risk_tags", []) if str(tag).strip()),
            )
            instruments.append(definition.as_dict())
    if not instruments:
        instruments = [item.as_dict() for item in CANDIDATE_INSTRUMENTS]
    return {
        "version": str(raw.get("version") or CATALOG_VERSION),
        "cex": cex,
        "instruments": instruments,
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


def configured_instruments(root_dir: Path) -> tuple[InstrumentDefinition, ...]:
    """Return all spot observations plus explicit candidate market contracts."""

    catalog = load_universe_catalog(root_dir)
    tiers = cex_symbol_tiers(root_dir)
    values: dict[str, InstrumentDefinition] = {}
    for symbol in configured_cex_symbols(root_dir):
        item = InstrumentDefinition(symbol, "binance", "spot", tiers.get(symbol, "CEX_HIGH_BETA"))
        values[item.instrument_id] = item
    for raw in catalog.get("instruments", []):
        item = InstrumentDefinition(
            symbol=str(raw["symbol"]),
            venue=str(raw["venue"]),
            market_type=str(raw["market_type"]),
            tier=str(raw["tier"]),
            listed_since=raw.get("listed_since"),
            listing_status=str(raw.get("listing_status") or "verify_at_runtime"),
            research_status=str(raw.get("research_status") or "observation"),
            execution_stage=str(raw.get("execution_stage") or "RESEARCH_ONLY"),
            risk_fraction_cap=float(raw.get("risk_fraction_cap", 0.01)),
            risk_tags=tuple(raw.get("risk_tags") or ()),
        )
        values[item.instrument_id] = item
    return tuple(values[key] for key in sorted(values))


def candidate_instrument(symbol: str, market_type: str | None = None, *, root_dir: Path | None = None) -> InstrumentDefinition | None:
    normalized = _normalise_symbol(symbol)
    if not normalized:
        return None
    values = configured_instruments(root_dir) if root_dir is not None else CANDIDATE_INSTRUMENTS
    return next(
        (
            item for item in values
            if item.symbol == normalized and (market_type is None or item.market_type == str(market_type).lower())
            and item.research_status == "candidate"
        ),
        None,
    )


def candidate_strategy_version(instrument: InstrumentDefinition) -> str:
    return "crypto_perpetual_long_v2.0.0" if instrument.market_type == "perpetual" else "crypto_spot_momentum_v2.0.0"
