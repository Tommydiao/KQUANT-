"""Package hash-indexed safe files; cloud delivery is a separate verified step."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
from time import monotonic
import zipfile

from cloud_archive_inventory import checked_path, inspect_file


def package(index: Path, output: Path, *, roots: list[Path], budget_seconds: float = 30,
            max_bytes: int = 32 * 1024 * 1024, max_files: int = 1000) -> dict:
    if not 0 < budget_seconds <= 60 or not 0 < max_files <= 10000 or max_bytes < 0:
        raise ValueError("INVALID_PACKAGE_LIMIT")
    deadline = monotonic() + budget_seconds
    index = checked_path(index, roots)
    output = checked_path(output, roots)
    temporary = checked_path(str(output) + ".preparing", roots)
    if output.suffix.lower() != ".zip" or output == index or output.exists() or temporary.exists():
        raise ValueError("NEW_IMMUTABLE_ZIP_TARGET_REQUIRED")
    if index.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("INDEX_SIZE_LIMIT")
    records, used = [], 0
    with index.open(encoding="utf-8") as stream:
        for line in stream:
            if monotonic() >= deadline or len(records) >= max_files:
                raise TimeoutError("PACKAGE_RECORD_OR_TIME_LIMIT")
            row = json.loads(line)
            if row.get("status") != "HASHED_AWAITING_PACKAGING_RECHECK":
                raise ValueError("INDEX_HAS_UNRESOLVED_FILES")
            path = checked_path(row["path"], roots)
            checked = inspect_file(path, roots, deadline, max_bytes - used)
            if (checked.get("status") != "HASHED_AWAITING_PACKAGING_RECHECK"
                    or checked.get("sha256") != row.get("sha256")
                    or checked.get("bytes") != row.get("bytes")
                    or checked.get("mtime_ns") != row.get("mtime_ns")
                    or checked.get("file_identity") != row.get("file_identity")):
                raise ValueError("SOURCE_CHANGED_OR_NOT_SAFE_FOR_PACKAGE")
            used += checked["bytes"]
            records.append(checked)
    if not records:
        raise ValueError("EMPTY_PACKAGE_NOT_ACCEPTED")
    metadata = {"schema": "KQUANT_CLOUD_CONTENT_PACKAGE_V1", "created_at": datetime.now(UTC).isoformat(),
                "index_sha256": sha256(index.read_bytes()).hexdigest(), "files": records,
                "restore_mode": "EXPLICIT_ISOLATED_TARGET_ONLY", "uploaded": False,
                "deletion_eligible": False, "database_exports": 0}
    output.parent.mkdir(parents=True, exist_ok=True)
    checked_path(temporary, roots)
    objects = {}
    with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        archive.writestr("manifest.json", json.dumps(metadata, sort_keys=True, ensure_ascii=True))
        for row in records:
            object_name = "objects/" + row["sha256"]
            if object_name in objects:
                continue
            path = checked_path(row["path"], roots)
            digest = sha256()
            length = 0
            with path.open("rb") as source, archive.open(object_name, "w") as target:
                while chunk := source.read(64 * 1024):
                    if monotonic() >= deadline:
                        raise TimeoutError("PACKAGE_BUDGET_EXHAUSTED")
                    digest.update(chunk)
                    length += len(chunk)
                    if length > row["bytes"]:
                        raise ValueError("SOURCE_CHANGED_WHILE_PACKAGING")
                    target.write(chunk)
            after = checked_path(path, roots).stat()
            if (digest.hexdigest() != row["sha256"] or length != row["bytes"]
                    or after.st_mtime_ns != row["mtime_ns"]
                    or {"device": after.st_dev, "inode": after.st_ino} != row["file_identity"]):
                raise ValueError("SOURCE_CHANGED_WHILE_PACKAGING")
            objects[object_name] = row
    checked_path(temporary, roots)
    with zipfile.ZipFile(temporary, "r") as archive:
        if set(archive.namelist()) != {"manifest.json", *objects}:
            raise ValueError("PACKAGE_MEMBER_SET_MISMATCH")
        if json.loads(archive.read("manifest.json")) != metadata:
            raise ValueError("PACKAGE_MANIFEST_MISMATCH")
        for name, row in objects.items():
            digest = sha256()
            length = 0
            with archive.open(name) as stream:
                while chunk := stream.read(64 * 1024):
                    if monotonic() >= deadline:
                        raise TimeoutError("PACKAGE_VERIFY_BUDGET_EXHAUSTED")
                    digest.update(chunk)
                    length += len(chunk)
                    if length > row["bytes"]:
                        raise ValueError("PACKAGE_OBJECT_SIZE_MISMATCH")
            if length != row["bytes"] or digest.hexdigest() != row["sha256"]:
                raise ValueError("PACKAGE_OBJECT_HASH_MISMATCH")
    digest = sha256()
    with temporary.open("rb") as stream:
        while block := stream.read(64 * 1024):
            if monotonic() >= deadline:
                raise TimeoutError("PACKAGE_VERIFY_BUDGET_EXHAUSTED")
            digest.update(block)
    checked_path(output, roots)
    temporary.rename(output)
    return {"schema": "KQUANT_CLOUD_LOCAL_PACKAGE_RECEIPT_V1", "observed_at": datetime.now(UTC).isoformat(),
            "path": str(output), "sha256": digest.hexdigest(), "bytes": output.stat().st_size,
            "files": len(records), "unique_objects": len(objects), "original_bytes": used,
            "package_objects_hash_verified": True, "uploaded": False, "cloud_roundtrip_verified": False,
            "deletion_eligible": False, "deleted_files": 0, "fault_drive_reads": 0, "database_exports": 0}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root = Path(__file__).absolute().parent
    scope_path = checked_path(args.scope, [root])
    if scope_path.stat().st_size > 1024 * 1024:
        raise ValueError("SCOPE_TOO_LARGE")
    scope = json.loads(scope_path.read_text(encoding="utf-8"))
    if scope.get("schema") != "KQUANT_CLOUD_SCOPE_V1":
        raise ValueError("UNSUPPORTED_SCOPE")
    roots = [Path(value) for value in scope["approved_roots"]]
    print(json.dumps(package(Path(args.index), Path(args.out), roots=roots), ensure_ascii=True))


if __name__ == "__main__":
    main()
