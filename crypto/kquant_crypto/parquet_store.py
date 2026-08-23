from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .market_models import NormalizedMarketEvent


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)


class ParquetMarketStore:
    """Append-only event store partitioned by venue, market and symbol/date."""

    def __init__(self, root: Path):
        self.root = root / "market"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.root / ".writer.lock"
        self._coverage_index_path = self.root / "_coverage_index.json"
        self._compacted_dir = self.root / "_compacted"
        self._compacted_kline_path = self._compacted_dir / "closed_klines.parquet"
        self._compacted_manifest_path = self._compacted_dir / "closed_klines.manifest.json"
        self._compacted_derivative_path = self._compacted_dir / "derivative_snapshots.parquet"
        self._compacted_derivative_manifest_path = self._compacted_dir / "derivative_snapshots.manifest.json"

    @property
    def compacted_closed_kline_path(self) -> Path:
        return self._compacted_kline_path

    def compacted_closed_kline_path_for(self, interval: str) -> Path:
        """Return the immutable closed-K-line snapshot for one interval."""

        normalized = str(interval).strip().lower()
        if normalized == "1m":
            return self._compacted_kline_path
        return self._compacted_dir / f"closed_klines_{_safe(normalized)}.parquet"

    @property
    def compacted_closed_kline_manifest_path(self) -> Path:
        return self._compacted_manifest_path

    def compacted_closed_kline_manifest_path_for(self, interval: str) -> Path:
        normalized = str(interval).strip().lower()
        if normalized == "1m":
            return self._compacted_manifest_path
        return self._compacted_dir / f"closed_klines_{_safe(normalized)}.manifest.json"

    @property
    def compacted_derivative_path(self) -> Path:
        return self._compacted_derivative_path

    @property
    def compacted_derivative_manifest_path(self) -> Path:
        return self._compacted_derivative_manifest_path

    def file_count_estimate(self) -> int:
        """Return a cheap count from the index without recursively scanning files."""

        return int(self._load_coverage_index().get("indexed_file_count", 0))

    def _load_coverage_index(self) -> dict[str, Any]:
        if not self._coverage_index_path.exists():
            return {}
        try:
            value = json.loads(self._coverage_index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @contextmanager
    def _writer_lock(self):
        """Serialize writers and keep partial Parquet files invisible."""

        self._lock_path.touch(exist_ok=True)
        handle = self._lock_path.open("r+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.05)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def _partition(self, event: NormalizedMarketEvent) -> Path:
        day = event.source_time[:10]
        symbol = _safe(event.instrument_id.rsplit(":", 1)[-1])
        path = self.root / f"venue={_safe(event.venue)}" / f"market_type={_safe(event.market_type)}" / f"symbol={symbol}" / f"date={day}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_events(self, events: Iterable[NormalizedMarketEvent]) -> list[Path]:
        import pyarrow as pa
        import pyarrow.parquet as pq

        grouped: dict[Path, list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            grouped[self._partition(event)].append({
                "asset_id": event.asset_id,
                "venue": event.venue,
                "instrument_id": event.instrument_id,
                "market_type": event.market_type,
                "event_type": event.event_type,
                "source_time": event.source_time,
                "received_at": event.received_at,
                "sequence": event.sequence,
                "provider_status": event.provider_status,
                "content_hash": event.content_hash,
                "payload_json": json.dumps(event.payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            })
        written: list[Path] = []
        with self._writer_lock():
            for directory, rows in grouped.items():
                stem = f"events-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-{os.getpid()}"
                file = directory / f"{stem}.parquet"
                temporary = directory / f".{stem}.tmp"
                try:
                    pq.write_table(pa.Table.from_pylist(rows), temporary, compression="zstd")
                    os.replace(temporary, file)
                finally:
                    if temporary.exists():
                        temporary.unlink()
                written.append(file)
            self._update_coverage_index(grouped, len(written))
        return written

    def _update_coverage_index(self, grouped: dict[Path, list[dict[str, Any]]], file_count: int) -> None:
        if self._coverage_index_path.exists():
            try:
                index = json.loads(self._coverage_index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                index = {}
        else:
            index = {}
        streams = index.setdefault("streams", {})
        indexed_events = int(index.get("event_count", 0))
        for rows in grouped.values():
            for row in rows:
                indexed_events += 1
                key = f"{row['venue']}:{row['market_type']}:{row['instrument_id']}"
                stream = streams.setdefault(key, {
                    "venue": row["venue"],
                    "market_type": row["market_type"],
                    "instrument_id": row["instrument_id"],
                    "event_count": 0,
                    "min_source_time": None,
                    "max_source_time": None,
                    "last_received_at": None,
                    "event_types": [],
                    "sequence_count": 0,
                })
                stream["event_count"] += 1
                for field, value in (("min_source_time", row["source_time"]), ("max_source_time", row["source_time"]), ("last_received_at", row["received_at"])):
                    if value is not None and (stream[field] is None or (field == "min_source_time" and value < stream[field]) or (field != "min_source_time" and value > stream[field])):
                        stream[field] = value
                if row["event_type"] not in stream["event_types"]:
                    stream["event_types"].append(row["event_type"])
                if row["sequence"] is not None:
                    stream["sequence_count"] += 1
                try:
                    start = datetime.fromisoformat(str(stream["min_source_time"]).replace("Z", "+00:00"))
                    end = datetime.fromisoformat(str(stream["max_source_time"]).replace("Z", "+00:00"))
                    stream["span_hours"] = round((end - start).total_seconds() / 3600.0, 4)
                except (TypeError, ValueError):
                    stream["span_hours"] = None
        index.update({
            "version": 1,
            "updated_at": datetime.now(UTC).isoformat(),
            "event_count": indexed_events,
            "indexed_file_count": int(index.get("indexed_file_count", 0)) + file_count,
            "streams": streams,
        })
        temporary = self._coverage_index_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(index, ensure_ascii=True, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self._coverage_index_path)

    def files(
        self,
        *,
        venue: str | None = None,
        market_type: str | None = None,
        symbols: Iterable[str] | None = None,
    ) -> list[Path]:
        """List raw files, optionally narrowing the filesystem traversal."""

        base = self.root
        if venue:
            base = base / f"venue={_safe(venue)}"
        if market_type:
            base = base / f"market_type={_safe(market_type)}"
        if not base.exists():
            return []
        wanted = {_safe(str(item).upper()) for item in (symbols or ()) if str(item).strip()}
        paths: list[Path] = []
        if wanted:
            # Avoid walking unrelated symbol trees during bounded maintenance
            # jobs. This matters after a long public-data collection because
            # trade/BBO files can outnumber candle files by several orders.
            roots = [base / f"symbol={symbol}" for symbol in sorted(wanted)]
            candidates = (root.rglob("*.parquet") for root in roots if root.exists())
            for group in candidates:
                paths.extend(group)
        else:
            paths.extend(base.rglob("*.parquet"))
        paths = [path for path in paths if self._compacted_dir not in path.parents]
        return sorted(paths)

    def coverage(self) -> dict[str, Any]:
        index = self._load_coverage_index()
        indexed_file_count = int(index.get("indexed_file_count", 0))
        streams = index.get("streams", {}) if isinstance(index.get("streams", {}), dict) else {}

        # The incremental index is the hot-path source of truth. Recursively
        # enumerating every raw event file here can block the dashboard after a
        # long collection run; full filesystem reconciliation belongs to the
        # explicit rebuild_coverage_index maintenance command.
        if index:
            partitions = index.get("partitions", {}) if isinstance(index.get("partitions", {}), dict) else {}
            return {
                "status": "available" if indexed_file_count or streams else "not_collected",
                "file_count": indexed_file_count,
                "partitions": dict(sorted(partitions.items())),
                "streams": sorted(streams.values(), key=lambda item: (item.get("venue", ""), item.get("market_type", ""), item.get("instrument_id", ""))),
                "coverage_index_status": "complete" if indexed_file_count or streams else "missing",
                "coverage_index_updated_at": index.get("updated_at"),
                "event_count": int(index.get("event_count", 0)) if indexed_file_count or streams else None,
                "min_source_time": min((item.get("min_source_time") for item in streams.values() if item.get("min_source_time")), default=None),
                "max_source_time": max((item.get("max_source_time") for item in streams.values() if item.get("max_source_time")), default=None),
            }

        # Legacy datasets without an index are still supported. This path is
        # intentionally retained for small/offline stores and maintenance
        # tests; production collectors create the index on every append.
        files = self.files()
        partitions: dict[str, int] = defaultdict(int)
        for file in files:
            parts = {piece.split("=", 1)[0]: piece.split("=", 1)[1] for piece in file.parts if "=" in piece}
            key = f"{parts.get('venue', 'unknown')}:{parts.get('market_type', 'unknown')}:{parts.get('symbol', 'unknown')}"
            partitions[key] += 1
        return {
            "status": "available" if files else "not_collected",
            "file_count": len(files),
            "partitions": dict(sorted(partitions.items())),
            "streams": [],
            "coverage_index_status": "missing",
            "coverage_index_updated_at": None,
            "event_count": None,
            "min_source_time": None,
            "max_source_time": None,
        }

    def rebuild_coverage_index(self) -> dict[str, Any]:
        """Rebuild the fast coverage index from append-only Parquet files.

        Normal writers update this index incrementally. This explicit
        maintenance path repairs datasets written by an older runtime while
        the writer lock prevents a concurrent append from being omitted.
        """

        files = self.files()
        if not files:
            return self.coverage()
        import duckdb

        with self._writer_lock(), duckdb.connect(database=":memory:") as conn:
            rows = conn.execute(
                """
                SELECT venue, market_type, instrument_id,
                       COUNT(*) AS event_count,
                       MIN(source_time) AS min_source_time,
                       MAX(source_time) AS max_source_time,
                       MAX(received_at) AS last_received_at,
                       COUNT(DISTINCT sequence) FILTER (WHERE sequence IS NOT NULL) AS sequence_count,
                       LIST(DISTINCT event_type) AS event_types
                FROM read_parquet(?)
                GROUP BY venue, market_type, instrument_id
                ORDER BY venue, market_type, instrument_id
                """,
                [[str(path) for path in files]],
            ).fetchall()
        streams: dict[str, dict[str, Any]] = {}
        event_count = 0
        for row in rows:
            venue, market_type, instrument_id, count, minimum, maximum, last_received, sequence_count, event_types = row
            stream = {
                "venue": venue,
                "market_type": market_type,
                "instrument_id": instrument_id,
                "event_count": int(count),
                "min_source_time": minimum,
                "max_source_time": maximum,
                "last_received_at": last_received,
                "event_types": sorted(str(value) for value in (event_types or [])),
                "sequence_count": int(sequence_count or 0),
            }
            try:
                start = datetime.fromisoformat(str(minimum).replace("Z", "+00:00"))
                end = datetime.fromisoformat(str(maximum).replace("Z", "+00:00"))
                stream["span_hours"] = round((end - start).total_seconds() / 3600.0, 4)
            except (TypeError, ValueError):
                stream["span_hours"] = None
            streams[f"{venue}:{market_type}:{instrument_id}"] = stream
            event_count += int(count)
        index = {
            "version": 1,
            "updated_at": datetime.now(UTC).isoformat(),
            "event_count": event_count,
            "indexed_file_count": len(files),
            "streams": streams,
        }
        temporary = self._coverage_index_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(index, ensure_ascii=True, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self._coverage_index_path)
        return self.coverage()

    def _stream_coverage(self, files: list[Path]) -> list[dict[str, Any]]:
        if not files:
            return []
        import duckdb

        # Parquet files are published with an atomic replace. A read-only
        # snapshot can therefore use the file list captured above without
        # waiting behind the long-running collector writer lock.
        with duckdb.connect(database=":memory:") as conn:
            rows = conn.execute(
                """
                SELECT
                  venue,
                  market_type,
                  instrument_id,
                  COUNT(*) AS event_count,
                  MIN(source_time) AS min_source_time,
                  MAX(source_time) AS max_source_time,
                  MAX(received_at) AS last_received_at,
                  COUNT(DISTINCT event_type) AS event_type_count,
                  COUNT(DISTINCT sequence) FILTER (WHERE sequence IS NOT NULL) AS sequence_count,
                  quantile_cont(
                    date_diff('millisecond', TRY_CAST(source_time AS TIMESTAMPTZ), TRY_CAST(received_at AS TIMESTAMPTZ)),
                    0.50
                  ) / 1000.0 AS latency_p50_seconds,
                  quantile_cont(
                    date_diff('millisecond', TRY_CAST(source_time AS TIMESTAMPTZ), TRY_CAST(received_at AS TIMESTAMPTZ)),
                    0.95
                  ) / 1000.0 AS latency_p95_seconds
                FROM read_parquet(?)
                GROUP BY venue, market_type, instrument_id
                ORDER BY venue, market_type, instrument_id
                """,
                [[str(path) for path in files]],
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            value = dict(zip((
                "venue", "market_type", "instrument_id", "event_count", "min_source_time",
                "max_source_time", "last_received_at", "event_type_count", "sequence_count",
                "latency_p50_seconds", "latency_p95_seconds",
            ), row))
            try:
                start = datetime.fromisoformat(str(value["min_source_time"]).replace("Z", "+00:00"))
                end = datetime.fromisoformat(str(value["max_source_time"]).replace("Z", "+00:00"))
                value["span_hours"] = round((end - start).total_seconds() / 3600.0, 4)
            except (TypeError, ValueError):
                value["span_hours"] = None
            result.append(value)
        return result

    def query(self, *, venue: str | None = None, market_type: str | None = None, symbol: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        files = self.files(
            venue=venue,
            market_type=market_type,
            symbols=[symbol] if symbol else None,
        )
        if not files:
            return []
        import duckdb

        # Parquet files are published with an atomic replace. A read-only
        # snapshot can therefore use the file list captured above without
        # waiting behind the long-running collector writer lock.
        with duckdb.connect(database=":memory:") as conn:
            relation = conn.execute(
                "SELECT * FROM read_parquet(?, union_by_name=true) ORDER BY source_time DESC LIMIT ?",
                [[str(path) for path in files], max(1, min(limit, 1_000_000))],
            )
            columns = [item[0] for item in relation.description]
            return [dict(zip(columns, row)) for row in relation.fetchall()]

    def compact_closed_klines(
        self,
        *,
        interval: str = "1m",
        venue: str | None = None,
        market_type: str | None = None,
        symbols: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Create an immutable, deduplicated closed-K-line snapshot.

        This is an explicit maintenance operation, not part of the hot
        collector path. Raw event files remain untouched; the output is
        published atomically so readers never see a partial compacted file.
        """

        normalized_interval = str(interval).strip().lower()
        requested_symbols = tuple(sorted({
            _safe(str(item).upper()) for item in (symbols or ()) if str(item).strip()
        }))
        output_path = self.compacted_closed_kline_path_for(normalized_interval)
        output_manifest_path = self.compacted_closed_kline_manifest_path_for(normalized_interval)
        files = self.files(
            venue=venue,
            market_type=market_type,
            symbols=requested_symbols or None,
        )
        if not files:
            return {"status": "NO_GO", "reason": "no parquet files"}
        import duckdb

        self._compacted_dir.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(".tmp.parquet")
        if temporary.exists():
            temporary.unlink()
        raw_files_parameter = [str(path) for path in files]
        merge_existing = bool(requested_symbols) and output_path.exists()
        if merge_existing:
            excluded_instruments = " OR ".join(
                "ends_with(instrument_id, ':' || ?)" for _ in requested_symbols
            )
            sql = f"""
                COPY (
                    WITH incoming AS (
                        SELECT
                            asset_id, venue, instrument_id, market_type,
                            source_time, received_at, provider_status,
                            json_extract_string(payload_json, '$.interval') AS interval,
                            lower(coalesce(json_extract_string(payload_json, '$.closed'), 'false')) = 'true' AS closed,
                            try_cast(json_extract_string(payload_json, '$.open') AS DOUBLE) AS open,
                            try_cast(json_extract_string(payload_json, '$.high') AS DOUBLE) AS high,
                            try_cast(json_extract_string(payload_json, '$.low') AS DOUBLE) AS low,
                            try_cast(json_extract_string(payload_json, '$.close') AS DOUBLE) AS close,
                            try_cast(json_extract_string(payload_json, '$.volume') AS DOUBLE) AS volume
                        FROM read_parquet(?, union_by_name=true)
                        WHERE event_type = 'kline'
                    ), all_rows AS (
                        SELECT asset_id, venue, instrument_id, market_type,
                               source_time, received_at, provider_status,
                               interval, open, high, low, close, volume
                        FROM incoming
                        WHERE interval = ? AND closed
                          AND open IS NOT NULL AND high IS NOT NULL
                          AND low IS NOT NULL AND close IS NOT NULL
                        UNION ALL
                        SELECT asset_id, venue, instrument_id, market_type,
                               source_time, received_at, provider_status,
                               interval, open, high, low, close, volume
                        FROM read_parquet(?)
                        WHERE interval = ? AND NOT ({excluded_instruments})
                    ), deduped AS (
                        SELECT *, row_number() OVER (
                            PARTITION BY instrument_id, source_time
                            ORDER BY received_at DESC
                        ) AS row_number
                        FROM all_rows
                    )
                    SELECT asset_id, venue, instrument_id, market_type,
                           source_time, received_at, provider_status,
                           interval, open, high, low, close, volume
                    FROM deduped
                    WHERE row_number = 1
                    ORDER BY instrument_id, source_time
                ) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)
            """
            query_params: list[Any] = [raw_files_parameter, normalized_interval, [str(output_path)], normalized_interval, *requested_symbols]
            try:
                existing_manifest = json.loads(output_manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                existing_manifest = {}
            previous_symbols = tuple(str(item).upper() for item in existing_manifest.get("symbols", ()) if str(item).strip())
        else:
            sql = """
                COPY (
                    WITH parsed AS (
                        SELECT
                            asset_id, venue, instrument_id, market_type,
                            source_time, received_at, provider_status,
                            json_extract_string(payload_json, '$.interval') AS interval,
                            lower(coalesce(json_extract_string(payload_json, '$.closed'), 'false')) = 'true' AS closed,
                            try_cast(json_extract_string(payload_json, '$.open') AS DOUBLE) AS open,
                            try_cast(json_extract_string(payload_json, '$.high') AS DOUBLE) AS high,
                            try_cast(json_extract_string(payload_json, '$.low') AS DOUBLE) AS low,
                            try_cast(json_extract_string(payload_json, '$.close') AS DOUBLE) AS close,
                            try_cast(json_extract_string(payload_json, '$.volume') AS DOUBLE) AS volume,
                            row_number() OVER (
                                PARTITION BY instrument_id, source_time
                                ORDER BY received_at DESC
                            ) AS row_number
                        FROM read_parquet(?, union_by_name=true)
                        WHERE event_type = 'kline'
                    )
                    SELECT asset_id, venue, instrument_id, market_type,
                           source_time, received_at, provider_status,
                           interval, open, high, low, close, volume
                    FROM parsed
                    WHERE row_number = 1
                      AND interval = ?
                      AND closed
                      AND open IS NOT NULL AND high IS NOT NULL
                      AND low IS NOT NULL AND close IS NOT NULL
                    ORDER BY instrument_id, source_time
                ) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)
            """
            query_params = [raw_files_parameter, normalized_interval]
            previous_symbols = ()
        # DuckDB accepts a parameter for read_parquet but requires the COPY
        # target to be a literal filename. The target is an internal path;
        # escape it before embedding it in the maintenance-only statement.
        target = str(temporary).replace("\\", "/").replace("'", "''")
        sql = sql.replace("TO ? (FORMAT PARQUET", f"TO '{target}' (FORMAT PARQUET")
        with duckdb.connect(database=":memory:") as conn:
            conn.execute(sql, query_params)
            row = conn.execute("SELECT COUNT(*) FROM read_parquet(?)", [[str(temporary)]]).fetchone()
        os.replace(temporary, output_path)
        manifest = {
            "status": "available",
            "source_file_count": len(files),
            "source_indexed_file_count": self.file_count_estimate(),
            "interval": normalized_interval,
            "venue": venue,
            "market_type": market_type,
            "symbols": sorted(set(previous_symbols) | set(requested_symbols)),
            "row_count": int(row[0] if row else 0),
            "compacted_at": datetime.now(UTC).isoformat(),
        }
        output_manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, sort_keys=True), encoding="utf-8")
        return manifest

    def compact_derivative_snapshots(
        self,
        *,
        venue: str = "binance",
        market_type: str = "perpetual",
        symbols: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Publish a deduplicated Funding/OI snapshot for historical replay.

        The raw event store is append-only and also contains high-volume trade
        and BBO streams. This maintenance snapshot keeps only registered
        derivative events, with the latest received row winning for the same
        source timestamp. It is an evidence snapshot, not an availability
        guarantee: callers must still enforce the stored ``available_at`` and
        ``provenance`` contract.
        """

        files = self.files(venue=venue, market_type=market_type, symbols=symbols)
        if not files:
            return {"status": "NO_GO", "reason": "no parquet files"}
        import duckdb

        self._compacted_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._compacted_derivative_path.with_suffix(".tmp.parquet")
        if temporary.exists():
            temporary.unlink()
        sql = """
            COPY (
                WITH parsed AS (
                    SELECT
                        asset_id,
                        venue,
                        instrument_id,
                        market_type,
                        event_type,
                        source_time,
                        received_at,
                        provider_status,
                        json_extract_string(payload_json, '$.funding_rate') AS funding_rate_text,
                        json_extract_string(payload_json, '$.open_interest') AS open_interest_text,
                        json_extract_string(payload_json, '$.open_interest_value') AS open_interest_value_text,
                        coalesce(
                            json_extract_string(payload_json, '$.available_at'),
                            source_time
                        ) AS available_at,
                        json_extract_string(payload_json, '$.retrieved_at') AS retrieved_at,
                        coalesce(
                            json_extract_string(payload_json, '$.provenance'),
                            'unknown'
                        ) AS provenance,
                        row_number() OVER (
                            PARTITION BY instrument_id, event_type, source_time
                            ORDER BY received_at DESC
                        ) AS row_number
                    FROM read_parquet(?, union_by_name=true)
                    WHERE event_type IN ('funding_rate', 'open_interest')
                )
                SELECT
                    asset_id,
                    venue,
                    instrument_id,
                    market_type,
                    event_type,
                    source_time,
                    received_at,
                    provider_status,
                    try_cast(funding_rate_text AS DOUBLE) AS funding_rate,
                    try_cast(open_interest_text AS DOUBLE) AS open_interest,
                    try_cast(open_interest_value_text AS DOUBLE) AS open_interest_value,
                    available_at,
                    retrieved_at,
                    provenance
                FROM parsed
                WHERE row_number = 1
                  AND (
                    try_cast(funding_rate_text AS DOUBLE) IS NOT NULL
                    OR try_cast(open_interest_text AS DOUBLE) IS NOT NULL
                  )
                ORDER BY instrument_id, event_type, source_time
            ) TO '__TARGET__' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
        target = str(temporary).replace("\\", "/").replace("'", "''")
        sql = sql.replace("__TARGET__", target)
        with duckdb.connect(database=":memory:") as conn:
            conn.execute(sql, [[str(path) for path in files]])
            row = conn.execute("SELECT COUNT(*) FROM read_parquet(?)", [[str(temporary)]]).fetchone()
        os.replace(temporary, self._compacted_derivative_path)
        manifest = {
            "status": "available",
            "source_file_count": len(files),
            "source_indexed_file_count": self.file_count_estimate(),
            "venue": venue,
            "market_type": market_type,
            "symbols": sorted({_safe(str(item).upper()) for item in (symbols or ()) if str(item).strip()}),
            "event_types": ["funding_rate", "open_interest"],
            "row_count": int(row[0] if row else 0),
            "compacted_at": datetime.now(UTC).isoformat(),
            "dedup_key": ["instrument_id", "event_type", "source_time"],
        }
        self._compacted_derivative_manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=True, sort_keys=True),
            encoding="utf-8",
        )
        return manifest
