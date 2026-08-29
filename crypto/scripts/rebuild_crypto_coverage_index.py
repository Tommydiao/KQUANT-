from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
from typing import Any

from kquant_crypto.config import load_settings
from kquant_crypto.parquet_store import ParquetMarketStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the crypto Parquet coverage index after a collector upgrade.")
    parser.add_argument("--root", type=Path, default=None, help="Optional data root override.")
    parser.add_argument("--batch-size", type=int, default=512, help="Raw Parquet files per bounded footer scan batch.")
    parser.add_argument("--venue", default=None, help="Limit the scan to one venue partition.")
    parser.add_argument("--market-type", default=None, help="Limit the scan to one market partition.")
    parser.add_argument("--symbol", dest="symbols", action="append", default=None, help="Limit the scan to one symbol; repeat for more symbols.")
    parser.add_argument("--date", dest="dates", action="append", default=None, help="Limit the scan to one UTC date partition; repeat for more dates.")
    parser.add_argument("--fragment-path", type=Path, default=None, help="Write a scoped result to this fragment path instead of publishing the main index.")
    parser.add_argument("--write-scope-manifest", type=Path, default=None, help="Write a cheap venue/market/symbol scope manifest and exit.")
    parser.add_argument("--run-scope-manifest", type=Path, default=None, help="Run every scope in a manifest, publishing one fragment per scope.")
    parser.add_argument("--resume", action="store_true", help="With --run-scope-manifest, skip already complete deterministic fragments.")
    parser.add_argument("--max-scopes", type=int, default=0, help="With --run-scope-manifest, process at most this many scopes; 0 means all.")
    parser.add_argument("--parallel-workers", type=int, default=1, help="With --run-scope-manifest, scan non-overlapping scopes concurrently.")
    parser.add_argument("--report-path", type=Path, default=None, help="Write the resumable scope run report atomically to this path.")
    parser.add_argument("--merge-fragments", action="store_true", help="Validate stored scope fragments instead of scanning raw files.")
    parser.add_argument("--scope-manifest", type=Path, default=None, help="Expected scope manifest for --merge-fragments.")
    parser.add_argument("--publish", action="store_true", help="With --merge-fragments, publish only when every expected scope is complete.")
    args = parser.parse_args()
    settings = load_settings(Path(__file__).resolve().parents[1])
    store = ParquetMarketStore(args.root or settings.data_dir)
    if args.write_scope_manifest:
        scopes = store.coverage_scope_manifest()
        args.write_scope_manifest.parent.mkdir(parents=True, exist_ok=True)
        args.write_scope_manifest.write_text(json.dumps(scopes, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "available", "scope_count": len(scopes), "path": str(args.write_scope_manifest)}, ensure_ascii=False, indent=2))
        return 0

    if args.merge_fragments:
        manifest: list[dict] | None = None
        if args.scope_manifest:
            manifest = json.loads(args.scope_manifest.read_text(encoding="utf-8"))
            if not isinstance(manifest, list):
                raise SystemExit("scope manifest must be a JSON list")
        print(json.dumps(store.merge_coverage_fragments(scope_manifest=manifest, publish=args.publish), ensure_ascii=False, indent=2, default=str))
        return 0

    if args.run_scope_manifest:
        scopes = json.loads(args.run_scope_manifest.read_text(encoding="utf-8"))
        if not isinstance(scopes, list):
            raise SystemExit("scope manifest must be a JSON list")
        results: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        skipped: list[str] = []
        processed = 0
        limit = max(0, int(args.max_scopes))

        def build_report() -> dict[str, Any]:
            complete_scope_keys: list[str] = []
            remaining_scope_keys: list[str] = []
            for candidate in scopes:
                if not isinstance(candidate, dict):
                    continue
                key = str(candidate.get("scope_key") or store.coverage_scope_key(candidate))
                try:
                    fragment = json.loads(store.coverage_fragment_path(candidate).read_text(encoding="utf-8"))
                except (OSError, UnicodeError, ValueError, TypeError):
                    fragment = None
                if (
                    isinstance(fragment, dict)
                    and fragment.get("scope_key") == key
                    and fragment.get("scan_status") == "complete"
                    and not int(fragment.get("unreadable_file_count", 0) or 0)
                ):
                    complete_scope_keys.append(key)
                else:
                    remaining_scope_keys.append(key)
            return {
                "status": "complete" if not remaining_scope_keys else "partial",
                "scope_count": len(scopes),
                "processed_count": processed,
                "skipped_count": len(skipped),
                "complete_count": len(complete_scope_keys),
                "remaining_count": len(remaining_scope_keys),
                "remaining_scope_keys": remaining_scope_keys,
                "resume": bool(args.resume),
                "results": results,
                "errors": errors,
            }

        def persist_report() -> None:
            if not args.report_path:
                return
            report = build_report()
            args.report_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.report_path.with_suffix(args.report_path.suffix + ".tmp")
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            temporary.replace(args.report_path)

        pending_scopes: list[dict[str, Any]] = []
        for scope in scopes:
            if not isinstance(scope, dict):
                continue
            scope_key = str(scope.get("scope_key") or "")
            if args.resume:
                fragment_path = store.coverage_fragment_path(scope)
                try:
                    fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, ValueError, TypeError):
                    fragment = None
                if (
                    isinstance(fragment, dict)
                    and fragment.get("scope_key") == (scope_key or store.coverage_scope_key(scope))
                    and fragment.get("scan_status") == "complete"
                    and not int(fragment.get("unreadable_file_count", 0) or 0)
                ):
                    skipped.append(scope_key or str(fragment.get("scope_key")))
                    persist_report()
                    continue
            if limit and processed >= limit:
                break
            pending_scopes.append(scope)

        def scan_scope(scope: dict[str, Any]) -> dict[str, Any]:
            return store.rebuild_coverage_index(
                batch_size=args.batch_size,
                venue=scope.get("venue"),
                market_type=scope.get("market_type"),
                symbols=scope.get("symbols") or None,
                dates=scope.get("dates") or None,
                lock=max(1, int(args.parallel_workers)) == 1,
            )

        worker_count = max(1, int(args.parallel_workers))
        if worker_count == 1:
            for scope in pending_scopes:
                try:
                    results.append(scan_scope(scope))
                except Exception as exc:
                    errors.append({
                        "scope_key": str(scope.get("scope_key") or store.coverage_scope_key(scope)),
                        "error_type": type(exc).__name__,
                    })
                processed += 1
                persist_report()
        else:
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="coverage-scope") as executor:
                futures = {executor.submit(scan_scope, scope): scope for scope in pending_scopes}
                for future in as_completed(futures):
                    scope = futures[future]
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        errors.append({
                            "scope_key": str(scope.get("scope_key") or store.coverage_scope_key(scope)),
                            "error_type": type(exc).__name__,
                        })
                    processed += 1
                    persist_report()
        report = build_report()
        if args.report_path:
            persist_report()
            report["report_path"] = str(args.report_path)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0

    print(json.dumps(store.rebuild_coverage_index(
        batch_size=args.batch_size,
        venue=args.venue,
        market_type=args.market_type,
        symbols=args.symbols,
        dates=args.dates,
        fragment_path=args.fragment_path,
    ), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
