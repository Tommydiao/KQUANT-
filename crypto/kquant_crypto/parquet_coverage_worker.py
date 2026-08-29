"""Short-lived Parquet footer worker used by coverage-index maintenance."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


_COVERAGE_COLUMNS = {
    "venue",
    "market_type",
    "instrument_id",
    "source_time",
    "received_at",
    "sequence",
    "event_type",
}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def scan(paths: list[Path]) -> dict[str, Any]:
    import pyarrow.parquet as pq

    streams: dict[str, dict[str, Any]] = {}
    unreadable_files: list[dict[str, str]] = []

    for path in paths:
        try:
            parquet_file = pq.ParquetFile(path)
            metadata = parquet_file.metadata
            names = list(parquet_file.schema.names)
            indexes = {name: index for index, name in enumerate(names) if name in _COVERAGE_COLUMNS}
            groups: list[dict[str, Any]] = []
            for row_group_id in range(metadata.num_row_groups):
                row_group = metadata.row_group(row_group_id)
                group: dict[str, Any] = {
                    "row_count": int(row_group.num_rows),
                    "venue": None,
                    "market_type": None,
                    "instrument_id": None,
                    "min_source_time": None,
                    "max_source_time": None,
                    "last_received_at": None,
                    "sequence_count": 0,
                    "event_types": set(),
                }
                for name, index in indexes.items():
                    statistics = row_group.column(index).statistics
                    if statistics is None:
                        continue
                    minimum = _text(statistics.min)
                    maximum = _text(statistics.max)
                    if name in {"venue", "market_type", "instrument_id"} and minimum is not None:
                        group[name] = minimum
                    elif name == "source_time":
                        group["min_source_time"] = minimum
                        group["max_source_time"] = maximum
                    elif name == "received_at":
                        group["last_received_at"] = maximum
                    elif name == "sequence":
                        group["sequence_count"] = max(0, group["row_count"] - int(statistics.null_count or 0))
                    elif name == "event_type":
                        for value in (minimum, maximum):
                            if value is not None:
                                group["event_types"].add(value)
                groups.append(group)
            del parquet_file
        except Exception as exc:
            unreadable_files.append({
                "path": str(path),
                "reason": "pyarrow_metadata_error",
                "error": str(exc)[:300],
            })
            continue

        path_parts = {
            piece.split("=", 1)[0]: piece.split("=", 1)[1]
            for piece in path.parts if "=" in piece
        }
        for group in groups:
            venue = group["venue"] or path_parts.get("venue", "unknown")
            market_type = group["market_type"] or path_parts.get("market_type", "unknown")
            instrument_id = group["instrument_id"] or f"{venue}:{market_type}:{path_parts.get('symbol', 'unknown')}"
            key = f"{venue}:{market_type}:{instrument_id}"
            stream = streams.setdefault(key, {
                "venue": venue,
                "market_type": market_type,
                "instrument_id": instrument_id,
                "event_count": 0,
                "min_source_time": None,
                "max_source_time": None,
                "last_received_at": None,
                "event_types": [],
                "sequence_count": 0,
            })
            stream["event_count"] += int(group["row_count"])
            stream["sequence_count"] += int(group["sequence_count"])
            for field in ("min_source_time", "max_source_time", "last_received_at"):
                value = group[field]
                if value is not None and (
                    stream[field] is None
                    or (field == "min_source_time" and value < stream[field])
                    or (field != "min_source_time" and value > stream[field])
                ):
                    stream[field] = value
            for event_type in sorted(group["event_types"]):
                if event_type not in stream["event_types"]:
                    stream["event_types"].append(event_type)

    return {
        "streams": list(streams.values()),
        "unreadable_files": unreadable_files,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m kquant_crypto.parquet_coverage_worker MANIFEST", file=sys.stderr)
        return 2
    manifest = Path(sys.argv[1])
    paths = [Path(item) for item in json.loads(manifest.read_text(encoding="utf-8"))]
    print(json.dumps(scan(paths), ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
