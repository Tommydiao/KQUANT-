from __future__ import annotations

"""Explicit, non-destructive SQLite and research-file backup helpers."""

import hashlib
import json
import shutil
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


BACKUP_VERSION = "crypto_backup_v1.0.0"
_IGNORED_NAMES = {".env", ".env.local", "node_modules", "dist", "__pycache__"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_file_manifest(root: Path, *, hash_files: bool = False, max_files: int = 2000) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in _IGNORED_NAMES for part in path.parts):
            continue
        if path.suffix.lower() not in {".parquet", ".json", ".ndjson", ".csv"}:
            continue
        rows.append({
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256(path) if hash_files else None,
        })
        if len(rows) >= max(1, int(max_files)):
            rows.append({"truncated": True, "remaining_files_not_listed": True})
            break
    return rows


def backup_sqlite(source: Path, destination: Path, *, timeout_seconds: float = 30.0) -> dict[str, Any]:
    if not source.exists():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    started = time.monotonic()
    try:
        with sqlite3.connect(str(source), timeout=5) as source_conn, sqlite3.connect(str(destination), timeout=5) as destination_conn:
            source_conn.execute("PRAGMA busy_timeout=5000")
            destination_conn.execute("PRAGMA busy_timeout=5000")

            def progress(_status: int, _remaining: int, _total: int) -> None:
                if time.monotonic() - started > max(1.0, float(timeout_seconds)):
                    raise TimeoutError("SQLite backup exceeded its bounded timeout")

            source_conn.backup(destination_conn, pages=512, sleep=0.05, progress=progress)
            destination_conn.commit()
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return {"path": str(destination), "size": destination.stat().st_size, "sha256": _sha256(destination)}


def create_backup(
    *,
    db_path: Path,
    data_dir: Path,
    output_dir: Path,
    copy_data: bool = False,
    hash_data: bool = False,
) -> dict[str, Any]:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = output_dir / stamp
    target.mkdir(parents=True, exist_ok=False)
    database = backup_sqlite(db_path, target / "kquant_crypto.sqlite3")
    manifest = {
        "version": BACKUP_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "database": database,
        "data_root": str(data_dir),
        "data_manifest": build_file_manifest(data_dir, hash_files=hash_data),
        "data_manifest_mode": "sha256" if hash_data else "metadata_only",
        "data_copied": bool(copy_data),
        "secrets_included": False,
        "research_only": True,
    }
    if copy_data and data_dir.exists():
        shutil.copytree(data_dir, target / "data", dirs_exist_ok=False, ignore=shutil.ignore_patterns(*_IGNORED_NAMES))
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return {"backup_dir": str(target), **manifest}


def restore_sqlite(source: Path, destination: Path, *, replace: bool = False) -> dict[str, Any]:
    if not source.exists():
        raise FileNotFoundError(source)
    if destination.exists() and not replace:
        raise FileExistsError(f"destination exists; pass replace=True explicitly: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    with sqlite3.connect(str(source)) as source_conn, sqlite3.connect(str(destination)) as destination_conn:
        source_conn.backup(destination_conn)
    return {"path": str(destination), "sha256": _sha256(destination), "research_only": True}


def verify_backup_restore(backup_dir: Path, destination: Path) -> dict[str, Any]:
    """Restore one backup to an explicit location and verify its integrity."""

    manifest_path = backup_dir / "manifest.json"
    source = backup_dir / "kquant_crypto.sqlite3"
    if not manifest_path.exists() or not source.exists():
        raise FileNotFoundError("backup manifest or SQLite database is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("backup manifest is invalid") from exc
    expected = ((manifest.get("database") or {}).get("sha256")) if isinstance(manifest, dict) else None
    source_hash = _sha256(source)
    if expected and source_hash != expected:
        raise ValueError("backup database hash does not match its manifest")
    restored = restore_sqlite(source, destination)
    with sqlite3.connect(str(destination)) as conn:
        quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        if quick_check.lower() != "ok":
            raise ValueError(f"restored SQLite quick_check failed: {quick_check}")
        user_tables = int(conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0])
    restored_hash = str(restored["sha256"])
    if restored_hash != source_hash:
        raise ValueError("restored SQLite hash does not match the source backup")
    manifest = dict(manifest)
    manifest.update({
        "restore_verified": True,
        "restore_verified_at": datetime.now(UTC).isoformat(),
        "restore_verified_sha256": restored_hash,
        "restore_verified_user_tables": user_tables,
    })
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(manifest_path)
    return {
        "status": "verified",
        "backup_dir": str(backup_dir),
        "restored_path": str(destination),
        "source_sha256": source_hash,
        "restored_sha256": restored_hash,
        "sqlite_quick_check": quick_check,
        "user_tables": user_tables,
        "research_only": True,
    }


def latest_backup_status(output_dir: Path) -> dict[str, Any]:
    """Read the latest secret-free backup manifest without writing anything."""

    manifests = sorted(output_dir.glob("*/manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True) if output_dir.exists() else []
    if not manifests:
        return {"status": "not_found", "last_backup": None, "restore_verified": False, "research_only": True}
    try:
        payload = json.loads(manifests[0].read_text(encoding="utf-8"))
        database = payload.get("database") if isinstance(payload.get("database"), dict) else {}
        return {
            "status": "available",
            "last_backup": payload.get("created_at"),
            "database_sha256": database.get("sha256"),
            "data_manifest_mode": payload.get("data_manifest_mode"),
            "data_copied": bool(payload.get("data_copied")),
            "restore_verified": bool(payload.get("restore_verified", False)),
            "research_only": True,
        }
    except (OSError, ValueError, TypeError):
        return {"status": "invalid_manifest", "last_backup": None, "restore_verified": False, "research_only": True}


__all__ = ["BACKUP_VERSION", "build_file_manifest", "backup_sqlite", "create_backup", "restore_sqlite", "verify_backup_restore", "latest_backup_status"]
