"""Read-only launch gate for a recovered runtime, without importing business code."""
from __future__ import annotations

from datetime import UTC, date, datetime
from hashlib import sha256
import json
import ntpath
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
from time import monotonic
from typing import Any


ROLES = {"main", "full_watch", "minute", "opening_research", "signal_copilot"}
NEW_EPOCH = "KQUANT_SAFE_NEW_EPOCH_V1"
OLD_RECORDS = {"minute_bars", "pending_tasks", "evaluations", "event_records", "manual_position_revisions"}


def canonical_hash(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def candidate_hash(manifest: dict) -> str:
    return canonical_hash({key: value for key, value in manifest.items()
                           if key not in {"acceptance_receipt", "final_runtime_accepted"}})


class BoundaryError(ValueError):
    pass


def checked_path(value: str, roots: list[Path]) -> Path:
    # Reject a forbidden drive lexically, before stat/resolve can touch it.
    drive, tail = ntpath.splitdrive(value)
    if drive.upper() not in {"C:", "D:", "E:"} or not ntpath.isabs(value) or ":" in tail:
        raise BoundaryError("FORBIDDEN_OR_RELATIVE_PATH")
    path = Path(ntpath.normpath(value))
    if not any(path.is_relative_to(root) for root in roots):
        raise BoundaryError("OUTSIDE_APPROVED_LOCAL_ROOTS")
    for item in reversed([path, *path.parents]):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise BoundaryError("REPARSE_PATH")
    return path


def safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or ":" in value or "\\" in value:
        raise BoundaryError("UNSAFE_ARTIFACT_PATH")
    return path


def digest(path: Path, deadline: float) -> str:
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("ARTIFACT_EXCEEDS_SMALL_FILE_LIMIT")
    result = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(256 * 1024):
            if monotonic() >= deadline:
                raise TimeoutError("PREFLIGHT_BUDGET_EXHAUSTED")
            result.update(chunk)
    return result.hexdigest()


def evaluate(manifest: dict[str, Any], *, roots: list[Path], budget_seconds: float = 5,
             allow_test_only: bool = False) -> dict[str, Any]:
    deadline = monotonic() + budget_seconds
    errors: list[dict[str, str]] = []
    verified = 0
    database_opens = 0
    metadata_baseline_opens = 0
    initialization_metadata_observations = []
    schema_extension_observations = []
    active_requests: list[dict] = []
    active_proofs: dict[str, dict] = {}
    epoch_boundary: dict | None = None
    path_binding: dict = {}

    def fail(code: str, subject: str) -> None:
        errors.append({"code": code, "subject": subject})

    def artifact(value: str, expected: str) -> Path | None:
        nonlocal verified
        try:
            path = checked_path(value, roots)
            if not expected or len(expected) != 64:
                raise ValueError("MISSING_SHA256")
            if digest(path, deadline) != expected:
                raise ValueError("HASH_MISMATCH")
            verified += 1
            return path
        except (OSError, ValueError, TimeoutError) as exc:
            fail(str(exc) if isinstance(exc, (ValueError, TimeoutError)) else type(exc).__name__, value)
            return None

    def receipt_json(receipt: dict[str, str]) -> dict[str, Any]:
        path = artifact(str(receipt.get("path", "")), str(receipt.get("sha256", "")))
        if path is None:
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(value, dict) and value.get("test_only") and not allow_test_only:
                fail("TEST_ONLY_RECEIPT_NOT_PRODUCTION", str(path))
                return {}
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            fail("INVALID_RECEIPT_JSON", str(path))
            return {}

    version = manifest.get("schema")
    if version not in {"KQUANT_SAFE_RECOVERY_V1", "KQUANT_SAFE_RECOVERY_V2", NEW_EPOCH}:
        fail("UNSUPPORTED_MANIFEST", "schema")
    activated_runtime = version in {"KQUANT_SAFE_RECOVERY_V2", NEW_EPOCH}
    runtime = None
    try:
        runtime = checked_path(str(manifest.get("runtime_root", "")), roots)
        approved = checked_path(str(manifest.get("approved_runtime_root", "")), roots)
        if runtime != approved:
            fail("RUNTIME_TARGET_NOT_ACCEPTED", str(runtime))
    except (OSError, ValueError) as exc:
        fail(str(exc), "runtime_root")

    # An incomplete overlay may not describe itself as the entire source tree.
    required = manifest.get("required_source", [])
    if not required:
        fail("MISSING_REQUIRED_SOURCE_INVENTORY", "required_source")
    for row in required:
        if monotonic() >= deadline:
            fail("PREFLIGHT_BUDGET_EXHAUSTED", "source_inventory")
            break
        artifact(str(row.get("path", "")), str(row.get("sha256", "")))
    frontend = manifest.get("frontend", [])
    if not frontend:
        fail("MISSING_PAIRED_FRONTEND", "frontend")
    for row in frontend:
        artifact(str(row.get("path", "")), str(row.get("sha256", "")))

    if version == NEW_EPOCH:
        declaration = receipt_json(manifest.get("epoch_declaration", {}))
        acceptance = receipt_json(manifest.get("data_scope_acceptance", {}))
        binding = receipt_json(manifest.get("runtime_path_binding", {}))
        try:
            session = date.fromisoformat(declaration["session"])
            epoch_id = declaration["epoch_id"]
            minute = checked_path(declaration["minute_path"], roots)
            expected = runtime / "work" / ("options_one_minute-epoch-" + session.strftime("%Y%m%d")) / "one_minute.sqlite3"
            declaration_sha = canonical_hash(declaration)
            schema_sha = declaration.get("schema_sha256", "")
            if (declaration.get("schema") != "KQUANT_NEW_MINUTE_EPOCH_V1"
                    or declaration.get("runtime_root") != str(runtime) or minute != expected
                    or not isinstance(epoch_id, str) or not epoch_id or len(epoch_id) > 100
                    or len(schema_sha) != 64 or any(c not in "0123456789abcdef" for c in schema_sha)
                    or set(declaration.get("preserved_roles", [])) != ROLES - {"minute"}
                    or set(declaration.get("unresolved_old_records", [])) != OLD_RECORDS
                    or declaration.get("old_position_continuity") != "UNKNOWN"
                    or declaration.get("complete_restoration_claimed") is not False
                    or declaration.get("execution_enabled") is not False
                    or declaration.get("qualified_signal_authorized") is not False):
                raise ValueError("NEW_EPOCH_DECLARATION_MISMATCH")
            if (acceptance.get("gate") != "O-SETUP" or acceptance.get("status") != "APPROVED"
                    or acceptance.get("approved_by") != "OWNER" or acceptance.get("decision") != "NEW_MINUTE_EPOCH"
                    or acceptance.get("declaration_sha256") != declaration_sha
                    or acceptance.get("runtime_root") != str(runtime) or acceptance.get("minute_path") != str(minute)
                    or acceptance.get("epoch_id") != epoch_id or acceptance.get("session") != session.isoformat()
                    or acceptance.get("old_position_continuity") != "UNKNOWN"
                    or not acceptance.get("human_decision_evidence")
                    or datetime.fromisoformat(acceptance["accepted_at"].replace("Z", "+00:00")).tzinfo is None):
                raise ValueError("EXACT_DATA_SCOPE_ACCEPTANCE_MISMATCH")
            stores = {r.get("role"): r.get("path") for r in manifest.get("databases", [])}
            binding_file = checked_path(str(manifest["runtime_path_binding"]["path"]), roots)
            if not binding_file.is_relative_to(runtime):
                raise ValueError("RUNTIME_PATH_BINDING_OUTSIDE_RUNTIME")
            if (binding.get("schema") != "KQUANT_NEW_EPOCH_RUNTIME_PATHS_V1"
                    or binding.get("runtime_root") != str(runtime) or binding.get("epoch_id") != epoch_id
                    or binding.get("session") != session.isoformat()
                    or binding.get("minute_path") != str(minute) or stores.get("minute") != str(minute)
                    or binding.get("opening_research_path") != stores.get("opening_research")
                    or binding.get("data_scope_acceptance_sha256") != canonical_hash(acceptance)):
                raise ValueError("EXACT_RUNTIME_PATH_BINDING_MISMATCH")
            if "stores" in binding and (not isinstance(binding["stores"], dict)
                    or set(binding["stores"]) != ROLES or binding["stores"] != stores
                    or len(set(binding["stores"].values())) != len(ROLES)):
                raise ValueError("EXACT_ALL_STORE_BINDING_MISMATCH")
            opening = checked_path(binding["opening_research_path"], roots)
            if not opening.is_relative_to(runtime) or opening.parent == minute.parent:
                raise ValueError("PRESERVED_RESEARCH_PATH_REQUIRED")
            epoch_boundary = {"schema": declaration["schema"], "epoch_id": epoch_id,
                "session": session.isoformat(), "declaration_sha256": declaration_sha,
                "data_scope_acceptance_sha256": canonical_hash(acceptance),
                "record_kind": "NEW_DATA_NOT_OLD_RECOVERY", "old_position_continuity": "UNKNOWN",
                "unresolved_old_records": sorted(OLD_RECORDS), "complete_restoration_claimed": False}
            path_binding = manifest["runtime_path_binding"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            fail(str(exc) if isinstance(exc, ValueError) else "INVALID_NEW_EPOCH_CONTRACT", "new_epoch")

    seen: set[str] = set()
    for row in manifest.get("databases", []):
        role = str(row.get("role", ""))
        if role in seen or role not in ROLES:
            fail("INVALID_OR_DUPLICATE_DATABASE_ROLE", role)
            continue
        seen.add(role)
        extension = row.get("schema_extension")
        if extension is not None and (not isinstance(extension, str) or version != NEW_EPOCH or (role, extension) not in {
                ("opening_research", "OPENING_SOURCE_INDEX_V1"),
                ('opening_research','OPENING_SOURCE_AND_CURRENT_INDEX_V1'),
                ('signal_copilot','COPILOT_AI_BUDGET_QUEUE_V1'),
                ("minute", "MINUTE_STATUS_METADATA_INDEX_V1")}):
            fail("UNSUPPORTED_SCHEMA_EXTENSION", role)
            continue
        if version == NEW_EPOCH and role == "minute":
            try:
                active = checked_path(str(row.get("path", "")), roots)
                activation = receipt_json(row.get("activation_receipt", {}))
                if (row.get("recovery_state") != "NEW_EPOCH_VERIFIED" or row.get("recovery_path")
                        or row.get("receipt") or epoch_boundary is None
                        or not active.is_file() or not active.is_relative_to(runtime)
                        or activation.get("schema") != "KQUANT_NEW_EPOCH_ACTIVATION_V1"
                        or activation.get("role") != "minute" or activation.get("database_path") != str(active)
                        or activation.get("epoch_boundary") != epoch_boundary
                        or not activation.get("verified_at") or not activation.get("file_identity", {}).get("inode")
                        or not activation.get("schema_sha256") or not activation.get("watermarks")):
                    raise ValueError("NEW_EPOCH_ACTIVATION_RECEIPT_MISMATCH")
                active_proofs[role] = activation
                request = {"role": role, "path": str(active), "watermarks": activation["watermarks"],
                           "epoch_boundary": epoch_boundary}
                if extension is not None:
                    request["schema_extension"] = extension
                active_requests.append(request)
            except (OSError, ValueError, TypeError) as exc:
                fail(str(exc) if isinstance(exc, ValueError) else type(exc).__name__, role)
            continue
        # Never open an incomplete recovery or an old archive as live business data.
        if row.get("recovery_state") != "COMPLETE_VERIFIED":
            fail("DATABASE_RECOVERY_NOT_COMPLETE", role)
            continue
        try:
            original_path = row.get("recovery_path", "") if activated_runtime else row.get("path", "")
            path = checked_path(str(original_path), roots)
            if not path.is_file():
                fail("MISSING_DATABASE_NO_AUTOCREATE", role)
            proof = receipt_json(row.get("receipt", {}))
            if (proof.get("database_path") != str(path) or proof.get("role") != role
                    or proof.get("integrity") != ["ok"] or not proof.get("verified_at")
                    or proof.get("bytes") != path.stat().st_size
                    or proof.get("mtime_ns") != path.stat().st_mtime_ns
                    or not isinstance(proof.get("wal_shm"), list)):
                fail("DATABASE_VERIFICATION_RECEIPT_MISMATCH", role)
            expected_companions = {str(path) + suffix for suffix in ("-wal", "-shm")
                                   if checked_path(str(path) + suffix, roots).exists()}
            if expected_companions != {str(r.get("path")) for r in proof.get("wal_shm", [])}:
                fail("DATABASE_COMPANION_SET_MISMATCH", role)
            for companion in proof.get("wal_shm", []):
                file = checked_path(str(companion.get("path", "")), roots)
                info = file.stat()
                if info.st_size != companion.get("bytes") or info.st_mtime_ns != companion.get("mtime_ns"):
                    fail("DATABASE_COMPANION_CHANGED", role)
            if activated_runtime:
                active = checked_path(str(row.get("path", "")), roots)
                activation = receipt_json(row.get("activation_receipt", {}))
                if (active == path or not active.is_file() or runtime is None
                        or not active.is_relative_to(runtime)):
                    fail("ACTIVE_DATABASE_NOT_SEPARATE_LOCAL_RUNTIME", role)
                elif (active.stat().st_dev, active.stat().st_ino) == (path.stat().st_dev, path.stat().st_ino):
                    fail("ACTIVE_DATABASE_LINKED_TO_RECOVERY_ORIGINAL", role)
                for suffix in ("-wal", "-shm", "-journal"):
                    checked_path(str(active) + suffix, roots)
                if (activation.get("schema") != "KQUANT_DATABASE_ACTIVATION_V1"
                        or activation.get("role") != role
                        or activation.get("database_path") != str(active)
                        or activation.get("recovery_receipt_sha256") != row.get("receipt", {}).get("sha256")
                        or not activation.get("verified_at")
                        or not activation.get("file_identity", {}).get("inode")
                        or not activation.get("schema_sha256")
                        or not activation.get("watermarks")):
                    fail("DATABASE_ACTIVATION_RECEIPT_MISMATCH", role)
                else:
                    active_proofs[role] = activation
                    request = {"role": role, "path": str(active), "watermarks": activation["watermarks"]}
                    if extension is not None:
                        request["schema_extension"] = extension
                    if role in {"signal_copilot", "main"}:
                        request["metadata_baseline"] = {"path": str(path),
                            "file_identity": activation.get("baseline_file_identity")}
                    active_requests.append(request)
        except (OSError, ValueError) as exc:
            fail(str(exc), role)
    for role in sorted(ROLES - seen):
        fail("UNDECLARED_BUSINESS_DATABASE", role)
    continuity = manifest.get("continuity", {})
    if version == NEW_EPOCH:
        proof = receipt_json(continuity.get("receipt", {}))
        preserved = ROLES - {"minute"}
        if (continuity.get("status") != "NEW_EPOCH_OLD_RECORDS_UNKNOWN"
                or set(continuity.get("reconciled_roles", [])) != preserved
                or proof.get("status") != "NEW_EPOCH_OLD_RECORDS_UNKNOWN"
                or proof.get("old_position_continuity") != "UNKNOWN"
                or set(proof.get("unresolved_old_records", [])) != OLD_RECORDS
                or proof.get("database_receipts") != {r["role"]: r.get("receipt", {}).get("sha256")
                    for r in manifest.get("databases", []) if r.get("role") in preserved}
                or proof.get("activation_receipts") != {r["role"]: r.get("activation_receipt", {}).get("sha256")
                    for r in manifest.get("databases", [])}
                or proof.get("epoch_boundary") != epoch_boundary or not proof.get("watermarks")):
            fail("NEW_EPOCH_CONTINUITY_BOUNDARY_MISMATCH", "continuity")
    elif continuity.get("status") != "CONFIRMED" or set(continuity.get("reconciled_roles", [])) != ROLES:
        fail("CROSS_STORE_CONTINUITY_UNCONFIRMED", "continuity")
    else:
        proof = receipt_json(continuity.get("receipt", {}))
        expected = {r["role"]: r.get("receipt", {}).get("sha256") for r in manifest.get("databases", [])}
        if (proof.get("status") != "CONFIRMED" or proof.get("database_receipts") != expected
                or not proof.get("watermarks") or proof.get("unresolved_business_gaps") != []):
            fail("CROSS_STORE_RECEIPT_MISMATCH", "continuity")
        if version == "KQUANT_SAFE_RECOVERY_V2" and proof.get("activation_receipts") != {
                r["role"]: r.get("activation_receipt", {}).get("sha256") for r in manifest.get("databases", [])}:
            fail("CROSS_STORE_ACTIVATION_RECEIPT_MISMATCH", "continuity")

    dependencies = manifest.get("dependencies", {})
    if not dependencies.get("verified_versions") or not dependencies.get("active_paths"):
        fail("DEPENDENCY_RUNTIME_UNVERIFIED", "dependencies")
    for value in dependencies.get("active_paths", []):
        try:
            checked_path(str(value), roots)
        except (OSError, ValueError) as exc:
            fail(str(exc), "dependency_active_path")
    receipt = dependencies.get("receipt", {})
    if receipt:
        proof = receipt_json(receipt)
        if (proof.get("versions") != dependencies.get("verified_versions")
                or proof.get("active_paths") != dependencies.get("active_paths") or proof.get("status") != "VERIFIED"):
            fail("DEPENDENCY_RECEIPT_MISMATCH", "dependencies")
    else:
        fail("DEPENDENCY_RECEIPT_MISSING", "dependencies")
    if manifest.get("final_runtime_accepted") is not True:
        fail("FINAL_RUNTIME_NOT_ACCEPTED", "O_LAUNCH")
    else:
        proof = receipt_json(manifest.get("acceptance_receipt", {}))
        if (proof.get("status") != "APPROVED" or proof.get("approved_by") != "OWNER"
                or not manifest.get("candidate_id") or proof.get("candidate_id") != manifest["candidate_id"]
                or runtime is None or proof.get("runtime_root") != str(runtime)
                or proof.get("continuity_receipt_sha256") != continuity.get("receipt", {}).get("sha256")):
            fail("EXACT_RUNTIME_ACCEPTANCE_MISMATCH", "O_LAUNCH")
        if version == NEW_EPOCH and (proof.get("gate") != "O-LAUNCH"
                or proof.get("candidate_payload_sha256") != candidate_hash(manifest)
                or not proof.get("accepted_at") or not proof.get("human_decision_evidence")):
            fail("EXACT_NEW_EPOCH_RUNTIME_ACCEPTANCE_MISMATCH", "O_LAUNCH")
    # Only complete, accepted V2 material can cause bounded read-only active DB access.
    if not errors and activated_runtime:
        remaining = deadline - monotonic()
        if remaining <= 0:
            fail("PREFLIGHT_BUDGET_EXHAUSTED", "active_databases")
        else:
            worker = None
            try:
                worker = subprocess.Popen([sys.executable, "-I", "-S",
                    str(Path(__file__).with_name("recovery_runtime_probe.py"))],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                payload = {"roots": [str(root) for root in roots], "databases": active_requests,
                           "budget_seconds": min(2, remaining)}
                output, _ = worker.communicate(json.dumps(payload).encode("ascii"), timeout=min(2, remaining))
                observed = json.loads(output)
                database_opens = observed.get("database_opens", 0)
                metadata_baseline_opens = observed.get("metadata_baseline_opens", 0)
                if worker.returncode != 0 or observed.get("ok") is not True:
                    fail(str(observed.get("code", "RUNTIME_DATABASE_PROBE_FAILED")),
                         str(observed.get("role", "active_databases")))
                else:
                    observations = observed.get("observations", [])
                    if {r.get("role") for r in observations} != ROLES or len(observations) != len(ROLES):
                        fail("RUNTIME_DATABASE_PROBE_INCOMPLETE", "active_databases")
                    for current in observations:
                        role = current["role"]
                        expected = active_proofs[role]
                        if current.get("file_identity") != expected["file_identity"]:
                            fail("ACTIVE_DATABASE_IDENTITY_CHANGED", role)
                        extension = next((r.get("schema_extension") for r in active_requests
                                          if r["role"] == role), None)
                        index_compatible = ((role, extension) in {
                            ("opening_research", "OPENING_SOURCE_INDEX_V1"),
                            ('opening_research','OPENING_SOURCE_AND_CURRENT_INDEX_V1'),
                            ('signal_copilot','COPILOT_AI_BUDGET_QUEUE_V1'),
                            ("minute", "MINUTE_STATUS_METADATA_INDEX_V1")}
                            and current.get("schema_extension", {}).get("contract") == extension
                            and current.get("baseline_schema_sha256") == expected["schema_sha256"])
                        if current.get("schema_sha256") != expected["schema_sha256"] and not index_compatible:
                            fail("ACTIVE_DATABASE_SCHEMA_CHANGED", role)
                        if extension is not None:
                            schema_extension_observations.append({"role": role,
                                "contract": extension, "compatible": index_compatible,
                                "observed": current.get("schema_extension"),
                                "actual_schema_sha256": current.get("schema_sha256"),
                                "baseline_schema_sha256": current.get("baseline_schema_sha256")})
                        marks = current.get("watermarks", [])
                        if len(marks) != len(expected["watermarks"]):
                            fail("ACTIVE_DATABASE_WATERMARKS_INCOMPLETE", role)
                        for actual, baseline in zip(marks, expected["watermarks"]):
                            minimum, head = baseline["minimum"], actual["current"]
                            metadata_match = (role == "signal_copilot" and baseline["table"] == "copilot_meta"
                                and actual.get("initialization_metadata_compatible") is True)
                            watchlist_metadata_match = (role == 'main' and baseline['table'] == 'stock_watchlist_members'
                                and actual.get('watchlist_timestamp_metadata_compatible') is True)
                            metadata_match = metadata_match or watchlist_metadata_match
                            if "initialization_metadata_compatible" in actual:
                                initialization_metadata_observations.append({"role": role, "table": baseline["table"],
                                    "compatible": metadata_match, "prefix_rows": actual["prefix_rows"],
                                    "baseline_prefix_rows": baseline["prefix_rows"]})
                            if 'watchlist_timestamp_metadata_compatible' in actual:
                                initialization_metadata_observations.append({'role': role, 'table': baseline['table'],
                                    'compatible': watchlist_metadata_match, 'only_mutable_field': 'updated_at',
                                    'prefix_rows': actual['prefix_rows'], 'baseline_prefix_rows': baseline['prefix_rows']})
                            if (not metadata_match and (minimum is not None and (head is None or head < minimum)
                                    or actual["prefix_rows"] != baseline["prefix_rows"]
                                    or actual["prefix_sha256"] != baseline["prefix_sha256"])):
                                fail("ACTIVE_DATABASE_BUSINESS_BASELINE_CHANGED", role)
            except subprocess.TimeoutExpired:
                database_opens = None
                fail("RUNTIME_DATABASE_PROBE_TIMEOUT", "active_databases")
            except (OSError, ValueError, KeyError, TypeError):
                fail("RUNTIME_DATABASE_PROBE_FAILED", "active_databases")
            finally:
                if worker is not None and worker.poll() is None:
                    worker.kill()
                    worker.communicate(timeout=1)
    return {"observed_at": datetime.now(UTC).isoformat(), "can_launch": not errors,
            "runtime_path_binding": path_binding if not errors else {},
            "old_position_continuity": "UNKNOWN" if version == NEW_EPOCH else "NOT_ESTABLISHED_BY_THIS_CHECK",
            "errors": errors, "verified_small_artifacts": verified, "database_opens": database_opens,
            "metadata_baseline_opens": metadata_baseline_opens,
            "initialization_metadata_observations": initialization_metadata_observations,
            "schema_extension_observations": schema_extension_observations,
            "business_writes": 0, "f_drive_reads": 0,
            "qualified_signal_authorized": False,
            "does_not_replace_release_manifest_or_signal_approval": True,
            "bound": "Application budget; not a guarantee that Windows kernel I/O is cancellable"}


def load_and_evaluate(path: Path, roots: list[Path]) -> dict[str, Any]:
    path = checked_path(str(path), roots)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("MANIFEST_TOO_LARGE")
    return evaluate(json.loads(path.read_text(encoding="utf-8-sig")), roots=roots)
