"""Restore a reviewed content package to a fresh isolated directory only."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
import ntpath
from pathlib import Path
import re
from time import monotonic
import zipfile

from cloud_archive_inventory import SECRET_BYTES, checked_path, excluded_name


HASH = re.compile(r"[0-9a-f]{64}\Z")


def restore(package: Path, destination: Path, receipt: dict, *, roots: list[Path],
            budget_seconds: float = 30, max_bytes: int = 32 * 1024 * 1024,
            max_files: int = 1000) -> dict:
    if (not 0 < budget_seconds <= 60 or not 0 < max_bytes <= 32 * 1024 * 1024
            or not 0 < max_files <= 10000):
        raise ValueError("INVALID_RESTORE_LIMIT")
    deadline = monotonic() + budget_seconds
    package = checked_path(package, roots)
    destination = checked_path(destination, roots)
    preparing = checked_path(str(destination) + ".preparing", roots)
    if destination.exists() or preparing.exists() or package.is_relative_to(destination):
        raise ValueError("FRESH_ISOLATED_RESTORE_TARGET_REQUIRED")
    if (receipt.get("schema") != "KQUANT_CLOUD_LOCAL_PACKAGE_RECEIPT_V1"
            or not HASH.fullmatch(str(receipt.get("sha256", "")))
            or receipt.get("database_exports") != 0):
        raise ValueError("REVIEWED_NON_DATABASE_PACKAGE_RECEIPT_REQUIRED")
    before = package.stat()
    if before.st_size != receipt.get("bytes") or before.st_size > max_bytes + 2 * 1024 * 1024:
        raise ValueError("PACKAGE_SIZE_MISMATCH_OR_LIMIT")
    actual = sha256()
    with package.open("rb") as stream:
        while block := stream.read(64 * 1024):
            if monotonic() >= deadline:
                raise TimeoutError("RESTORE_BUDGET_EXHAUSTED")
            actual.update(block)
    if actual.hexdigest() != receipt["sha256"]:
        raise ValueError("PACKAGE_HASH_MISMATCH")
    with zipfile.ZipFile(package, "r") as archive:
        members = archive.infolist()
        names = [item.filename for item in members]
        if len(names) != len(set(names)) or len(members) > max_files + 1:
            raise ValueError("DUPLICATE_OR_EXCESS_PACKAGE_MEMBERS")
        if "manifest.json" not in names or archive.getinfo("manifest.json").file_size > 2 * 1024 * 1024:
            raise ValueError("BOUNDED_PACKAGE_MANIFEST_REQUIRED")
        metadata = json.loads(archive.read("manifest.json"))
        rows = metadata.get("files", [])
        if (metadata.get("schema") != "KQUANT_CLOUD_CONTENT_PACKAGE_V1"
                or metadata.get("database_exports") != 0
                or not isinstance(rows, list) or not 0 < len(rows) <= max_files
                or len(rows) != receipt.get("files")):
            raise ValueError("PACKAGE_MANIFEST_SCOPE_MISMATCH")
        objects = {}
        original_bytes = 0
        original_paths = set()
        for row in rows:
            path_text = row.get("path", "")
            drive, tail = ntpath.splitdrive(path_text)
            # Original names are metadata, not filesystem access or restore targets.
            if (drive.upper() not in {"C:", "E:"} or not ntpath.isabs(path_text)
                    or ":" in tail or path_text in original_paths
                    or excluded_name(Path(path_text))):
                raise ValueError("UNSAFE_OR_DUPLICATE_ORIGINAL_METADATA")
            original_paths.add(path_text)
            key, size = row.get("sha256", ""), row.get("bytes")
            if (not HASH.fullmatch(str(key)) or type(size) is not int or size < 0
                    or row.get("status") != "HASHED_AWAITING_PACKAGING_RECHECK"):
                raise ValueError("INVALID_CONTENT_RECORD")
            original_bytes += size
            if original_bytes > max_bytes:
                raise ValueError("RESTORE_EXPANSION_LIMIT")
            if key in objects and objects[key] != size:
                raise ValueError("CONFLICTING_CONTENT_SIZE")
            objects[key] = size
        expected = {"manifest.json", *("objects/" + key for key in objects)}
        if set(names) != expected or len(objects) != receipt.get("unique_objects"):
            raise ValueError("PACKAGE_MEMBER_SET_MISMATCH")
        for item in members:
            if item.is_dir() or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("DIRECTORY_OR_LINK_MEMBER_NOT_ALLOWED")
            if item.filename != "manifest.json" and item.file_size != objects[item.filename.removeprefix("objects/")]:
                raise ValueError("OBJECT_DECLARED_SIZE_MISMATCH")
        destination.parent.mkdir(parents=True, exist_ok=True)
        checked_path(preparing, roots)
        preparing.mkdir()
        (preparing / "objects").mkdir()
        for key, size in objects.items():
            target = checked_path(preparing / "objects" / key, roots)
            digest = sha256()
            count = 0
            carry = b""
            with archive.open("objects/" + key) as source, target.open("xb") as output:
                while block := source.read(64 * 1024):
                    if monotonic() >= deadline:
                        raise TimeoutError("RESTORE_BUDGET_EXHAUSTED")
                    count += len(block)
                    if count > size:
                        raise ValueError("OBJECT_SIZE_MISMATCH")
                    if SECRET_BYTES.search(carry + block):
                        raise ValueError("SECRET_CONTENT_NOT_RESTORABLE_FROM_PLAIN_ARCHIVE")
                    if count == len(block) and block.startswith((b"SQLite format 3\x00", b"PK\x03\x04", b"Rar!\x1a\x07", b"7z\xbc\xaf\x27\x1c")):
                        raise ValueError("DATABASE_OR_NESTED_ARCHIVE_REQUIRES_SEPARATE_REVIEW")
                    digest.update(block)
                    carry = block[-512:]
                    output.write(block)
            if count != size or digest.hexdigest() != key:
                raise ValueError("RESTORED_OBJECT_HASH_MISMATCH")
            # Verify actual disk bytes, not only the decompression stream.
            disk_hash = sha256()
            with target.open("rb") as stream:
                while block := stream.read(64 * 1024):
                    if monotonic() >= deadline:
                        raise TimeoutError("RESTORE_VERIFY_BUDGET_EXHAUSTED")
                    disk_hash.update(block)
            if target.stat().st_size != size or disk_hash.hexdigest() != key:
                raise ValueError("RESTORED_DISK_HASH_MISMATCH")
        index = {"schema": "KQUANT_ISOLATED_RESTORE_INDEX_V1", "package_sha256": receipt["sha256"],
                 "files": [{"original_path_metadata_only": row["path"],
                            "restored_object": "objects/" + row["sha256"],
                            "sha256": row["sha256"], "bytes": row["bytes"]} for row in rows],
                 "originals_overwritten": False, "database_activation": False}
        with (preparing / "restore-index.json").open("x", encoding="ascii") as output:
            json.dump(index, output, sort_keys=True, ensure_ascii=True)
    checked_path(package, roots)
    after = package.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("PACKAGE_CHANGED_DURING_RESTORE")
    checked_path(destination, roots)
    checked_path(preparing, roots)
    preparing.rename(destination)
    return {"schema": "KQUANT_CLOUD_ISOLATED_RESTORE_RECEIPT_V1", "observed_at": datetime.now(UTC).isoformat(),
            "package_sha256": receipt["sha256"], "restore_directory": str(destination),
            "files_verified": len(rows), "unique_objects_verified": len(objects),
            "original_bytes": original_bytes, "actual_disk_hashes_verified": True,
            "cloud_roundtrip_verified": False, "cloud_uploaded": False, "deletion_eligible": False,
            "originals_overwritten": 0, "fault_drive_reads": 0, "database_activation": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--receipt-out", required=True)
    args = parser.parse_args()
    tool_root = Path(__file__).absolute().parent
    scope_path = checked_path(args.scope, [tool_root])
    if scope_path.stat().st_size > 1024 * 1024:
        raise ValueError("SCOPE_SIZE_LIMIT")
    scope = json.loads(scope_path.read_text(encoding="utf-8-sig"))
    if scope.get("schema") != "KQUANT_CLOUD_SCOPE_V1":
        raise ValueError("UNSUPPORTED_SCOPE")
    roots = [Path(value) for value in scope["approved_roots"]]
    receipt_path = checked_path(args.receipt, roots)
    report_path = checked_path(args.receipt_out, roots)
    if receipt_path.stat().st_size > 1024 * 1024 or report_path.exists():
        raise ValueError("BOUNDED_RECEIPT_AND_IMMUTABLE_REPORT_REQUIRED")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    result = restore(Path(args.package), Path(args.out), receipt, roots=roots)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    checked_path(report_path, roots)
    with report_path.open("x", encoding="ascii") as output:
        json.dump(result, output, ensure_ascii=True, sort_keys=True)
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
