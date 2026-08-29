from __future__ import annotations

"""Move invalid raw Parquet files into an auditable quarantine directory.

The collector archive is append-only evidence. A killed writer can leave a
file without a Parquet footer; such a file must not enter coverage or
validation, but it is preserved byte-for-byte under ``_quarantine``.
"""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from kquant_crypto.config import load_settings
from kquant_crypto.parquet_store import ParquetMarketStore


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fragment_invalid_paths(store: ParquetMarketStore) -> list[Path]:
    paths: set[Path] = set()
    fragment_dir = store.root / "_coverage_fragments"
    for fragment_path in sorted(fragment_dir.glob("coverage-*.json")) if fragment_dir.exists() else ():
        try:
            payload = json.loads(fragment_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, TypeError):
            continue
        for item in payload.get("unreadable_files", ()) if isinstance(payload, dict) else ():
            raw = str(item.get("path") or "") if isinstance(item, dict) else ""
            if not raw:
                continue
            candidate = (store.root.parent / raw).resolve()
            if candidate.is_relative_to(store.root.resolve()) and candidate.suffix.lower() == ".parquet":
                paths.add(candidate)
    return sorted(paths)


def quarantine_invalid_files(
    *,
    root: Path,
    output_path: Path,
    dry_run: bool = False,
    limit: int = 0,
    from_fragments: bool = False,
) -> dict:
    store = ParquetMarketStore(root)
    market_root = store.root.resolve()
    quarantine_root = (store.root / "_quarantine").resolve()
    candidates: list[dict] = []
    conflicts: list[dict] = []
    moved: list[dict] = []

    with store._writer_lock():
        raw_files = _fragment_invalid_paths(store) if from_fragments else sorted(
            path for path in store.root.rglob("*.parquet")
            if path.is_file() and not path.resolve().is_relative_to(quarantine_root)
            and any(part.startswith("venue=") for part in path.relative_to(store.root).parts)
        )
        raw_files = [path for path in raw_files if path.exists() and path.is_file()]
        for path in raw_files:
            if limit and len(candidates) >= limit:
                break
            reason = store._parquet_magic_issue(path)
            if not reason:
                continue
            relative = path.relative_to(store.root)
            target = (quarantine_root / relative).resolve()
            if not target.is_relative_to(quarantine_root):
                raise RuntimeError("quarantine target escaped the data root")
            item = {
                "source_path": str(relative).replace("\\", "/"),
                "reason": reason,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            candidates.append(item)
            if target.exists():
                conflicts.append({**item, "target_path": str(target.relative_to(market_root)).replace("\\", "/")})
                continue
            if dry_run:
                moved.append({**item, "target_path": str(target.relative_to(market_root)).replace("\\", "/"), "action": "would_quarantine"})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            path.replace(target)
            moved.append({**item, "target_path": str(target.relative_to(market_root)).replace("\\", "/"), "action": "quarantined"})

    report = {
        "version": "crypto_parquet_quarantine_v1.0.0",
        "status": "dry_run" if dry_run else ("complete" if not conflicts else "partial"),
        "observed_at": datetime.now(UTC).isoformat(),
        "market_root": "data/market",
        "quarantine_root": "data/market/_quarantine",
        "discovery_mode": "coverage_fragments" if from_fragments else "raw_tree_scan",
        "raw_files_scanned": len(raw_files),
        "candidate_count": len(candidates),
        "moved_count": len(moved),
        "conflict_count": len(conflicts),
        "files": moved,
        "conflicts": conflicts,
        "raw_evidence_preserved": True,
        "read_only_market_data": True,
        "account_access": False,
        "wallet_access": False,
        "order_submission": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Quarantine invalid raw crypto Parquet files without deleting evidence.")
    parser.add_argument("--root", type=Path, default=None, help="Optional data root override.")
    parser.add_argument("--output", type=Path, default=None, help="Secret-free quarantine report path.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--from-fragments", action="store_true", help="Only process invalid paths recorded by coverage fragments.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum invalid files to inspect; 0 means all.")
    args = parser.parse_args()
    settings = load_settings(Path(__file__).resolve().parents[1])
    root = (args.root or settings.data_dir).resolve()
    output = (args.output or settings.outputs_dir / "parquet_quarantine_latest.json").resolve()
    print(json.dumps(quarantine_invalid_files(root=root, output_path=output, dry_run=args.dry_run, limit=max(0, args.limit), from_fragments=args.from_fragments), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
