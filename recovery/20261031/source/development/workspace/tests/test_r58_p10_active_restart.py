from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
from time import monotonic

import pytest

from kquant.recovery_preflight import ROLES, evaluate
from kquant.recovery_runtime_probe import observe_database


def activated(tmp_path):
    root, original = tmp_path / "runtime", tmp_path / "original"
    root.mkdir()
    original.mkdir()

    def receipt(name, value):
        path = root / (name + ".json")
        path.write_text(json.dumps({"test_only": True, **value}), encoding="ascii")
        return {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}

    source = receipt("source", {"purpose": "TEST_ONLY"})
    rows = []
    for role in sorted(ROLES):
        frozen, active = original / (role + ".sqlite3"), root / (role + ".sqlite3")
        with closing(sqlite3.connect(frozen)) as db:
            db.execute("CREATE TABLE business_events (id INTEGER PRIMARY KEY, payload TEXT)")
            db.execute("INSERT INTO business_events VALUES (1, 'TEST_ONLY retained business')")
            db.commit()
        proof = receipt(role + "-recovery", {"role": role, "database_path": str(frozen),
            "bytes": frozen.stat().st_size, "mtime_ns": frozen.stat().st_mtime_ns,
            "integrity": ["ok"], "verified_at": "TEST_ONLY", "wal_shm": []})
        shutil.copy2(frozen, active)
        observation = observe_database({"role": role, "path": str(active),
            "watermarks": [{"table": "business_events", "column": "id", "minimum": 1}]},
            [str(tmp_path)], monotonic() + 5)
        activation = receipt(role + "-activation", {"schema": "KQUANT_DATABASE_ACTIVATION_V1",
            "role": role, "database_path": str(active), "verified_at": "TEST_ONLY",
            "recovery_receipt_sha256": proof["sha256"], "file_identity": observation["file_identity"],
            "schema_sha256": observation["schema_sha256"], "watermarks": observation["watermarks"]})
        rows.append({"role": role, "path": str(active), "recovery_path": str(frozen),
            "recovery_state": "COMPLETE_VERIFIED", "receipt": proof, "activation_receipt": activation})
    continuity = receipt("continuity", {"status": "CONFIRMED", "watermarks": {r: 1 for r in ROLES},
        "unresolved_business_gaps": [], "database_receipts": {r["role"]: r["receipt"]["sha256"] for r in rows},
        "activation_receipts": {r["role"]: r["activation_receipt"]["sha256"] for r in rows}})
    deps = {"verified_versions": {"TEST_ONLY": "1"}, "active_paths": [str(root)]}
    deps["receipt"] = receipt("dependencies", {"status": "VERIFIED", "versions": deps["verified_versions"],
        "active_paths": deps["active_paths"]})
    accepted = receipt("acceptance", {"status": "APPROVED", "approved_by": "OWNER",
        "candidate_id": "TEST_ONLY", "runtime_root": str(root), "continuity_receipt_sha256": continuity["sha256"]})
    return {"schema": "KQUANT_SAFE_RECOVERY_V2", "runtime_root": str(root), "approved_runtime_root": str(root),
        "candidate_id": "TEST_ONLY", "required_source": [source], "frontend": [source], "databases": rows,
        "continuity": {"status": "CONFIRMED", "reconciled_roles": sorted(ROLES), "receipt": continuity},
        "dependencies": deps, "final_runtime_accepted": True, "acceptance_receipt": accepted}


def check(manifest, tmp_path, **kwargs):
    return evaluate(manifest, roots=[tmp_path], allow_test_only=True, **kwargs)


def test_real_write_checkpoint_and_restart_preserve_original(tmp_path):
    manifest = activated(tmp_path)
    originals = {r["role"]: Path(r["recovery_path"]).read_bytes() for r in manifest["databases"]}
    assert check(manifest, tmp_path)["can_launch"]
    for row in manifest["databases"]:
        with closing(sqlite3.connect(row["path"])) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("INSERT INTO business_events VALUES (2, ?)", ("TEST_ONLY new event" * 1000,))
            db.commit()
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    result = check(manifest, tmp_path)
    assert result["can_launch"], result
    assert result["database_opens"] == 5
    assert result["business_writes"] == result["f_drive_reads"] == 0
    assert result["qualified_signal_authorized"] is False
    assert originals == {r["role"]: Path(r["recovery_path"]).read_bytes() for r in manifest["databases"]}


def test_new_events_in_uncheckpointed_wal_are_visible(tmp_path):
    manifest = activated(tmp_path)
    with closing(sqlite3.connect(manifest["databases"][0]["path"])) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("INSERT INTO business_events VALUES (2,'TEST_ONLY WAL')")
        db.commit()
        assert Path(manifest["databases"][0]["path"] + "-wal").exists()
        assert check(manifest, tmp_path)["can_launch"]


@pytest.mark.parametrize("mutation,code", [
    ("replace", "ACTIVE_DATABASE_IDENTITY_CHANGED"),
    ("schema", "ACTIVE_DATABASE_SCHEMA_CHANGED"),
    ("delete_old", "ACTIVE_DATABASE_BUSINESS_BASELINE_CHANGED"),
    ("rewrite_old", "ACTIVE_DATABASE_BUSINESS_BASELINE_CHANGED"),
    ("modify_original", "DATABASE_VERIFICATION_RECEIPT_MISMATCH"),
    ("missing_activation", "DATABASE_ACTIVATION_RECEIPT_MISMATCH"),
    ("f_active", "FORBIDDEN_OR_RELATIVE_PATH"),
    ("same_original", "ACTIVE_DATABASE_NOT_SEPARATE_LOCAL_RUNTIME"),
])
def test_illegitimate_database_changes_do_not_pass(tmp_path, mutation, code):
    manifest = activated(tmp_path)
    row = manifest["databases"][0]
    path = Path(row["path"])
    if mutation == "replace":
        path.rename(path.with_suffix(".kept"))
        shutil.copy2(row["recovery_path"], path)
    elif mutation in {"schema", "delete_old", "rewrite_old"}:
        with closing(sqlite3.connect(path)) as db:
            sql = {"schema": "CREATE TABLE unrelated (id INTEGER)", "delete_old": "DELETE FROM business_events",
                   "rewrite_old": "UPDATE business_events SET payload='TEST_ONLY changed' WHERE id=1"}[mutation]
            db.execute(sql)
            db.commit()
    elif mutation == "modify_original":
        with closing(sqlite3.connect(row["recovery_path"])) as db:
            db.execute("INSERT INTO business_events VALUES (2,'TEST_ONLY unexpected original write')")
            db.commit()
    elif mutation == "missing_activation":
        row.pop("activation_receipt")
    elif mutation == "f_active":
        row["path"] = r"F:\never-read.sqlite3"
    elif mutation == "same_original":
        row["path"] = row["recovery_path"]
    result = check(manifest, tmp_path)
    assert not result["can_launch"]
    assert code in {r["code"] for r in result["errors"]}, result


def test_unaccepted_candidate_never_probes_active_database(tmp_path, monkeypatch):
    manifest = activated(tmp_path)
    manifest["final_runtime_accepted"] = False
    monkeypatch.setattr("kquant.recovery_preflight.subprocess.Popen", lambda *a, **k: pytest.fail("unaccepted DB probe"))
    result = check(manifest, tmp_path)
    assert not result["can_launch"] and result["database_opens"] == 0


def test_missing_active_database_not_created(tmp_path):
    manifest = activated(tmp_path)
    path = Path(manifest["databases"][0]["path"])
    path.unlink()
    assert not check(manifest, tmp_path)["can_launch"]
    assert not path.exists()


def test_timeout_reaps_worker_and_fails_closed(tmp_path, monkeypatch):
    import subprocess

    manifest = activated(tmp_path)
    original = subprocess.Popen
    children = []
    def slow_worker(*args, **kwargs):
        args = ([args[0][0], "-I", "-S", "-c", "import time; time.sleep(10)"], *args[1:])
        process = original(*args, **kwargs)
        children.append(process)
        return process
    monkeypatch.setattr("kquant.recovery_preflight.subprocess.Popen", slow_worker)
    started = monotonic()
    result = check(manifest, tmp_path)
    assert monotonic() - started < 4
    assert not result["can_launch"]
    assert "RUNTIME_DATABASE_PROBE_TIMEOUT" in {r["code"] for r in result["errors"]}
    assert children and all(child.poll() is not None for child in children)


def test_actual_exclusive_lock_fails_then_recovers(tmp_path):
    manifest = activated(tmp_path)
    with closing(sqlite3.connect(manifest["databases"][0]["path"])) as db:
        db.execute("BEGIN EXCLUSIVE")
        blocked = check(manifest, tmp_path)
        assert not blocked["can_launch"]
        assert "OperationalError" in {r["code"] for r in blocked["errors"]}
        db.rollback()
    assert check(manifest, tmp_path)["can_launch"]


def test_watermark_identifier_cannot_execute_sql(tmp_path):
    manifest = activated(tmp_path)
    path = Path(manifest["databases"][0]["path"])
    with pytest.raises(ValueError, match="IDENTIFIER"):
        observe_database({"role": "TEST_ONLY", "path": str(path),
            "watermarks": [{"table": "business_events; DROP TABLE business_events", "column": "id", "minimum": 1}]},
            [str(tmp_path)], monotonic() + 5)
    assert check(manifest, tmp_path)["can_launch"]


def test_active_hardlink_cannot_modify_original(tmp_path):
    manifest = activated(tmp_path)
    row = manifest["databases"][0]
    path = Path(row["path"])
    path.unlink()
    path.hardlink_to(row["recovery_path"])
    result = check(manifest, tmp_path)
    assert not result["can_launch"]
    assert "ACTIVE_DATABASE_LINKED_TO_RECOVERY_ORIGINAL" in {r["code"] for r in result["errors"]}


def test_runtime_probe_rejects_f_before_stat(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "lstat", lambda *a, **k: pytest.fail("F stat attempted"))
    with pytest.raises(ValueError, match="FORBIDDEN"):
        observe_database({"role": "minute", "path": r"F:\never-read.sqlite3", "watermarks": []},
            [str(tmp_path)], monotonic() + 5)


def test_receipt_does_not_authorize_changed_continuity(tmp_path):
    manifest = activated(tmp_path)
    manifest["databases"][0]["activation_receipt"] = manifest["databases"][1]["activation_receipt"]
    result = check(manifest, tmp_path)
    assert not result["can_launch"]
    assert "DATABASE_ACTIVATION_RECEIPT_MISMATCH" in {r["code"] for r in result["errors"]}
    assert "CROSS_STORE_ACTIVATION_RECEIPT_MISMATCH" in {r["code"] for r in result["errors"]}
