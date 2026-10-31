"""Produce activation facts from verified recovery snapshots; never approve launch."""
from __future__ import annotations

from datetime import UTC, date, datetime
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import subprocess
import sys
from time import monotonic

from .recovery_preflight import OLD_RECORDS, ROLES, canonical_hash, checked_path, digest


NEW_EPOCH_REQUEST = "KQUANT_NEW_EPOCH_ACTIVATION_REQUEST_V1"


def portable_snapshot(proof: dict, original: Path, role: str, roots: list[Path],
                      deadline: float, allow_test_only: bool) -> bool:
    """A verified exported snapshot is the baseline, not a missing old-machine original."""
    if proof.get("schema") != "KQUANT_PORTABLE_SNAPSHOT_PROOF_V1":
        return False
    ref = proof["restore_receipt"]
    receipt = checked_path(ref["path"], roots)
    if digest(receipt, deadline) != ref["sha256"]:
        raise ValueError("PORTABLE_RESTORE_RECEIPT_HASH_MISMATCH")
    restored = json.loads(receipt.read_text(encoding="utf-8-sig"))
    if restored.get("test_only") and not allow_test_only:
        raise ValueError("TEST_ONLY_RECEIPT_NOT_PRODUCTION")
    core = restored.get("core_restore", {})
    stores = [item for item in core.get("stores", []) if item.get("role") == role]
    if (restored.get("schema") != "KQUANT_PORTABLE_COMPUTER_HANDOFF_RESTORE_V1"
            or restored.get("inputs_verified") is not True or restored.get("restored") is not True
            or restored.get("core_sha256") != proof.get("core_sha256")
            or not isinstance(proof.get("core_sha256"), str) or len(proof["core_sha256"]) != 64
            or checked_path(restored["preserved_snapshots"], roots) / (role + ".sqlite3") != original
            or len(stores) != 1):
        raise ValueError("PORTABLE_SNAPSHOT_PROVENANCE_MISMATCH")
    store = stores[0]
    info = original.stat()
    if (store.get("sha256") != proof.get("sha256") or not proof.get("sha256")
            or store.get("integrity_check") != ["ok"] or store.get("bytes_unchanged") is not True
            or store.get("bytes") != info.st_size or store.get("mtime_ns") != info.st_mtime_ns
            or store.get("file_identity") != {"device": info.st_dev, "inode": info.st_ino}
            or proof.get("validated_snapshot", {}).get("path") != str(original)):
        raise ValueError("PORTABLE_SNAPSHOT_PROVENANCE_MISMATCH")
    return True


def new_epoch_contract(request: dict, runtime: Path, roots: list[Path], deadline: float,
                       allow_test_only: bool) -> tuple[Path, dict]:
    """Read the actual decision supplied by the caller; never produce an approval."""
    materials = {}
    for name in ("epoch_declaration", "data_scope_acceptance"):
        ref = request[name]
        path = checked_path(ref["path"], roots)
        if digest(path, deadline) != ref["sha256"]:
            raise ValueError("NEW_EPOCH_MATERIAL_HASH_MISMATCH")
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("INVALID_NEW_EPOCH_MATERIAL")
        if value.get("test_only") and not allow_test_only:
            raise ValueError("TEST_ONLY_RECEIPT_NOT_PRODUCTION")
        materials[name] = value
    declaration, acceptance = materials["epoch_declaration"], materials["data_scope_acceptance"]
    session = date.fromisoformat(declaration["session"])
    epoch_id = declaration["epoch_id"]
    schema_sha = declaration.get("schema_sha256", "")
    minute = checked_path(declaration["minute_path"], roots)
    expected = runtime / "work" / ("options_one_minute-epoch-" + session.strftime("%Y%m%d")) / "one_minute.sqlite3"
    if (declaration.get("schema") != "KQUANT_NEW_MINUTE_EPOCH_V1"
            or declaration.get("runtime_root") != str(runtime) or minute != expected
            or not isinstance(epoch_id, str) or not epoch_id or len(epoch_id) > 100
            or not isinstance(schema_sha, str) or len(schema_sha) != 64
            or any(c not in "0123456789abcdef" for c in schema_sha)
            or set(declaration.get("preserved_roles", [])) != ROLES - {"minute"}
            or set(declaration.get("unresolved_old_records", [])) != OLD_RECORDS
            or declaration.get("old_position_continuity") != "UNKNOWN"
            or declaration.get("complete_restoration_claimed") is not False
            or declaration.get("execution_enabled") is not False
            or declaration.get("qualified_signal_authorized") is not False):
        raise ValueError("NEW_EPOCH_DECLARATION_MISMATCH")
    accepted_at = acceptance.get("accepted_at")
    if (acceptance.get("gate") != "O-SETUP" or acceptance.get("status") != "APPROVED"
            or acceptance.get("approved_by") != "OWNER" or acceptance.get("decision") != "NEW_MINUTE_EPOCH"
            or acceptance.get("declaration_sha256") != canonical_hash(declaration)
            or acceptance.get("runtime_root") != str(runtime) or acceptance.get("minute_path") != str(minute)
            or acceptance.get("epoch_id") != epoch_id or acceptance.get("session") != session.isoformat()
            or acceptance.get("old_position_continuity") != "UNKNOWN"
            or not acceptance.get("human_decision_evidence")
            or not isinstance(accepted_at, str)
            or datetime.fromisoformat(accepted_at.replace("Z", "+00:00")).tzinfo is None):
        raise ValueError("EXACT_DATA_SCOPE_ACCEPTANCE_MISMATCH")
    boundary = {"schema": declaration["schema"], "epoch_id": epoch_id,
                "session": session.isoformat(), "declaration_sha256": canonical_hash(declaration),
                "data_scope_acceptance_sha256": canonical_hash(acceptance),
                "record_kind": "NEW_DATA_NOT_OLD_RECOVERY", "old_position_continuity": "UNKNOWN",
                "unresolved_old_records": sorted(OLD_RECORDS), "complete_restoration_claimed": False}
    return minute, boundary


def produce(request: dict, *, roots: list[Path], budget_seconds: float = 5,
            allow_test_only: bool = False) -> dict:
    deadline = monotonic() + min(budget_seconds, 5)
    result = {"ok": False, "activation_receipts": [], "database_opens": 0,
              "business_writes": 0, "database_copies": 0, "f_drive_reads": 0,
              "owner_acceptance_written": False, "cross_store_continuity_confirmed": False,
              "can_launch": False, "qualified_signal_authorized": False}
    worker = None
    try:
        if (not isfinite(budget_seconds) or budget_seconds <= 0
                or request.get("schema") not in {"KQUANT_ACTIVATION_REQUEST_V1", NEW_EPOCH_REQUEST}):
            raise ValueError("INVALID_ACTIVATION_REQUEST")
        runtime = checked_path(request["runtime_root"], roots)
        if runtime != checked_path(request["approved_runtime_root"], roots):
            raise ValueError("RUNTIME_TARGET_NOT_ACCEPTED")
        rows = request["databases"]
        if len(rows) != len(ROLES) or {r["role"] for r in rows} != ROLES:
            raise ValueError("FIVE_RECOVERED_ROLES_REQUIRED")
        jobs, proofs = [], {}
        new_epoch = request["schema"] == NEW_EPOCH_REQUEST
        minute, boundary = (new_epoch_contract(request, runtime, roots, deadline, allow_test_only)
                            if new_epoch else (None, None))
        # All materials are checked before any database is opened, including a partial fifth store.
        for row in rows:
            role = row["role"]
            if new_epoch and role == "minute":
                active = checked_path(row["path"], roots)
                if (row.get("recovery_state") != "NEW_EPOCH_VERIFIED" or row.get("recovery_path")
                        or row.get("receipt") or active != minute or not active.is_file()):
                    raise ValueError("NEW_EPOCH_ACTIVATION_REQUEST_MISMATCH")
                for suffix in ("-wal", "-shm", "-journal"):
                    checked_path(str(active) + suffix, roots)
                marks = row.get("watermarks")
                if (not marks or len(marks) > 32
                        or len({(m["table"], m["column"]) for m in marks}) != len(marks)
                        or not any(m["table"] == "data_epoch_boundary" and m["column"] == "id" for m in marks)):
                    raise ValueError("NEW_EPOCH_BOUNDARY_WATERMARK_REQUIRED")
                jobs.append({"role": role, "path": str(active), "epoch_boundary": boundary,
                             "watermarks": [{"table": m["table"], "column": m["column"]} for m in marks]})
                continue
            if row.get("recovery_state") != "COMPLETE_VERIFIED":
                raise ValueError("DATABASE_RECOVERY_NOT_COMPLETE")
            original = checked_path(row["recovery_path"], roots)
            active = checked_path(row["path"], roots)
            ref = row["receipt"]
            receipt = checked_path(ref["path"], roots)
            if digest(receipt, deadline) != ref["sha256"]:
                raise ValueError("RECOVERY_RECEIPT_HASH_MISMATCH")
            proof = json.loads(receipt.read_text(encoding="utf-8-sig"))
            if proof.get("test_only") and not allow_test_only:
                raise ValueError("TEST_ONLY_RECEIPT_NOT_PRODUCTION")
            portable = portable_snapshot(proof, original, role, roots, deadline, allow_test_only)
            info = original.stat()
            if (proof.get("database_path") != str(original) or proof.get("role") != role
                    or proof.get("integrity") != ["ok"] or not proof.get("verified_at")
                    or proof.get("bytes") != info.st_size or proof.get("mtime_ns") != info.st_mtime_ns):
                raise ValueError("DATABASE_VERIFICATION_RECEIPT_MISMATCH")
            companions = proof.get("wal_shm")
            if not isinstance(companions, list):
                raise ValueError("DATABASE_COMPANION_SET_MISMATCH")
            actual = {str(original) + suffix for suffix in ("-wal", "-shm")
                      if checked_path(str(original) + suffix, roots).exists()}
            if actual != {r["path"] for r in companions}:
                raise ValueError("DATABASE_COMPANION_SET_MISMATCH")
            for companion in companions:
                file = checked_path(companion["path"], roots).stat()
                if file.st_size != companion["bytes"] or file.st_mtime_ns != companion["mtime_ns"]:
                    raise ValueError("DATABASE_COMPANION_CHANGED")
            stamp = proof.get("validated_snapshot", {})
            if (stamp.get("integrity") != ["ok"] or not stamp.get("file_identity")
                    or not stamp.get("path") or stamp.get("bytes") is None or stamp.get("mtime_ns") is None
                    or not isinstance(stamp.get("wal_shm"), list)):
                raise ValueError("VERIFIED_SNAPSHOT_RECEIPT_REQUIRED")
            snapshot = checked_path(stamp["path"], roots)
            if not snapshot.is_file() or not active.is_file():
                raise ValueError("MISSING_DATABASE_NO_AUTOCREATE")
            origin_id = {"device": info.st_dev, "inode": info.st_ino}
            if (not info.st_ino or not active.is_relative_to(runtime) or active == original
                    or (active.stat().st_dev, active.stat().st_ino) == (info.st_dev, info.st_ino)
                    or (not portable and (snapshot == original
                        or (snapshot.stat().st_dev, snapshot.stat().st_ino) == (info.st_dev, info.st_ino)))):
                raise ValueError("ACTIVE_DATABASE_NOT_SEPARATE_FROM_ORIGINAL")
            for file in (active, snapshot):
                for suffix in ("-wal", "-shm", "-journal"):
                    checked_path(str(file) + suffix, roots)
            marks = row.get("watermarks")
            if (not marks or len(marks) > 32
                    or len({(m["table"], m["column"]) for m in marks}) != len(marks)):
                raise ValueError("BUSINESS_BASELINE_SPEC_REQUIRED")
            proofs[role] = ref["sha256"]
            jobs.append({"role": role, "path": str(active), "snapshot": stamp,
                         "original_identity": origin_id,
                         "watermarks": [{"table": m["table"], "column": m["column"]} for m in marks]})
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("ACTIVATION_BUDGET_EXHAUSTED")
        worker = subprocess.Popen([sys.executable, "-I", "-S",
            str(Path(__file__).with_name("recovery_runtime_probe.py"))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        payload = {"action": "activation", "roots": [str(r) for r in roots],
                   "databases": jobs, "budget_seconds": remaining}
        output, _ = worker.communicate(json.dumps(payload).encode("ascii"), timeout=remaining)
        observed = json.loads(output)
        result["database_opens"] = observed.get("database_opens", 0)
        if worker.returncode or observed.get("ok") is not True:
            result["code"] = observed.get("code", "ACTIVATION_PROBE_FAILED")
            return result
        observations = observed["observations"]
        if len(observations) != len(ROLES) or {r["role"] for r in observations} != ROLES:
            raise ValueError("ACTIVATION_PROBE_INCOMPLETE")
        stamp = datetime.now(UTC).isoformat()
        for row in observations:
            fact = {"test_only": bool(allow_test_only), "role": row["role"],
                    "database_path": row["path"], "verified_at": stamp,
                    "file_identity": row["file_identity"], "schema_sha256": row["schema_sha256"],
                    "watermarks": row["watermarks"]}
            if new_epoch and row["role"] == "minute":
                fact.update(schema="KQUANT_NEW_EPOCH_ACTIVATION_V1", epoch_boundary=boundary)
            else:
                fact.update(schema="KQUANT_DATABASE_ACTIVATION_V1",
                            recovery_receipt_sha256=proofs[row["role"]],
                            baseline_snapshot=row["baseline_snapshot"],
                            baseline_file_identity=row["baseline_file_identity"])
            result["activation_receipts"].append(fact)
        if new_epoch:
            result.update(record_kind="NEW_DATA_NOT_OLD_RECOVERY", old_position_continuity="UNKNOWN",
                          old_business_continuity="UNKNOWN")
        result["ok"] = True
    except subprocess.TimeoutExpired:
        result["database_opens"] = None
        result["code"] = "ACTIVATION_PROBE_TIMEOUT"
    except (OSError, ValueError, KeyError, TypeError, TimeoutError) as exc:
        result["code"] = str(exc) if isinstance(exc, (ValueError, TimeoutError)) else type(exc).__name__
    finally:
        if worker is not None and worker.poll() is None:
            worker.kill()
            worker.communicate(timeout=1)
    return result
