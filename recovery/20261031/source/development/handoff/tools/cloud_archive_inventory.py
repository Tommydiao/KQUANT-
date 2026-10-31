"""Bounded, read-only preparation for cloud archives; never upload or delete."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
import json
import ntpath
import os
from pathlib import Path
import re
import stat
from time import monotonic
from typing import Iterator


SKIP_DIRECTORIES = {".git", ".venv", ".venv-dev", "node_modules", "__pycache__",
                    ".pytest_cache", "browser_profile", "credentials", "secrets"}
SECRET_NAMES = {".env", "credentials.json", "secrets.json", "login data", "cookies",
                "local state", "web data", "key.pem", "id_rsa", "id_ed25519"}
SECRET_SUFFIXES = {".dpapi", ".pfx", ".p12", ".key"}
DATABASE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
SECRET_BYTES = re.compile(
    rb"-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----|"
    rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|"
    rb"(?i:OPENAI_API_KEY|LONGBRIDGE_APP_SECRET|LONGBRIDGE_ACCESS_TOKEN)"
    rb"[\"']?\s*[:=]\s*[\"'][A-Za-z0-9_./+\-=]{16,}[\"']"
)


def checked_path(value: str | Path, roots: list[Path]) -> Path:
    raw = str(value)
    drive, tail = ntpath.splitdrive(raw)
    if drive.upper() not in {"C:", "D:", "E:"} or not ntpath.isabs(raw) or ":" in tail:
        raise ValueError("FORBIDDEN_OR_RELATIVE_PATH")
    path = Path(ntpath.normpath(raw))
    if not any(path.is_relative_to(root) for root in roots):
        raise ValueError("OUTSIDE_EXPLICIT_ROOTS")
    for parent in reversed([path, *path.parents]):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("LINK_OR_REPARSE_PATH")
    return path


def excluded_name(path: Path) -> str | None:
    name = path.name.casefold()
    if (name in SECRET_NAMES or name.startswith(".env.") or "dpapi" in name
            or path.suffix.casefold() in SECRET_SUFFIXES):
        return "CREDENTIAL_NAME_EXCLUDED"
    if path.suffix.casefold() in DATABASE_SUFFIXES or name.endswith(("-wal", "-shm", "-journal")):
        return "DATABASE_REQUIRES_CONSISTENT_EXPORT"
    if name.endswith((".rar", ".7z", ".zip")):
        return "PREEXISTING_ARCHIVE_REQUIRES_CONTENT_AUDIT"
    return None


def file_rows(source: Path, roots: list[Path], deadline: float) -> Iterator[dict]:
    source = checked_path(source, roots)
    pending = [source]
    while pending:
        if monotonic() >= deadline:
            raise TimeoutError("INVENTORY_BUDGET_EXHAUSTED")
        path = pending.pop()
        try:
            path = checked_path(path, roots)
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                if path.name.casefold() in SKIP_DIRECTORIES:
                    yield {"path": str(path), "status": "REGENERABLE_OR_PRIVATE_DIRECTORY_EXCLUDED"}
                    continue
                with os.scandir(path) as entries:
                    for entry in entries:
                        if monotonic() >= deadline:
                            raise TimeoutError("INVENTORY_BUDGET_EXHAUSTED")
                        child = Path(entry.path)
                        try:
                            checked_path(child, roots)
                            if entry.is_dir(follow_symlinks=False):
                                if len(pending) >= 1000:
                                    raise TimeoutError("DIRECTORY_QUEUE_LIMIT")
                                pending.append(child)
                            else:
                                yield {"path": str(child), "status": "PENDING_HASH"}
                        except ValueError as exc:
                            yield {"path": str(child), "status": str(exc)}
                continue
            yield {"path": str(path), "status": "PENDING_HASH"}
        except (OSError, ValueError) as exc:
            yield {"path": str(path), "status": type(exc).__name__ if isinstance(exc, OSError) else str(exc)}


def inspect_file(path: Path, roots: list[Path], deadline: float, remaining_bytes: int) -> dict:
    checked_path(path, roots)
    row = {"path": str(path), "uploaded": False, "deletion_eligible": False}
    reason = excluded_name(path)
    if reason:
        return {**row, "status": reason, "bytes_hashed": 0}
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        return {**row, "status": "NON_REGULAR_FILE_EXCLUDED", "bytes_hashed": 0}
    row.update(bytes=before.st_size, mtime_ns=before.st_mtime_ns)
    if before.st_size > remaining_bytes:
        return {**row, "status": "HASH_BYTE_BUDGET_EXCEEDED", "bytes_hashed": 0}
    digest = sha256()
    carry = b""
    hashed = 0
    with path.open("rb") as stream:
        while block := stream.read(64 * 1024):
            if monotonic() >= deadline:
                raise TimeoutError("INVENTORY_BUDGET_EXHAUSTED")
            hashed += len(block)
            if hashed > remaining_bytes:
                return {**row, "status": "FILE_GREW_BEYOND_BUDGET", "bytes_hashed": hashed}
            if SECRET_BYTES.search(carry + block):
                return {**row, "status": "SECRET_CONTENT_EXCLUDED", "bytes_hashed": hashed}
            if hashed == len(block) and block.startswith(b"SQLite format 3\x00"):
                return {**row, "status": "DATABASE_REQUIRES_CONSISTENT_EXPORT", "bytes_hashed": hashed}
            if hashed == len(block) and block.startswith((b"PK\x03\x04", b"Rar!\x1a\x07", b"7z\xbc\xaf\x27\x1c")):
                return {**row, "status": "PREEXISTING_ARCHIVE_REQUIRES_CONTENT_AUDIT", "bytes_hashed": hashed}
            digest.update(block)
            carry = block[-512:]
    checked_path(path, roots)
    after = path.lstat()
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if identity(before) != identity(after) or hashed != after.st_size:
        return {**row, "status": "SOURCE_CHANGED_DURING_HASH", "bytes_hashed": hashed}
    return {**row, "status": "HASHED_AWAITING_PACKAGING_RECHECK", "sha256": digest.hexdigest(),
            "bytes_hashed": hashed, "file_identity": {"device": after.st_dev, "inode": after.st_ino}}


def inventory(scope: dict, output: Path, *, budget_seconds: float = 15,
              max_files: int = 1000, max_hash_bytes: int = 32 * 1024 * 1024) -> dict:
    if scope.get("schema") != "KQUANT_CLOUD_SCOPE_V1":
        raise ValueError("UNSUPPORTED_SCOPE")
    if not 0 < budget_seconds <= 60 or not 0 < max_files <= 10000 or max_hash_bytes < 0:
        raise ValueError("INVALID_BOUNDED_LIMIT")
    deadline = monotonic() + budget_seconds
    roots = [Path(ntpath.normpath(value)) for value in scope.get("approved_roots", [])]
    if not roots:
        raise ValueError("EXPLICIT_ROOTS_REQUIRED")
    for root in roots:
        checked_path(root, [root])
    destination = checked_path(output, roots)
    sources = [checked_path(str(value), roots) for value in scope.get("sources", [])]
    if not sources or any(destination == source or destination.is_relative_to(source) for source in sources):
        raise ValueError("INVALID_SOURCE_OR_OUTPUT_OVERLAP")
    if destination.exists():
        raise ValueError("IMMUTABLE_INVENTORY_ALREADY_EXISTS")
    destination.parent.mkdir(parents=True, exist_ok=True)
    checked_path(destination, roots)
    counts: Counter = Counter()
    entries = hashed_bytes = 0
    truncated = False
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        try:
            for source in sources:
                for item in file_rows(source, roots, deadline):
                    if entries >= max_files:
                        truncated = True
                        break
                    if item["status"] == "PENDING_HASH":
                        try:
                            item = inspect_file(Path(item["path"]), roots, deadline, max_hash_bytes - hashed_bytes)
                        except (OSError, ValueError) as exc:
                            item = {"path": item["path"], "status": type(exc).__name__ if isinstance(exc, OSError) else str(exc)}
                    hashed_bytes += item.get("bytes_hashed", 0)
                    counts[item["status"]] += 1
                    stream.write(json.dumps(item, ensure_ascii=True, sort_keys=True) + "\n")
                    entries += 1
                if truncated:
                    break
        except TimeoutError:
            truncated = True
    return {"schema": "KQUANT_CLOUD_INVENTORY_RESULT_V1", "observed_at": datetime.now(UTC).isoformat(),
            "inventory_path": str(destination), "entries": entries, "status_counts": dict(counts),
            "bytes_hashed": hashed_bytes, "truncated": truncated, "production_started": False,
            "uploaded_files": 0, "deleted_files": 0, "fault_drive_reads": 0,
            "database_exports": 0, "credential_uploads": 0}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seconds", type=float, default=15)
    args = parser.parse_args()
    root = Path(__file__).absolute().parent
    scope_path = checked_path(args.scope, [root])
    if scope_path.stat().st_size > 1024 * 1024:
        raise ValueError("SCOPE_TOO_LARGE")
    scope = json.loads(scope_path.read_text(encoding="utf-8-sig"))
    print(json.dumps(inventory(scope, Path(args.out), budget_seconds=args.seconds), ensure_ascii=True))


if __name__ == "__main__":
    main()
