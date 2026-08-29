from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from .backtest import BacktestBar
from .derivative_dataset import align_derivatives_to_bars, load_derivative_dataset
from .evaluation_models import stable_hash
from .parquet_store import ParquetMarketStore
from .validation import ValidationSeries


@dataclass(frozen=True)
class ParquetValidationDataset:
    series: tuple[ValidationSeries, ...]
    excluded: tuple[dict[str, Any], ...]
    coverage: dict[str, Any]


def _bar(row: dict[str, Any], payload: dict[str, Any]) -> BacktestBar | None:
    try:
        return BacktestBar(
            start_time=str(row["source_time"]),
            open=float(payload["open"]),
            high=float(payload["high"]),
            low=float(payload["low"]),
            close=float(payload["close"]),
            volume=float(payload.get("volume") or 0.0),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _interval_minutes(interval: str) -> int:
    value = str(interval).strip().lower()
    if value.endswith("m"):
        return max(1, int(value[:-1]))
    if value.endswith("h"):
        return max(1, int(value[:-1]) * 60)
    if value.endswith("d"):
        return max(1, int(value[:-1]) * 1440)
    raise ValueError(f"Unsupported bar interval: {interval}")


def _aggregate_bars(bars: Sequence[BacktestBar], interval: str) -> tuple[BacktestBar, ...]:
    minutes = _interval_minutes(interval)
    if minutes == 1:
        return tuple(bars)
    buckets: dict[int, list[BacktestBar]] = {}
    for bar in bars:
        try:
            parsed = datetime.fromisoformat(bar.start_time.replace("Z", "+00:00"))
        except ValueError:
            continue
        parsed = (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)
        epoch_minutes = int(parsed.timestamp() // 60)
        bucket = epoch_minutes - epoch_minutes % minutes
        buckets.setdefault(bucket, []).append(bar)
    output: list[BacktestBar] = []
    for bucket, values in sorted(buckets.items()):
        ordered = sorted(values, key=lambda item: item.start_time)
        start_time = datetime.fromtimestamp(bucket * 60, UTC).isoformat()
        output.append(BacktestBar(
            start_time=start_time,
            open=ordered[0].open,
            high=max(item.high for item in ordered),
            low=min(item.low for item in ordered),
            close=ordered[-1].close,
            volume=sum(item.volume for item in ordered),
        ))
    return tuple(output)


def load_parquet_validation_dataset(
    data_dir: Path,
    *,
    symbols: tuple[str, ...] | list[str] | None = None,
    interval: str = "1m",
    min_bars: int = 55,
    limit: int = 250_000,
    include_derivatives: bool = False,
) -> ParquetValidationDataset:
    """Build a PIT validation dataset from closed, persisted market events.

    Only Binance spot Parquet rows explicitly marked as closed K lines are
    eligible. The loader never falls back to Yahoo, current universe
    membership, forming candles, or synthetic bars.
    """

    wanted = {str(item).upper() for item in (symbols or ()) if str(item).strip()}
    store = ParquetMarketStore(data_dir)
    requested_interval = str(interval).strip().lower()
    native_compacted = store.compacted_closed_kline_path_for(requested_interval)
    use_native_interval = requested_interval != "1m" and native_compacted.exists()
    compacted = native_compacted if use_native_interval else store.compacted_closed_kline_path
    storage_mode = "raw_events"
    compacted_manifest: dict[str, Any] | None = None
    source_interval = requested_interval if use_native_interval or requested_interval == "1m" else "1m"
    if compacted.exists():
        import duckdb

        try:
            compacted_manifest = json.loads(
                store.compacted_closed_kline_manifest_path_for(source_interval).read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            compacted_manifest = None

        with duckdb.connect(database=":memory:") as conn:
            result = conn.execute(
                """
                SELECT asset_id, venue, instrument_id, market_type, source_time,
                       received_at, provider_status, interval, open, high, low,
                       close, volume
                FROM read_parquet(?)
                WHERE venue = 'binance' AND market_type = 'spot' AND interval = ?
                ORDER BY instrument_id, source_time
                LIMIT ?
                """,
                [[str(compacted)], source_interval, max(1, min(limit, 1_000_000))],
            )
            columns = [item[0] for item in result.description]
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
        storage_mode = "compacted_closed_klines"
    elif store.file_count_estimate() > 5_000:
        return ParquetValidationDataset(
            series=(),
            excluded=(),
            coverage={
                "source": "parquet:binance:spot",
                "storage_mode": "compaction_required",
                "interval": interval,
                "requested_symbols": sorted(wanted),
                "raw_rows_read": 0,
                "eligible_series_count": 0,
                "excluded_series_count": 0,
                "eligible_symbols": [],
                "excluded": [],
                "file_count_estimate": store.file_count_estimate(),
                "dataset_hash": None,
                "reason": "raw event file count exceeds the synchronous validation scan budget; run compact_crypto_klines.py",
            },
        )
    else:
        rows = store.query(venue="binance", market_type="spot", limit=max(1, min(limit, 1_000_000)))
    grouped: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if storage_mode == "raw_events" and str(row.get("event_type") or "") != "kline":
            continue
        instrument_id = str(row.get("instrument_id") or "")
        symbol = instrument_id.rsplit(":", 1)[-1].upper()
        if wanted and symbol not in wanted:
            continue
        if storage_mode == "compacted_closed_klines":
            payload = {
                "interval": row.get("interval"),
                "closed": True,
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
            }
        else:
            try:
                payload = json.loads(row.get("payload_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if str(payload.get("interval") or "") not in {source_interval, source_interval.removesuffix("m"), source_interval.upper()}:
                continue
            if not bool(payload.get("closed")):
                continue
        source_time = str(row.get("source_time") or "")
        dedup_key = (instrument_id, source_time)
        if not source_time or dedup_key in seen:
            continue
        seen.add(dedup_key)
        value = _bar(row, payload)
        if value is None:
            continue
        item = grouped.setdefault(instrument_id, {
            "asset_id": str(row.get("asset_id") or ""),
            "symbol": symbol,
            "bars": [],
        })
        item["bars"].append(value)

    for item in grouped.values():
        item["bars"].sort(key=lambda value: value.start_time)
        item["bars"] = list(_aggregate_bars(item["bars"], interval))

    benchmark_map: dict[str, tuple[BacktestBar, ...]] = {}
    for key in ("BTCUSDT", "ETHUSDT"):
        match = next((item for item in grouped.values() if item["symbol"] == key), None)
        if match:
            benchmark_map[key.removesuffix("USDT")] = tuple(match["bars"])

    derivative_dataset = load_derivative_dataset(data_dir, symbols=wanted) if include_derivatives else None
    eligible: list[ValidationSeries] = []
    excluded: list[dict[str, Any]] = []
    for instrument_id, item in sorted(grouped.items(), key=lambda pair: pair[1]["symbol"]):
        bars = tuple(item["bars"])
        reason = None
        if len(bars) < max(1, int(min_bars)):
            reason = "insufficient_closed_bars"
        elif not item["asset_id"]:
            reason = "asset_identity_missing"
        if reason:
            excluded.append({
                "instrument_id": instrument_id,
                "symbol": item["symbol"],
                "bars": len(bars),
                "reason": reason,
            })
            continue
        eligible.append(ValidationSeries(
            asset_id=item["asset_id"],
            symbol=item["symbol"],
            bars=bars,
            benchmark_bars=dict(benchmark_map),
            instrument_id=instrument_id,
            asset_type="crypto_spot" if str(instrument_id).startswith("binance:spot:") else "",
            instrument_data_status="actual" if str(instrument_id).startswith("binance:spot:") else "",
            derivative_series=(
                align_derivatives_to_bars(bars, derivative_dataset.for_symbol(item["symbol"]))
                if derivative_dataset is not None
                else None
            ),
        ))

    coverage = {
        "source": "parquet:binance:spot",
        "storage_mode": storage_mode,
        "compacted_manifest": compacted_manifest,
        "interval": interval,
        "source_interval": source_interval,
        "requested_symbols": sorted(wanted),
        "raw_rows_read": len(rows),
        "closed_bar_count": sum(len(item["bars"]) for item in grouped.values()),
        "eligible_series_count": len(eligible),
        "excluded_series_count": len(excluded),
        "eligible_symbols": [item.symbol for item in eligible],
        "excluded": excluded,
        "derivative_coverage": derivative_dataset.coverage if derivative_dataset is not None else None,
        "dataset_hash": stable_hash({
            "source": "parquet:binance:spot",
            "interval": interval,
            "series": [
                {
                    "asset_id": item.asset_id,
                    "symbol": item.symbol,
                    "bars": [bar.__dict__ for bar in item.bars],
                    "derivative_series": list(item.derivative_series or ()),
                }
                for item in eligible
            ],
        }),
    }
    return ParquetValidationDataset(tuple(eligible), tuple(excluded), coverage)
