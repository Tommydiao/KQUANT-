"""Read-only, reproducible historical inputs for the research candidate.

Only market-specific compacted closed candles are authoritative. Gaps are never
filled: consumers must reset indicators and handle unverifiable position paths.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

if TYPE_CHECKING:
    from .strategy_dual_mode_v1 import Bar

DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
DAY = 86400
WARMUP = 250 * 3600
OHLC_REL_TOL = 1e-8
OHLC_ABS_TOL = 1e-8
SCHEMA = pa.schema([
    ("start", pa.int64()), *[(x, pa.float64()) for x in ("open", "high", "low", "close", "volume")],
    ("available_at", pa.int64()), ("availability_basis", pa.string()),
    ("received_at", pa.string()), ("provider_status", pa.string()),
])


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _now() -> int:
    return int(datetime.now(UTC).timestamp())


def _coverage(rows: list[dict], step: int, start: int, end: int) -> dict:
    times = [r["start"] for r in rows]
    gaps, segments = [], []
    cursor = start
    segment_start = previous = None
    for stamp in times:
        if stamp > cursor:
            gaps.append({"start": cursor, "end": stamp, "missing_bars": (stamp - cursor) // step})
        if previous is None or stamp != previous + step:
            if previous is not None:
                segments.append({"start": segment_start, "end": previous + step, "bars": (previous + step - segment_start) // step})
            segment_start = stamp
        previous = stamp
        cursor = stamp + step
    if previous is not None:
        segments.append({"start": segment_start, "end": previous + step, "bars": (previous + step - segment_start) // step})
    if cursor < end:
        gaps.append({"start": cursor, "end": end, "missing_bars": (end - cursor) // step})
    return {"count": len(rows), "first_start": times[0] if times else None,
            "last_start": times[-1] if times else None, "gaps": gaps, "continuous_segments": segments}


def _validate(raw: list[tuple], step: int) -> tuple[list[dict], dict]:
    grouped: dict[int, list[tuple]] = {}
    for row in raw:
        grouped.setdefault(int(row[0]), []).append(row)
    result, excluded = [], []
    exact = conflicts = 0
    for stamp, variants in sorted(grouped.items()):
        prices = {tuple(v[1:6]) for v in variants}
        if len(prices) != 1:
            conflicts += 1
            excluded.append({"start": stamp, "reason": "conflicting_duplicate", "rows": len(variants)})
            continue
        exact += len(variants) - 1
        # Deterministic provenance selection; no claim that a replay saw receipts.
        row = min(variants, key=lambda v: (str(v[6] or ""), str(v[7] or "")))
        values = row[1:6]
        if (stamp % step or any(v is None or not math.isfinite(v) for v in values)
                or min(values[:4]) <= 0 or values[4] < 0
                or values[2] > min(values[0], values[3])
                or values[1] < max(values[0], values[3]) or values[2] > values[1]):
            excluded.append({"start": stamp, "reason": "invalid_ohlcv_or_timestamp"})
            continue
        result.append(dict(zip(("start", "open", "high", "low", "close", "volume"), row[:6]),
                           available_at=stamp + step, availability_basis="assumed_close_historical_replay",
                           received_at=None if row[6] is None else str(row[6]),
                           provider_status=None if row[7] is None else str(row[7])))
    return result, {"exact_duplicate_rows": exact, "conflicting_duplicate_timestamps": conflicts, "excluded": excluded}


def freeze_dataset(data_dir: Path, output_dir: Path, symbols: Sequence[str] = DEFAULT_SYMBOLS,
                   *, as_of: int | None = None) -> dict:
    """Freeze 365 complete days if available, otherwise a 180-day calendar.

    ``as_of`` is an optional UTC epoch cutoff for reproducible tests/research.
    Gappy inputs may support research after contiguous warmup, but cannot pass
    full-window continuity acceptance. Eligibility never selects or trims rows. An
    existing output directory must be empty; frozen artifacts are never replaced.
    """
    symbols = tuple(dict.fromkeys(str(s).upper() for s in symbols))
    if not symbols or any(not re.fullmatch(r"[A-Z0-9]+", s) for s in symbols):
        raise ValueError("symbols must be nonempty alphanumeric identifiers")
    data_dir, output_dir = Path(data_dir).resolve(), Path(output_dir).resolve()
    if output_dir == data_dir or output_dir.is_relative_to(data_dir):
        raise ValueError("output must be outside the read-only data directory")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("freeze output is not empty")
    now = _now() if as_of is None else int(as_of)
    paths = {tf: data_dir / "market" / "_compacted" / f"closed_klines_spot_{tf}.parquet" for tf in ("5m", "1h")}
    source_hashes = {tf: _sha(p) for tf, p in paths.items() if p.exists()}
    bounds, queries = {}, 0
    placeholders = ",".join("?" for _ in symbols)
    # Predicates are applied in SQL before materialization; there is no row cap.
    select = f"""SELECT upper(split_part(instrument_id, ':', -1)) AS symbol,
        epoch(TRY_CAST(source_time AS TIMESTAMPTZ)) AS stamp,
        TRY_CAST(open AS DOUBLE) AS open, TRY_CAST(high AS DOUBLE) AS high,
        TRY_CAST(low AS DOUBLE) AS low, TRY_CAST(close AS DOUBLE) AS close,
        TRY_CAST(volume AS DOUBLE) AS volume, received_at, provider_status
        FROM read_parquet(?) WHERE venue='binance' AND market_type='spot'
        AND interval=? AND upper(split_part(instrument_id, ':', -1)) IN ({placeholders})"""
    all_rows = {s: {} for s in symbols}
    quality = {s: {} for s in symbols}
    raw_counts = {}
    with duckdb.connect(":memory:") as conn:
        for tf, step in (("5m", 300), ("1h", 3600)):
            if not paths[tf].exists():
                continue
            params = [str(paths[tf]), tf, *symbols]
            summary = conn.execute(
                f"""SELECT symbol,
                min(stamp) FILTER (WHERE stamp + ? <= ?),
                max(stamp) FILTER (WHERE stamp + ? <= ?),
                count(*) FILTER (WHERE stamp IS NULL OR NOT isfinite(stamp)
                    OR stamp < 0 OR stamp != floor(stamp))
                FROM ({select}) GROUP BY symbol""",
                [step, now, step, now, *params]).fetchall()
            if any(invalid for _, _, _, invalid in summary):
                raise ValueError(f"invalid source timestamp in authoritative {tf} snapshot")
            bounds[tf] = {s: (lo, hi) for s, lo, hi, _ in summary if hi is not None}
            queries += 1
        maxima = [int(v[1]) + (300 if tf == "5m" else 3600)
                  for tf, entries in bounds.items() for v in entries.values()]
        end = min([now, *maxima]) // DAY * DAY
        earliest = end - 365 * DAY - WARMUP
        for tf, step in (("5m", 300), ("1h", 3600)):
            grouped = {s: [] for s in symbols}
            if paths[tf].exists():
                rows = conn.execute(f"SELECT * FROM ({select}) WHERE stamp >= ? AND stamp + ? <= ? ORDER BY symbol, stamp",
                                    [str(paths[tf]), tf, *symbols, earliest, step, end]).fetchall()
                queries += 1
                for symbol, stamp, *rest in rows:
                    if stamp != int(stamp):
                        raise ValueError("fractional candle timestamp")
                    grouped[symbol].append((int(stamp), *rest))
            raw_counts[tf] = sum(map(len, grouped.values()))
            for symbol in symbols:
                all_rows[symbol][tf], quality[symbol][tf] = _validate(grouped[symbol], step)
    for tf, digest in source_hashes.items():
        if _sha(paths[tf]) != digest:
            raise RuntimeError("source snapshot changed during freeze; retry")
    for symbol in symbols:
        five = {r["start"]: r for r in all_rows[symbol]["5m"]}
        hours = []
        for hour in all_rows[symbol]["1h"]:
            children = [five.get(hour["start"] + n * 300) for n in range(12)]
            reason = None
            if any(c is None for c in children):
                reason = "incomplete_12x5m"
            else:
                expected = (children[0]["open"], max(c["high"] for c in children),
                            min(c["low"] for c in children), children[-1]["close"])
                if any(not math.isclose(hour[k], value, rel_tol=OHLC_REL_TOL, abs_tol=OHLC_ABS_TOL)
                       for k, value in zip(("open", "high", "low", "close"), expected)):
                    reason = "hour_ohlc_mismatch"
            if reason:
                quality[symbol]["1h"]["excluded"].append({"start": hour["start"], "reason": reason})
            else:
                hours.append(hour)
        all_rows[symbol]["1h"] = hours
    full_year = all(not _coverage(all_rows[s][tf], step, earliest, end)["gaps"]
                    for s in symbols for tf, step in (("5m", 300), ("1h", 3600)))
    days = 365 if full_year else 180
    start = end - days * DAY
    warmup_start = start - WARMUP
    manifest = {"schema_version": 1, "symbols": list(symbols), "as_of": now,
                "window": {"start": start, "end": end, "end_exclusive": True, "days": days, "warmup_start": warmup_start},
                "source": "binance:spot:market_specific_compacted_closed_klines",
                "sources": {tf: {"path": str(p), "sha256": source_hashes.get(tf), "bounds": bounds.get(tf, {})} for tf, p in paths.items()},
                "exposure": {"status": "exposed", "basis": "unknown_treated_as_exposed", "independent_holdout": False,
                             "performance_status": "PERFORMANCE_UNPROVEN"},
                "original_historical_data_gate": {"status": "NOT_EVALUATED", "modified": False, "scope": "original_31_symbol_gate_unchanged"},
                "provenance": {"available_at": "assumed candle close for historical replay, not actual receipt",
                               "received_at": "preserved source receipt/ingestion time, including archive imports",
                               "duplicate_policy": "exact OHLCV collapsed, conflicts excluded", "source_deduplication": "upstream compaction may already have removed duplicates",
                               "gap_policy": "preserve; kernel must reset and rewarm",
                               "missing_hour_policy": "continue valid 5m; pass no hourly bar at missing hour close so kernel invalidates",
                               "ohlc_relative_tolerance": OHLC_REL_TOL,
                               "ohlc_absolute_tolerance": OHLC_ABS_TOL},
                "files": {}, "quality": quality, "candidate_data_eligibility": {},
                "profile": {"sql_queries": queries, "raw_rows_read": raw_counts, "row_limit": None,
                            "predicate_pushdown": ["venue", "market_type", "interval", "symbols", "time_window"],
                            "duckdb_version": duckdb.__version__, "pyarrow_version": pa.__version__}}
    output_dir.mkdir(parents=True, exist_ok=True)
    for symbol in symbols:
        manifest["files"][symbol] = {}
        reasons = []
        for tf, step in (("5m", 300), ("1h", 3600)):
            rows = [r for r in all_rows[symbol][tf] if r["start"] >= warmup_start]
            coverage = _coverage(rows, step, warmup_start, end)
            quality[symbol][tf]["coverage"] = coverage
            if coverage["gaps"]:
                reasons.append(f"{tf}_history_or_warmup_gaps")
            path = output_dir / f"{symbol}_{tf}.parquet"
            with path.open("xb") as stream:
                pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), stream, compression="zstd", row_group_size=65536)
            manifest["files"][symbol][tf] = {"path": path.name, "sha256": _sha(path), "rows": len(rows)}
        # Each retained hour was checked against 12 consecutive valid 5m bars.
        # Thus a continuous hourly segment also proves the overlapping 5m run.
        usable_segments = [
            {"start": segment["start"], "end": segment["end"],
             "bars_1h": segment["bars"], "bars_5m": segment["bars"] * 12,
             "warmup_complete_at": segment["start"] + WARMUP}
            for segment in quality[symbol]["1h"]["coverage"]["continuous_segments"]
            if segment["bars"] >= 250 and segment["bars"] * 12 >= 100
        ]
        continuous = not reasons
        research_eligible = bool(usable_segments)
        if not research_eligible:
            reasons.append("no_contiguous_250h_and_100x5m_warmup_segment")
        latest = bounds.get("5m", {}).get(symbol)
        latest_close = int(latest[1]) + 300 if latest else None
        expected_close = now // 300 * 300
        fresh = latest_close is not None and (latest_close >= expected_close or (now - expected_close <= 30 and latest_close >= expected_close - 300))
        manifest["candidate_data_eligibility"][symbol] = {
            "historical": {"eligible": research_eligible,
                           "status": ("ELIGIBLE" if continuous else "PARTIAL") if research_eligible else "BLOCKED",
                           "continuous": continuous, "formal_acceptance_eligible": continuous and research_eligible,
                           "eligibility_scope": "research_only", "usable_segments": usable_segments,
                           "reasons": reasons},
            "freshness": {"eligible": fresh, "status": "FRESH" if fresh else "STALE_OR_MISSING", "latest_source_close": latest_close,
                          "evaluated_at": now, "grace_seconds": 30, "actual_receipt_verified": False},
            "execution_admission": False}
    manifest["manifest_hash"] = hashlib.sha256(_canonical(manifest)).hexdigest()
    with (output_dir / "data_manifest.json").open("xb") as stream:
        stream.write(_canonical(manifest) + b"\n")
    return manifest


def load_dataset(manifest_path: Path) -> dict[str, dict[str, list[Bar]]]:
    """Verify the frozen manifest/files before constructing kernel Bar objects."""
    from .strategy_dual_mode_v1 import Bar

    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = manifest.pop("manifest_hash", None)
    if digest != hashlib.sha256(_canonical(manifest)).hexdigest():
        raise ValueError("manifest hash mismatch")
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported dataset schema")
    output = {}
    for symbol in manifest["symbols"]:
        output[symbol] = {}
        for tf in ("5m", "1h"):
            entry = manifest["files"][symbol][tf]
            path = (manifest_path.parent / entry["path"]).resolve()
            if not path.is_relative_to(manifest_path.parent) or _sha(path) != entry["sha256"]:
                raise ValueError("frozen file path/hash mismatch")
            rows = pq.read_table(path).to_pylist()
            if len(rows) != entry["rows"]:
                raise ValueError("frozen row count mismatch")
            output[symbol][tf] = [Bar(**{k: row[k] for k in ("start", "open", "high", "low", "close", "volume")}) for row in rows]
    return output
