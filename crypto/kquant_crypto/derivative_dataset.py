from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .backtest import BacktestBar
from .parquet_store import ParquetMarketStore


@dataclass(frozen=True)
class DerivativeSnapshot:
    instrument_id: str
    symbol: str
    event_type: str
    source_time: str
    available_at: str
    received_at: str
    funding_rate: float | None
    open_interest: float | None
    open_interest_value: float | None
    provenance: str


@dataclass(frozen=True)
class DerivativeDataset:
    snapshots: tuple[DerivativeSnapshot, ...]
    coverage: dict[str, Any]

    def for_symbol(self, symbol: str) -> tuple[DerivativeSnapshot, ...]:
        wanted = str(symbol).strip().upper()
        return tuple(item for item in self.snapshots if item.symbol == wanted)


def _as_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def load_derivative_dataset(
    data_dir: Path,
    *,
    symbols: Iterable[str] | None = None,
    limit: int = 500_000,
) -> DerivativeDataset:
    """Load the immutable derivative snapshot, never the high-volume raw stream."""

    store = ParquetMarketStore(data_dir)
    path = store.compacted_derivative_path
    wanted = {str(item).strip().upper() for item in (symbols or ()) if str(item).strip()}
    if not path.exists():
        return DerivativeDataset((), {
            "status": "unavailable",
            "source": "parquet:binance:perpetual:derivative_snapshots",
            "snapshot_path": str(path),
            "requested_symbols": sorted(wanted),
            "snapshot_count": 0,
            "reason": "run compact_crypto_derivatives.py before derivative replay",
        })

    import duckdb

    with duckdb.connect(database=":memory:") as conn:
        result = conn.execute(
            """
            SELECT instrument_id, event_type, source_time, available_at,
                   received_at, funding_rate, open_interest,
                   open_interest_value, provenance
            FROM read_parquet(?)
            ORDER BY instrument_id, source_time, event_type
            LIMIT ?
            """,
            [[str(path)], max(1, min(int(limit), 2_000_000))],
        )
        rows = result.fetchall()

    snapshots: list[DerivativeSnapshot] = []
    for row in rows:
        instrument_id, event_type, source_time, available_at, received_at, funding_rate, open_interest, open_interest_value, provenance = row
        symbol = str(instrument_id or "").rsplit(":", 1)[-1].upper()
        if wanted and symbol not in wanted:
            continue
        if not instrument_id or not source_time or not available_at:
            continue
        snapshots.append(DerivativeSnapshot(
            instrument_id=str(instrument_id),
            symbol=symbol,
            event_type=str(event_type),
            source_time=str(source_time),
            available_at=str(available_at),
            received_at=str(received_at),
            funding_rate=_number(funding_rate),
            open_interest=_number(open_interest),
            open_interest_value=_number(open_interest_value),
            provenance=str(provenance or "unknown"),
        ))

    manifest: dict[str, Any] | None = None
    try:
        value = json.loads(store.compacted_derivative_manifest_path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            manifest = value
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        manifest = None
    coverage = {
        "status": "available" if snapshots else "empty",
        "source": "parquet:binance:perpetual:derivative_snapshots",
        "snapshot_path": str(path),
        "requested_symbols": sorted(wanted),
        "symbols": sorted({item.symbol for item in snapshots}),
        "snapshot_count": len(snapshots),
        "event_types": sorted({item.event_type for item in snapshots}),
        "provenance": sorted({item.provenance for item in snapshots}),
        "min_source_time": min((item.source_time for item in snapshots), default=None),
        "max_source_time": max((item.source_time for item in snapshots), default=None),
        "availability_contract": "available_at is a source-time proxy; not an exchange publication-time proof",
        "manifest": manifest,
    }
    return DerivativeDataset(tuple(snapshots), coverage)


def align_derivatives_to_bars(
    bars: Sequence[BacktestBar],
    snapshots: Sequence[DerivativeSnapshot],
) -> tuple[Mapping[str, float | None], ...]:
    """Carry only derivative observations available at each closed bar.

    The compacted snapshot currently uses source time as an explicit
    availability proxy. Both timestamps are still checked, so a future source
    observation can never be used for an earlier bar.
    """

    ordered = sorted(
        snapshots,
        key=lambda item: (
            _as_datetime(item.available_at) or datetime.max.replace(tzinfo=UTC),
            _as_datetime(item.source_time) or datetime.max.replace(tzinfo=UTC),
        ),
    )
    output: list[Mapping[str, float | None]] = []
    cursor = 0
    funding_rate: float | None = None
    open_interest: float | None = None
    oi_change: float | None = None
    for bar in bars:
        bar_time = _as_datetime(bar.start_time)
        if bar_time is None:
            output.append({})
            continue
        while cursor < len(ordered):
            item = ordered[cursor]
            source_time = _as_datetime(item.source_time)
            available_at = _as_datetime(item.available_at)
            if source_time is None or available_at is None:
                cursor += 1
                continue
            if available_at > bar_time or source_time > bar_time:
                break
            if item.event_type == "funding_rate" and item.funding_rate is not None:
                funding_rate = item.funding_rate
            elif item.event_type == "open_interest" and item.open_interest is not None:
                if open_interest not in (None, 0.0):
                    oi_change = item.open_interest / open_interest - 1.0
                open_interest = item.open_interest
            cursor += 1
        output.append({
            "funding_rate": funding_rate,
            "oi_change": oi_change,
        })
    return tuple(output)
