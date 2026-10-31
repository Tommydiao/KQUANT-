from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from time import monotonic

import pytest

from kquant.recovery_activation import produce
from kquant.recovery_preflight import ROLES, evaluate
from kquant.recovery_runtime_probe import file_identity


def material(tmp_path):
    runtime, original, validated = (tmp_path / x for x in ("runtime", "original", "validated"))
    for path in (runtime, original, validated):
        path.mkdir()
    rows = []
    for role in sorted(ROLES):
        source = original / (role + ".sqlite3")
        snapshot = validated / source.name
        active = runtime / source.name
        with closing(sqlite3.connect(source)) as db:
            db.execute("CREATE TABLE business_events (id INTEGER PRIMARY KEY, payload TEXT)")
            db.execute("INSERT INTO business_events VALUES (1, 'TEST_ONLY retained event')")
            db.commit()
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        shutil.copy2(source, snapshot)
        shutil.copy2(source, active)
        proof = {"test_only": True, "database_path": str(source), "role": role,
            "bytes": source.stat().st_size, "mtime_ns": source.stat().st_mtime_ns,
            "integrity": ["ok"], "verified_at": "TEST_ONLY verified recovery", "wal_shm": [],
            "validated_snapshot": {"path": str(snapshot), "bytes": snapshot.stat().st_size,
                "mtime_ns": snapshot.stat().st_mtime_ns, "integrity": ["ok"],
                "file_identity": file_identity(snapshot), "wal_shm": []}}
        receipt = runtime / (role + "-recovery.json")
        receipt.write_text(json.dumps(proof), encoding="ascii")
        rows.append({"role": role, "path": str(active), "recovery_path": str(source),
            "recovery_state": "COMPLETE_VERIFIED",
            "receipt": {"path": str(receipt), "sha256": sha256(receipt.read_bytes()).hexdigest()},
            "watermarks": [{"table": "business_events", "column": "id"}]})
    return {"schema": "KQUANT_ACTIVATION_REQUEST_V1", "runtime_root": str(runtime),
            "approved_runtime_root": str(runtime), "databases": rows}


def test_real_five_store_receipts_keep_source_and_business_untouched(tmp_path):
    request = material(tmp_path)
    before = {r["role"]: Path(r["recovery_path"]).read_bytes() for r in request["databases"]}
    result = produce(request, roots=[tmp_path], allow_test_only=True)
    assert result["ok"], result
    assert result["database_opens"] == 10
    assert {r["role"] for r in result["activation_receipts"]} == ROLES
    assert all(r["watermarks"][0]["minimum"] == 1 for r in result["activation_receipts"])
    assert result["business_writes"] == result["database_copies"] == result["f_drive_reads"] == 0
    assert not result["can_launch"] and not result["owner_acceptance_written"]
    assert not result["cross_store_continuity_confirmed"]
    assert before == {r["role"]: Path(r["recovery_path"]).read_bytes() for r in request["databases"]}


def portable_material(tmp_path):
    request = material(tmp_path)
    stores = []
    for row in request["databases"]:
        original = Path(row["recovery_path"])
        info = original.stat()
        stores.append({"role": row["role"], "sha256": sha256(original.read_bytes()).hexdigest(),
            "integrity_check": ["ok"], "bytes_unchanged": True, "bytes": info.st_size,
            "mtime_ns": info.st_mtime_ns, "file_identity": file_identity(original)})
    receipt = tmp_path / "restore.json"
    receipt.write_text(json.dumps({"test_only": True,
        "schema": "KQUANT_PORTABLE_COMPUTER_HANDOFF_RESTORE_V1", "core_sha256": "a" * 64,
        "inputs_verified": True, "restored": True, "preserved_snapshots": str(tmp_path / "original"),
        "core_restore": {"stores": stores}}), encoding="ascii")
    for row, store in zip(request["databases"], stores):
        path = Path(row["receipt"]["path"])
        proof = json.loads(path.read_text())
        old_snapshot = Path(proof["validated_snapshot"]["path"])
        proof.update(schema="KQUANT_PORTABLE_SNAPSHOT_PROOF_V1", sha256=store["sha256"],
            core_sha256="a" * 64, restore_receipt={"path": str(receipt), "sha256": sha256(receipt.read_bytes()).hexdigest()})
        proof["validated_snapshot"].update(path=row["recovery_path"], bytes=store["bytes"],
            mtime_ns=store["mtime_ns"], file_identity=store["file_identity"])
        old_snapshot.unlink()
        path.write_text(json.dumps(proof), encoding="ascii")
        row["receipt"]["sha256"] = sha256(path.read_bytes()).hexdigest()
    return request


def test_portable_export_uses_one_preserved_baseline_not_a_third_copy(tmp_path):
    request = portable_material(tmp_path)
    result = produce(request, roots=[tmp_path], allow_test_only=True)
    assert result["ok"], result
    assert result["database_copies"] == 0
    assert not result["can_launch"] and not result["cross_store_continuity_confirmed"]
    assert len(result["activation_receipts"]) == 5


def test_portable_wrong_parent_receipt_is_rejected_before_opening_db(tmp_path, monkeypatch):
    request = portable_material(tmp_path)
    path = Path(request["databases"][0]["receipt"]["path"])
    proof = json.loads(path.read_text())
    proof["core_sha256"] = "b" * 64
    path.write_text(json.dumps(proof), encoding="ascii")
    request["databases"][0]["receipt"]["sha256"] = sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr("kquant.recovery_activation.subprocess.Popen", lambda *a, **k: pytest.fail("DB worker started"))
    result = produce(request, roots=[tmp_path], allow_test_only=True)
    assert result["code"] == "PORTABLE_SNAPSHOT_PROVENANCE_MISMATCH"
    assert result["database_opens"] == 0


def test_produced_receipts_feed_restart_gate_but_do_not_accept_runtime(tmp_path):
    from test_r58_p10_active_restart import activated

    producer_root = tmp_path / "producer"
    producer_root.mkdir()
    request = material(producer_root)
    result = produce(request, roots=[tmp_path], allow_test_only=True)
    assert result["ok"]
    other = tmp_path / "gate"
    other.mkdir()
    manifest = activated(other)
    manifest["runtime_root"] = manifest["approved_runtime_root"] = request["runtime_root"]
    manifest["databases"] = request["databases"]
    for proof, row in zip(result["activation_receipts"], request["databases"]):
        path = Path(request["runtime_root"]) / (row["role"] + "-activation.json")
        path.write_text(json.dumps(proof), encoding="ascii")
        row["activation_receipt"] = {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}
    continuity_path = Path(manifest["continuity"]["receipt"]["path"])
    continuity = json.loads(continuity_path.read_text())
    continuity["database_receipts"] = {r["role"]: r["receipt"]["sha256"] for r in request["databases"]}
    continuity["activation_receipts"] = {r["role"]: r["activation_receipt"]["sha256"] for r in request["databases"]}
    continuity_path.write_text(json.dumps(continuity), encoding="ascii")
    manifest["continuity"]["receipt"]["sha256"] = sha256(continuity_path.read_bytes()).hexdigest()
    manifest["final_runtime_accepted"] = False
    denied = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    assert not denied["can_launch"] and denied["database_opens"] == 0
    # This approval remains an explicitly isolated fixture, not a producer output.
    accepted_path = Path(manifest["acceptance_receipt"]["path"])
    accepted = json.loads(accepted_path.read_text())
    accepted["runtime_root"] = request["runtime_root"]
    accepted["continuity_receipt_sha256"] = manifest["continuity"]["receipt"]["sha256"]
    accepted_path.write_text(json.dumps(accepted), encoding="ascii")
    manifest["acceptance_receipt"]["sha256"] = sha256(accepted_path.read_bytes()).hexdigest()
    manifest["final_runtime_accepted"] = True
    assert evaluate(manifest, roots=[tmp_path], allow_test_only=True)["can_launch"]
    with closing(sqlite3.connect(request["databases"][0]["path"])) as db:
        db.execute("INSERT INTO business_events VALUES (2, 'TEST_ONLY post-activation business')")
        db.commit()
    assert evaluate(manifest, roots=[tmp_path], allow_test_only=True)["can_launch"]


@pytest.mark.parametrize("mutation,code", [
    ("partial_fifth", "DATABASE_RECOVERY_NOT_COMPLETE"),
    ("missing_role", "FIVE_RECOVERED_ROLES_REQUIRED"),
    ("duplicate_role", "FIVE_RECOVERED_ROLES_REQUIRED"),
    ("missing_active", "MISSING_DATABASE_NO_AUTOCREATE"),
    ("old_source_changed", "DATABASE_VERIFICATION_RECEIPT_MISMATCH"),
    ("hardlink", "ACTIVE_DATABASE_NOT_SEPARATE_FROM_ORIGINAL"),
    ("receipt_changed", "RECOVERY_RECEIPT_HASH_MISMATCH"),
    ("no_watermarks", "BUSINESS_BASELINE_SPEC_REQUIRED"),
])
def test_incomplete_material_never_opens_any_database(tmp_path, monkeypatch, mutation, code):
    request = material(tmp_path)
    row = request["databases"][-1]
    if mutation == "partial_fifth":
        row["recovery_state"] = "PARTIAL_DO_NOT_OPEN"
    elif mutation == "missing_role":
        request["databases"].pop()
    elif mutation == "duplicate_role":
        row["role"] = request["databases"][0]["role"]
    elif mutation == "missing_active":
        Path(row["path"]).unlink()
    elif mutation == "old_source_changed":
        Path(row["recovery_path"]).write_bytes(b"TEST_ONLY changed original")
    elif mutation == "hardlink":
        Path(row["path"]).unlink()
        Path(row["path"]).hardlink_to(row["recovery_path"])
    elif mutation == "receipt_changed":
        Path(row["receipt"]["path"]).write_text("{}", encoding="ascii")
    elif mutation == "no_watermarks":
        row["watermarks"] = []
    monkeypatch.setattr("kquant.recovery_activation.subprocess.Popen", lambda *a, **k: pytest.fail("DB worker started"))
    result = produce(request, roots=[tmp_path], allow_test_only=True)
    assert result["ok"] is False and result["code"] == code, result
    assert result["database_opens"] == 0 and not result["activation_receipts"]


@pytest.mark.parametrize("mutation,code", [
    ("snapshot_modified", "VALIDATED_SNAPSHOT_CHANGED"),
    ("active_schema", "ACTIVATION_SCHEMA_MISMATCH"),
    ("active_rewrite", "ACTIVATION_BUSINESS_BASELINE_MISMATCH"),
    ("active_deleted", "ACTIVATION_BUSINESS_BASELINE_MISMATCH"),
    ("active_extra", "ACTIVATION_BUSINESS_BASELINE_MISMATCH"),
])
def test_initial_activation_cannot_rebase_to_bad_current_data(tmp_path, mutation, code):
    request = material(tmp_path)
    row = request["databases"][0]
    if mutation == "snapshot_modified":
        proof = json.loads(Path(row["receipt"]["path"]).read_text())
        with closing(sqlite3.connect(proof["validated_snapshot"]["path"])) as db:
            db.execute("INSERT INTO business_events VALUES (2,'TEST_ONLY changed snapshot')")
            db.commit()
    else:
        with closing(sqlite3.connect(row["path"])) as db:
            db.execute({"active_schema": "CREATE TABLE x (id INTEGER)",
                "active_rewrite": "UPDATE business_events SET payload='TEST_ONLY changed'",
                "active_deleted": "DELETE FROM business_events",
                "active_extra": "INSERT INTO business_events VALUES (2,'TEST_ONLY premature write')"}[mutation])
            db.commit()
    result = produce(request, roots=[tmp_path], allow_test_only=True)
    assert not result["ok"] and result["code"] == code, result
    assert not result["activation_receipts"]


def test_test_only_fact_cannot_become_production_receipt(tmp_path):
    result = produce(material(tmp_path), roots=[tmp_path])
    assert not result["ok"] and result["code"] == "TEST_ONLY_RECEIPT_NOT_PRODUCTION"
    assert result["database_opens"] == 0


def test_f_drive_rejected_before_filesystem_access(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "lstat", lambda *a, **k: pytest.fail("forbidden stat"))
    result = produce({"schema": "KQUANT_ACTIVATION_REQUEST_V1", "runtime_root": r"F:\do-not-read"}, roots=[tmp_path])
    assert result["code"] == "FORBIDDEN_OR_RELATIVE_PATH" and result["database_opens"] == 0


def test_timeout_reaps_real_child(tmp_path, monkeypatch):
    request = material(tmp_path)
    original = subprocess.Popen
    children = []
    def stuck(*args, **kwargs):
        args = ([args[0][0], "-I", "-S", "-c", "import time; time.sleep(20)"], *args[1:])
        child = original(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr("kquant.recovery_activation.subprocess.Popen", stuck)
    start = monotonic()
    result = produce(request, roots=[tmp_path], allow_test_only=True, budget_seconds=0.7)
    assert monotonic() - start < 2
    assert result["code"] == "ACTIVATION_PROBE_TIMEOUT" and result["database_opens"] is None
    assert children and all(child.poll() is not None for child in children)


def test_actual_write_lock_reports_fault_and_can_recover(tmp_path):
    request = material(tmp_path)
    with closing(sqlite3.connect(request["databases"][0]["path"])) as db:
        db.execute("BEGIN EXCLUSIVE")
        result = produce(request, roots=[tmp_path], allow_test_only=True)
        assert not result["ok"] and result["code"] == "OperationalError", result
        db.rollback()
    assert produce(request, roots=[tmp_path], allow_test_only=True)["ok"]


def test_new_snapshot_wal_is_not_silently_adopted(tmp_path):
    request = material(tmp_path)
    row = request["databases"][0]
    proof = json.loads(Path(row["receipt"]["path"]).read_text())
    with closing(sqlite3.connect(proof["validated_snapshot"]["path"])) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("INSERT INTO business_events VALUES (2,'TEST_ONLY snapshot WAL')")
        db.commit()
        result = produce(request, roots=[tmp_path], allow_test_only=True)
        assert not result["ok"]
        assert result["code"] in {"VALIDATED_SNAPSHOT_CHANGED", "VALIDATED_SNAPSHOT_COMPANIONS_CHANGED"}


@pytest.mark.parametrize("budget", [float("nan"), float("inf"), 0, -1])
def test_invalid_budget_cannot_disable_child_deadline(tmp_path, monkeypatch, budget):
    request = material(tmp_path)
    monkeypatch.setattr("kquant.recovery_activation.subprocess.Popen", lambda *a, **k: pytest.fail("DB worker started"))
    result = produce(request, roots=[tmp_path], allow_test_only=True, budget_seconds=budget)
    assert not result["ok"] and result["code"] == "INVALID_ACTIVATION_REQUEST"
    assert result["database_opens"] == 0


def test_real_cli_rejects_nonactivation_candidate_without_db_access(tmp_path):
    entry = Path(__file__).absolute().parents[1]
    request = tmp_path / "test-only-bad-request.json"
    request.write_text("{}", encoding="ascii")
    output = tmp_path / "test-only-result.json"
    # The exact script uses its configured safe roots; no arbitrary tmp directory is added.
    done = subprocess.run([sys.executable, "-I", "-S", str(entry / "scripts/record_recovery_activation.py"),
                           "--request", str(request), "--output", str(output)], capture_output=True, timeout=5)
    assert done.returncode == 2, done.stderr
    result = json.loads(done.stdout)
    assert not result["ok"] and not result["can_launch"]


@pytest.mark.parametrize("bad_output", [None, "database", "existing"])
def test_actual_cli_positive_and_output_safety(tmp_path, bad_output):
    source_entry = Path(__file__).absolute().parents[1]
    entry = tmp_path / "dev"
    (entry / "kquant").mkdir(parents=True)
    (entry / "scripts").mkdir()
    # Use byte-identical current components in a separate TEST_ONLY entry, with its own roots.
    for name in ("kquant/recovery_activation.py", "kquant/recovery_preflight.py",
                 "kquant/recovery_runtime_probe.py", "scripts/record_recovery_activation.py"):
        shutil.copy2(source_entry / name, entry / name)
    data = tmp_path / "data"
    data.mkdir()
    request = material(data)
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="ascii")
    output = tmp_path / ("must-not-create.sqlite3" if bad_output == "database" else "result.json")
    if bad_output == "existing":
        output.write_bytes(b"TEST_ONLY previous evidence")
    done = subprocess.run([sys.executable, "-I", "-S", str(entry / "scripts/record_recovery_activation.py"),
        "--request", str(request_path), "--output", str(output), "--test-only"], capture_output=True, timeout=7)
    result = json.loads(done.stdout)
    if bad_output:
        assert done.returncode == 2 and result["database_opens"] == 0, (result, done.stderr)
        if bad_output == "database":
            assert not output.exists() and result["code"] == "FACT_OUTPUT_MUST_BE_JSON_NOT_A_DATABASE"
        else:
            assert output.read_bytes() == b"TEST_ONLY previous evidence"
    else:
        assert done.returncode == 0 and result["ok"], (result, done.stderr)
        saved = json.loads(output.read_text())
        assert len(saved["activation_receipts"]) == 5 and saved["database_opens"] == 10
        assert all(r["test_only"] for r in saved["activation_receipts"])
        assert not saved["can_launch"] and not saved["owner_acceptance_written"]
