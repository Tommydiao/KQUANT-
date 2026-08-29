from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager, nullcontext
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

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
        self._coverage_fragment_dir = self.root / "_coverage_fragments"
        self._compacted_dir = self.root / "_compacted"
        self._compacted_kline_path = self._compacted_dir / "closed_klines.parquet"
        self._compacted_manifest_path = self._compacted_dir / "closed_klines.manifest.json"
        self._compacted_derivative_path = self._compacted_dir / "derivative_snapshots.parquet"
        self._compacted_derivative_manifest_path = self._compacted_dir / "derivative_snapshots.manifest.json"
        self._coverage_index_issue: str | None = None

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
            raw = self._coverage_index_path.read_bytes()
            # A collector killed during an in-place/antivirus-mediated file
            # replacement can leave a zero-filled file with a valid-looking
            # size. Never let that force a recursive scan on a hot path.
            if b"\x00" in raw:
                self._coverage_index_issue = "nul_bytes"
                return {}
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            self._coverage_index_issue = "invalid_json"
            return {}
        return value if isinstance(value, dict) else {}

    def _coverage_from_compacted(self) -> dict[str, Any] | None:
        """Recover bounded coverage from immutable closed-K-line snapshots.

        This is deliberately not treated as a repaired raw-event index. It is
        a conservative recovery view for health checks and validation tooling;
        the explicit rebuild command remains the only path that reconciles
        every raw event file.
        """

        paths = sorted(self._compacted_dir.glob("closed_klines*.parquet"))
        if not paths:
            return None
        import duckdb

        try:
            with duckdb.connect(database=":memory:") as conn:
                rows = conn.execute(
                    """
                    SELECT venue, market_type, instrument_id, interval,
                           COUNT(*) AS event_count,
                           MIN(source_time) AS min_source_time,
                           MAX(source_time) AS max_source_time,
                           MAX(received_at) AS last_received_at
                    FROM read_parquet(?, union_by_name=true)
                    GROUP BY venue, market_type, instrument_id, interval
                    ORDER BY venue, market_type, instrument_id, interval
                    """,
                    [[str(path) for path in paths]],
                ).fetchall()
        except Exception:
            # Coverage must never take the dashboard down because a stale or
            # partially written maintenance snapshot is unreadable.
            self._coverage_index_issue = self._coverage_index_issue or "compacted_snapshot_unreadable"
            return None

        streams: list[dict[str, Any]] = []
        for venue, market_type, instrument_id, interval, count, minimum, maximum, last_received in rows:
            try:
                start = datetime.fromisoformat(str(minimum).replace("Z", "+00:00"))
                end = datetime.fromisoformat(str(maximum).replace("Z", "+00:00"))
                span_hours = round((end - start).total_seconds() / 3600.0, 4)
            except (TypeError, ValueError):
                span_hours = None
            streams.append({
                "venue": venue,
                "market_type": market_type,
                "instrument_id": instrument_id,
                "interval": interval,
                "event_count": int(count),
                "min_source_time": minimum,
                "max_source_time": maximum,
                "last_received_at": last_received,
                "event_types": ["kline"],
                "sequence_count": 0,
                "span_hours": span_hours,
                "coverage_basis": "compacted_closed_klines",
            })
        manifests: list[dict[str, Any]] = []
        for path in sorted(self._compacted_dir.glob("closed_klines*.manifest.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                manifests.append(value)
        return {
            "status": "available" if streams else "not_collected",
            "file_count": sum(int(item.get("source_file_count") or 0) for item in manifests),
            "partitions": {
                f"{item['venue']}:{item['market_type']}:{str(item['instrument_id']).rsplit(':', 1)[-1]}:{item.get('interval') or 'unknown'}": int(item["event_count"])
                for item in streams
            },
            "streams": streams,
            "coverage_index_status": "recovered_compacted",
            "coverage_index_issue": self._coverage_index_issue,
            "coverage_index_updated_at": None,
            "event_count": sum(int(item["event_count"]) for item in streams),
            "min_source_time": min((item["min_source_time"] for item in streams), default=None),
            "max_source_time": max((item["max_source_time"] for item in streams), default=None),
            "recovery_basis": "immutable_compacted_closed_klines",
            "raw_index_repair_required": True,
        }

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
                raw = self._coverage_index_path.read_bytes()
                if b"\x00" in raw:
                    raise ValueError("coverage index contains NUL bytes")
                index = json.loads(raw.decode("utf-8"))
                if not isinstance(index, dict):
                    raise ValueError("coverage index is not an object")
            except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
                # Never replace a corrupt or legacy-partial index with only
                # the current write batch. Raw events remain append-only and
                # the explicit scoped repair command is the only path that
                # can reconcile the full archive.
                self._coverage_index_issue = "raw_index_repair_required"
                return
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
        dates: Iterable[str] | None = None,
    ) -> list[Path]:
        """List raw files, optionally narrowing the filesystem traversal."""

        return sorted(self.iter_files(venue=venue, market_type=market_type, symbols=symbols, dates=dates))

    def iter_files(
        self,
        *,
        venue: str | None = None,
        market_type: str | None = None,
        symbols: Iterable[str] | None = None,
        dates: Iterable[str] | None = None,
    ) -> Iterable[Path]:
        """Yield raw files without materializing a large event tree."""

        base = self.root
        if venue:
            base = base / f"venue={_safe(venue)}"
        if market_type:
            base = base / f"market_type={_safe(market_type)}"
        if not base.exists():
            return
        wanted = {_safe(str(item).upper()) for item in (symbols or ()) if str(item).strip()}
        wanted_dates = {_safe(str(item)) for item in (dates or ()) if str(item).strip()}
        if wanted_dates:
            if wanted:
                roots = [base / f"symbol={symbol}" for symbol in sorted(wanted)]
            else:
                roots = [path for path in base.glob("symbol=*") if path.is_dir()]
            date_roots = (
                date_root
                for root in roots if root.exists()
                for date_root in root.glob("date=*")
                if date_root.is_dir() and date_root.name.removeprefix("date=") in wanted_dates
            )
            candidates = (path for date_root in date_roots for path in date_root.glob("*.parquet"))
        elif wanted:
            # Avoid walking unrelated symbol trees during bounded maintenance
            # jobs. This matters after a long public-data collection because
            # trade/BBO files can outnumber candle files by several orders.
            roots = [base / f"symbol={symbol}" for symbol in sorted(wanted)]
            candidates = (path for root in roots if root.exists() for path in root.rglob("*.parquet"))
        else:
            candidates = base.rglob("*.parquet")
        for path in candidates:
            if self._compacted_dir not in path.parents:
                yield path

    @staticmethod
    def _coverage_scope_key(scope: Mapping[str, Any]) -> str:
        normalized = {
            "venue": scope.get("venue"),
            "market_type": scope.get("market_type"),
            "symbols": sorted(str(item).upper() for item in (scope.get("symbols") or ()) if str(item).strip()),
            "dates": sorted(str(item) for item in (scope.get("dates") or ()) if str(item).strip()),
        }
        encoded = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]

    def coverage_scope_manifest(self) -> list[dict[str, Any]]:
        """Return non-overlapping venue/market/symbol maintenance scopes.

        This enumerates partition directories only. It does not open Parquet
        files and is therefore safe to run before a long footer repair.
        """

        scopes: list[dict[str, Any]] = []
        for symbol_root in self.root.glob("venue=*/market_type=*/symbol=*"):
            if not symbol_root.is_dir() or self._compacted_dir in symbol_root.parents:
                continue
            values = {
                part.split("=", 1)[0]: part.split("=", 1)[1]
                for part in symbol_root.parts
                if "=" in part
            }
            scope = {
                "venue": values.get("venue"),
                "market_type": values.get("market_type"),
                "symbols": [values.get("symbol")],
                "dates": [],
            }
            scope["scope_key"] = self._coverage_scope_key(scope)
            scopes.append(scope)
        return sorted(scopes, key=lambda item: str(item["scope_key"]))

    def coverage_fragment_path(self, scope: Mapping[str, Any]) -> Path:
        """Return the deterministic path for one resumable coverage scope."""

        self._coverage_fragment_dir.mkdir(parents=True, exist_ok=True)
        return self._coverage_fragment_dir / f"coverage-{self._coverage_scope_key(scope)}.json"

    def coverage_scope_key(self, scope: Mapping[str, Any]) -> str:
        """Return the public, stable key used by maintenance reports."""

        return self._coverage_scope_key(scope)

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
            has_data = bool(indexed_file_count or streams)
            unreadable_file_count = int(index.get("unreadable_file_count", 0) or 0)
            coverage_index_status = "partial" if unreadable_file_count else ("complete" if has_data else "missing")
            return {
                "status": "degraded" if unreadable_file_count and not has_data else ("available" if has_data else "not_collected"),
                "file_count": indexed_file_count,
                "partitions": dict(sorted(partitions.items())),
                "streams": sorted(streams.values(), key=lambda item: (item.get("venue", ""), item.get("market_type", ""), item.get("instrument_id", ""))),
                "coverage_index_status": coverage_index_status,
                "coverage_index_issue": index.get("coverage_index_issue"),
                "raw_index_repair_required": bool(unreadable_file_count),
                "scanned_file_count": int(index.get("scanned_file_count", indexed_file_count) or 0),
                "unreadable_file_count": unreadable_file_count,
                "unreadable_files": list(index.get("unreadable_files", ()))[:100],
                "coverage_index_updated_at": index.get("updated_at"),
                "event_count": int(index.get("event_count", 0)) if has_data else None,
                "min_source_time": min((item.get("min_source_time") for item in streams.values() if item.get("min_source_time")), default=None),
                "max_source_time": max((item.get("max_source_time") for item in streams.values() if item.get("max_source_time")), default=None),
            }

        recovered = self._coverage_from_compacted()
        if recovered is not None:
            return recovered

        if self._coverage_index_issue:
            # A corrupt index without a bounded snapshot is not permission to
            # walk an unbounded raw event tree from a request handler.
            return {
                "status": "degraded",
                "file_count": 0,
                "partitions": {},
                "streams": [],
                "coverage_index_status": "corrupt",
                "coverage_index_issue": self._coverage_index_issue,
                "coverage_index_updated_at": None,
                "event_count": None,
                "min_source_time": None,
                "max_source_time": None,
                "raw_index_repair_required": True,
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

    @staticmethod
    def _parquet_magic_issue(path: Path) -> str | None:
        """Catch a partially published Parquet file without opening DuckDB."""

        try:
            size = path.stat().st_size
            if size < 12:
                return "file_too_small"
            with path.open("rb") as handle:
                if handle.read(4) != b"PAR1":
                    return "missing_header_magic"
                handle.seek(-4, os.SEEK_END)
                if handle.read(4) != b"PAR1":
                    return "missing_footer_magic"
        except OSError as exc:
            return f"file_read_error:{type(exc).__name__}"
        return None

    def rebuild_coverage_index(
        self,
        *,
        batch_size: int = 512,
        venue: str | None = None,
        market_type: str | None = None,
        symbols: Iterable[str] | None = None,
        dates: Iterable[str] | None = None,
        fragment_path: Path | None = None,
        lock: bool = True,
    ) -> dict[str, Any]:
        """Rebuild the fast coverage index from append-only Parquet files.

        Normal writers update this index incrementally. This explicit
        maintenance path repairs datasets written by an older runtime while
        the writer lock prevents a concurrent append from being omitted. Raw
        files are inspected through bounded Parquet footer batches so a large
        event tree is never materialized as a DuckDB relation.
        """

        batch_size = max(1, int(batch_size))
        requested_symbols = tuple(sorted({
            _safe(str(item).upper()) for item in (symbols or ()) if str(item).strip()
        }))
        requested_dates = tuple(sorted({
            _safe(str(item)) for item in (dates or ()) if str(item).strip()
        }))
        scoped = bool(venue or market_type or requested_symbols or requested_dates or fragment_path)
        scope = {
            "venue": _safe(str(venue)) if venue else None,
            "market_type": _safe(str(market_type)) if market_type else None,
            "symbols": list(requested_symbols),
            "dates": list(requested_dates),
        }
        scope_key = self._coverage_scope_key(scope)
        if scoped and fragment_path is None:
            self._coverage_fragment_dir.mkdir(parents=True, exist_ok=True)
            fragment_path = self._coverage_fragment_dir / f"coverage-{scope_key}.json"
        if fragment_path is not None:
            fragment_path = Path(fragment_path)
        streams: dict[str, dict[str, Any]] = {}
        event_count = 0
        unreadable_files: list[dict[str, Any]] = []
        unreadable_file_total = 0
        scanned_file_total = 0

        def record_unreadable(path: Path, reason: str, error: Exception | None = None) -> None:
            nonlocal unreadable_file_total
            unreadable_file_total += 1
            # Keep the audit payload bounded and relative to the data root so
            # a maintenance detail never exposes a machine-specific path.
            if len(unreadable_files) >= 100:
                return
            try:
                display_path = str(path.relative_to(self.root.parent))
            except ValueError:
                display_path = path.name
            item: dict[str, Any] = {"path": display_path, "reason": reason}
            if error is not None:
                item["error"] = str(error)[:300]
            unreadable_files.append(item)

        def readable_batches() -> Iterable[list[Path]]:
            nonlocal scanned_file_total
            batch: list[Path] = []
            for path in self.iter_files(
                venue=venue,
                market_type=market_type,
                symbols=requested_symbols or None,
                dates=requested_dates or None,
            ):
                scanned_file_total += 1
                issue = self._parquet_magic_issue(path)
                if issue:
                    record_unreadable(path, issue)
                    continue
                batch.append(path)
                if len(batch) >= batch_size:
                    yield batch
                    batch = []
            if batch:
                yield batch

        worker_failed = False
        # Scoped fragments are independent files. Maintenance may opt out of
        # the global writer lock when it has already stopped the collector and
        # wants to scan several non-overlapping scopes concurrently.
        writer_context = self._writer_lock() if lock else nullcontext()
        with writer_context:
            # PyArrow can retain native footer allocations for the lifetime of
            # a Python process. Each worker batch is therefore a subprocess;
            # the OS reclaims all native memory before the next batch starts.
            repo_root = Path(__file__).resolve().parents[1]
            for batch_number, paths in enumerate(readable_batches()):
                offset = batch_number * batch_size
                manifest = self._coverage_index_path.with_name(
                    f".coverage-worker-{os.getpid()}-{threading.get_ident()}-{offset}.json"
                )
                manifest.write_text(json.dumps([str(path) for path in paths]), encoding="utf-8")
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "kquant_crypto.parquet_coverage_worker", str(manifest)],
                        cwd=str(repo_root),
                        capture_output=True,
                        text=True,
                        timeout=180,
                        check=False,
                    )
                    if result.returncode != 0:
                        worker_failed = True
                        for path in paths:
                            record_unreadable(path, "coverage_worker_failed", None)
                        continue
                    payload = json.loads(result.stdout)
                except (OSError, subprocess.SubprocessError, ValueError, TypeError):
                    worker_failed = True
                    for path in paths:
                        record_unreadable(path, "coverage_worker_failed", None)
                    continue
                finally:
                    try:
                        manifest.unlink()
                    except OSError:
                        pass

                for item in payload.get("unreadable_files", ()):
                    record_unreadable(Path(str(item.get("path", "unknown"))), str(item.get("reason", "worker_unreadable")), None)
                for row in payload.get("streams", ()):
                    key = f"{row.get('venue', 'unknown')}:{row.get('market_type', 'unknown')}:{row.get('instrument_id', 'unknown')}"
                    stream = streams.setdefault(key, {
                        "venue": row.get("venue", "unknown"),
                        "market_type": row.get("market_type", "unknown"),
                        "instrument_id": row.get("instrument_id", "unknown"),
                        "event_count": 0,
                        "min_source_time": None,
                        "max_source_time": None,
                        "last_received_at": None,
                        "event_types": [],
                        "sequence_count": 0,
                    })
                    stream["event_count"] += int(row.get("event_count", 0) or 0)
                    stream["sequence_count"] += int(row.get("sequence_count", 0) or 0)
                    for field in ("min_source_time", "max_source_time", "last_received_at"):
                        value = row.get(field)
                        if value is not None and (
                            stream[field] is None
                            or (field == "min_source_time" and value < stream[field])
                            or (field != "min_source_time" and value > stream[field])
                        ):
                            stream[field] = value
                    for event_type in row.get("event_types", ()):
                        if event_type not in stream["event_types"]:
                            stream["event_types"].append(event_type)
                    event_count += int(row.get("event_count", 0) or 0)

        if scanned_file_total == 0:
            if not scoped:
                return self.coverage()
            empty = {
                "version": 1,
                "fragment_version": 1,
                "updated_at": datetime.now(UTC).isoformat(),
                "scope": scope,
                "scope_key": scope_key,
                "coverage_basis": "raw_parquet_footer",
                "scan_status": "empty",
                "event_count": 0,
                "indexed_file_count": 0,
                "scanned_file_count": 0,
                "unreadable_file_count": 0,
                "unreadable_files": [],
                "streams": {},
            }
            assert fragment_path is not None
            fragment_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = fragment_path.with_suffix(fragment_path.suffix + ".tmp")
            temporary.write_text(json.dumps(empty, ensure_ascii=True, sort_keys=True), encoding="utf-8")
            os.replace(temporary, fragment_path)
            return {**empty, "published_fragment": str(fragment_path)}

        for stream in streams.values():
            stream["event_types"] = sorted(stream["event_types"])
            minimum = stream["min_source_time"]
            maximum = stream["max_source_time"]
            try:
                start = datetime.fromisoformat(str(minimum).replace("Z", "+00:00"))
                end = datetime.fromisoformat(str(maximum).replace("Z", "+00:00"))
                stream["span_hours"] = round((end - start).total_seconds() / 3600.0, 4)
            except (TypeError, ValueError):
                stream["span_hours"] = None
        index = {
            "version": 1,
            "updated_at": datetime.now(UTC).isoformat(),
            "event_count": event_count,
            "indexed_file_count": scanned_file_total - unreadable_file_total,
            "scanned_file_count": scanned_file_total,
            "unreadable_file_count": unreadable_file_total,
            "unreadable_files": unreadable_files,
            "coverage_index_issue": (
                "coverage_worker_failed" if worker_failed else
                ("unreadable_parquet_files" if unreadable_files else None)
            ),
            "streams": streams,
        }
        if scoped:
            index.update({
                "fragment_version": 1,
                "scope": scope,
                "scope_key": scope_key,
                "coverage_basis": "raw_parquet_footer",
                "scan_status": "complete" if not unreadable_files and not worker_failed else "partial",
            })
            assert fragment_path is not None
            fragment_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = fragment_path.with_suffix(fragment_path.suffix + ".tmp")
            temporary.write_text(json.dumps(index, ensure_ascii=True, sort_keys=True), encoding="utf-8")
            os.replace(temporary, fragment_path)
            return {**index, "published_fragment": str(fragment_path)}
        temporary = self._coverage_index_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(index, ensure_ascii=True, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self._coverage_index_path)
        return self.coverage()

    def merge_coverage_fragments(
        self,
        *,
        scope_manifest: Iterable[Mapping[str, Any]] | None = None,
        publish: bool = False,
    ) -> dict[str, Any]:
        """Validate and optionally publish a set of scoped coverage scans.

        Fragments are useful while repairing a large archive, but they do not
        imply full coverage by themselves. A caller must provide the expected
        non-overlapping scope manifest and set ``publish=True`` before the
        main index can be replaced. Missing or partial scopes return a report
        and leave the existing index untouched.
        """

        fragment_paths = sorted(self._coverage_fragment_dir.glob("coverage-*.json")) if self._coverage_fragment_dir.exists() else []
        fragments: dict[str, dict[str, Any]] = {}
        invalid_fragments: list[str] = []
        for path in fragment_paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
                invalid_fragments.append(path.name)
                continue
            if not isinstance(payload, dict) or not payload.get("scope_key"):
                invalid_fragments.append(path.name)
                continue
            fragments[str(payload["scope_key"])] = payload

        expected = [dict(item) for item in (scope_manifest or ())]
        expected_keys = {
            str(item.get("scope_key") or self._coverage_scope_key(item))
            for item in expected
        }
        missing = sorted(expected_keys - set(fragments)) if expected_keys else []
        partial = sorted(
            key for key, item in fragments.items()
            if item.get("scan_status") != "complete"
        )
        unexpected = sorted(set(fragments) - expected_keys) if expected_keys else sorted(fragments)
        aggregate_streams: dict[str, dict[str, Any]] = {}
        event_count = 0
        indexed_file_count = 0
        scanned_file_count = 0
        unreadable_file_count = 0
        unreadable_files: list[dict[str, Any]] = []
        for item in fragments.values():
            event_count += int(item.get("event_count", 0) or 0)
            indexed_file_count += int(item.get("indexed_file_count", 0) or 0)
            scanned_file_count += int(item.get("scanned_file_count", 0) or 0)
            unreadable_file_count += int(item.get("unreadable_file_count", 0) or 0)
            unreadable_files.extend(list(item.get("unreadable_files") or ())[: max(0, 100 - len(unreadable_files))])
            for key, row in (item.get("streams") or {}).items():
                stream = aggregate_streams.setdefault(str(key), {
                    "venue": row.get("venue", "unknown"),
                    "market_type": row.get("market_type", "unknown"),
                    "instrument_id": row.get("instrument_id", "unknown"),
                    "event_count": 0,
                    "min_source_time": None,
                    "max_source_time": None,
                    "last_received_at": None,
                    "event_types": [],
                    "sequence_count": 0,
                })
                stream["event_count"] += int(row.get("event_count", 0) or 0)
                stream["sequence_count"] += int(row.get("sequence_count", 0) or 0)
                for field in ("min_source_time", "max_source_time", "last_received_at"):
                    value = row.get(field)
                    if value is not None and (
                        stream[field] is None
                        or (field == "min_source_time" and value < stream[field])
                        or (field != "min_source_time" and value > stream[field])
                    ):
                        stream[field] = value
                for event_type in row.get("event_types", ()):
                    if event_type not in stream["event_types"]:
                        stream["event_types"].append(event_type)

        complete = bool(expected_keys) and not missing and not partial and not invalid_fragments and not unexpected
        report = {
            "status": "complete" if complete else "partial",
            "published": False,
            "fragment_count": len(fragments),
            "expected_scope_count": len(expected_keys),
            "missing_scope_keys": missing,
            "partial_scope_keys": partial,
            "unexpected_scope_keys": unexpected,
            "invalid_fragments": invalid_fragments,
            "event_count": event_count,
            "indexed_file_count": indexed_file_count,
            "scanned_file_count": scanned_file_count,
            "unreadable_file_count": unreadable_file_count,
            "unreadable_files": unreadable_files[:100],
            "streams": aggregate_streams,
            "coverage_index_status": "complete" if complete else "partial",
            "raw_index_repair_required": not complete,
            "publish_requested": bool(publish),
        }
        if not complete or not publish:
            return report

        index = {
            "version": 1,
            "updated_at": datetime.now(UTC).isoformat(),
            "event_count": event_count,
            "indexed_file_count": indexed_file_count,
            "scanned_file_count": scanned_file_count,
            "unreadable_file_count": unreadable_file_count,
            "unreadable_files": unreadable_files[:100],
            "coverage_index_issue": None,
            "streams": aggregate_streams,
            "coverage_index_status": "complete",
            "coverage_scope_manifest_hash": hashlib.sha256(
                json.dumps(sorted(expected_keys), ensure_ascii=True).encode("utf-8")
            ).hexdigest(),
        }
        temporary = self._coverage_index_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(index, ensure_ascii=True, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self._coverage_index_path)
        report.update({"published": True, "published_path": str(self._coverage_index_path)})
        return report

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
