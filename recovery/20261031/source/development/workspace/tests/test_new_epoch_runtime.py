from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from time import monotonic

import pytest

from kquant.options_data_paths import connect_store, resolve_stores
from kquant.recovery_preflight import NEW_EPOCH, OLD_RECORDS, candidate_hash, canonical_hash, evaluate
from kquant.recovery_runtime_probe import observe_database
from new_data_epoch import initialize
from test_r58_p10_active_restart import activated


def epoch_candidate(tmp_path):
    manifest = activated(tmp_path)
    root = Path(manifest["runtime_root"])

    def receipt(name, value):
        path = root / (name + ".json")
        path.write_text(json.dumps({"test_only": True, **value}), encoding="ascii")
        return {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}

    schema = "CREATE TABLE business_events(id INTEGER PRIMARY KEY,payload TEXT);"
    minute = root / "work/options_one_minute-epoch-20261007/one_minute.sqlite3"
    declaration = {"schema": "KQUANT_NEW_MINUTE_EPOCH_V1", "runtime_root": str(root),
        "minute_path": str(minute), "epoch_id": "TEST_ONLY-20261007", "session": "2026-10-07",
        "schema_sha256": sha256(schema.encode()).hexdigest(),
        "preserved_roles": ["main", "full_watch", "opening_research", "signal_copilot"],
        "unresolved_old_records": sorted(OLD_RECORDS), "old_position_continuity": "UNKNOWN",
        "complete_restoration_claimed": False, "execution_enabled": False,
        "qualified_signal_authorized": False, "test_only": True}
    scope = {"gate": "O-SETUP", "status": "APPROVED", "approved_by": "OWNER",
        "decision": "NEW_MINUTE_EPOCH", "runtime_root": str(root), "minute_path": str(minute),
        "epoch_id": declaration["epoch_id"], "session": declaration["session"],
        "declaration_sha256": canonical_hash(declaration), "old_position_continuity": "UNKNOWN",
        "accepted_at": "2026-10-07T03:00:00+00:00", "human_decision_evidence": "TEST_ONLY isolated receipt",
        "test_only": True}
    created = initialize(declaration, scope, roots=[tmp_path], schema=schema, allow_test_only=True)
    assert created["ok"], created
    with closing(sqlite3.connect(minute)) as db:
        metadata = json.loads(db.execute("SELECT payload_json FROM data_epoch_boundary").fetchone()[0])
    boundary = {k: v for k, v in metadata.items() if k != "created_at"}
    observed = observe_database({"role": "minute", "path": str(minute), "epoch_boundary": boundary,
        "watermarks": [{"table": "data_epoch_boundary", "column": "id", "minimum": 1},
                       {"table": "business_events", "column": "id", "minimum": None}]},
        [str(tmp_path)], monotonic() + 5)
    activation = receipt("new-minute-activation", {"schema": "KQUANT_NEW_EPOCH_ACTIVATION_V1",
        "role": "minute", "database_path": str(minute), "epoch_boundary": boundary,
        "verified_at": "TEST_ONLY", "file_identity": observed["file_identity"],
        "schema_sha256": observed["schema_sha256"], "watermarks": observed["watermarks"]})
    manifest["schema"] = NEW_EPOCH
    manifest["databases"] = [r for r in manifest["databases"] if r["role"] != "minute"]
    manifest["databases"].append({"role": "minute", "path": str(minute),
        "recovery_state": "NEW_EPOCH_VERIFIED", "activation_receipt": activation})
    manifest["epoch_declaration"] = receipt("epoch-declaration", declaration)
    manifest["data_scope_acceptance"] = receipt("epoch-data-scope", scope)
    opening = next(r["path"] for r in manifest["databases"] if r["role"] == "opening_research")
    manifest["runtime_path_binding"] = receipt("epoch-path-binding", {
        "schema": "KQUANT_NEW_EPOCH_RUNTIME_PATHS_V1", "runtime_root": str(root),
        "minute_path": str(minute), "opening_research_path": opening,
        "epoch_id": declaration["epoch_id"], "session": declaration["session"],
        "data_scope_acceptance_sha256": canonical_hash(scope)})
    continuity = receipt("epoch-continuity", {"status": "NEW_EPOCH_OLD_RECORDS_UNKNOWN",
        "old_position_continuity": "UNKNOWN", "unresolved_old_records": sorted(OLD_RECORDS),
        "epoch_boundary": boundary, "watermarks": {r["role"]: "TEST_ONLY" for r in manifest["databases"]},
        "database_receipts": {r["role"]: r["receipt"]["sha256"] for r in manifest["databases"] if r["role"] != "minute"},
        "activation_receipts": {r["role"]: r["activation_receipt"]["sha256"] for r in manifest["databases"]}})
    manifest["continuity"] = {"status": "NEW_EPOCH_OLD_RECORDS_UNKNOWN",
        "reconciled_roles": declaration["preserved_roles"], "receipt": continuity}
    manifest["acceptance_receipt"] = receipt("epoch-runtime-acceptance", {
        "gate": "O-LAUNCH", "status": "APPROVED", "approved_by": "OWNER",
        "candidate_id": "TEST_ONLY", "runtime_root": str(root),
        "continuity_receipt_sha256": continuity["sha256"], "candidate_payload_sha256": candidate_hash(manifest),
        "accepted_at": scope["accepted_at"], "human_decision_evidence": "TEST_ONLY isolated final acceptance"})
    return manifest


def test_real_initializer_restart_gate_and_independent_store_paths(tmp_path, monkeypatch):
    manifest = epoch_candidate(tmp_path)
    files = {p: sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*.sqlite3")}
    result = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    assert result["can_launch"], result
    assert result["old_position_continuity"] == "UNKNOWN"
    assert result["database_opens"] == 5
    assert not result["qualified_signal_authorized"]
    assert result["business_writes"] == result["f_drive_reads"] == 0
    assert files == {p: sha256(p.read_bytes()).hexdigest() for p in files}
    binding = result["runtime_path_binding"]
    monkeypatch.setenv("KQUANT_RUNTIME_PATH_BINDING", binding["path"])
    monkeypatch.setenv("KQUANT_RUNTIME_PATH_BINDING_SHA256", binding["sha256"])
    paths = resolve_stores(Path(manifest["runtime_root"]))
    assert paths["minute"] != paths["opening_research"]
    assert paths["minute"].parent != paths["opening_research"].parent
    with closing(connect_store(paths["minute"])) as db, db:
        db.execute("INSERT INTO business_events VALUES(1,'TEST_ONLY new data')")
    assert evaluate(manifest, roots=[tmp_path], allow_test_only=True)["can_launch"]


@pytest.mark.parametrize("change,code", [
    ("unaccepted", "FINAL_RUNTIME_NOT_ACCEPTED"),
    ("scope", "HASH_MISMATCH"), ("source", "HASH_MISMATCH"),
    ("fake_recovery", "NEW_EPOCH_ACTIVATION_RECEIPT_MISMATCH"),
    ("confirmed", "NEW_EPOCH_CONTINUITY_BOUNDARY_MISMATCH"),
    ("rebound", "EXACT_RUNTIME_PATH_BINDING_MISMATCH"),
    ("candidate", "EXACT_NEW_EPOCH_RUNTIME_ACCEPTANCE_MISMATCH"),
    ("missing_store", "NEW_EPOCH_ACTIVATION_RECEIPT_MISMATCH"),
])
def test_failed_epoch_contract_never_opens_db(tmp_path, change, code):
    manifest = epoch_candidate(tmp_path)
    row = next(r for r in manifest["databases"] if r["role"] == "minute")
    if change == "unaccepted":
        manifest["final_runtime_accepted"] = False
    elif change == "scope":
        Path(manifest["data_scope_acceptance"]["path"]).write_text("{}", encoding="ascii")
    elif change == "source":
        Path(manifest["required_source"][0]["path"]).write_text("{}", encoding="ascii")
    elif change == "fake_recovery":
        row["recovery_state"] = "COMPLETE_VERIFIED"
    elif change == "confirmed":
        manifest["continuity"]["status"] = "CONFIRMED"
    elif change == "rebound":
        row["path"] = str(tmp_path / "different.sqlite3")
    elif change == "candidate":
        manifest["candidate_id"] = "TEST_ONLY changed after signature"
    elif change == "missing_store":
        Path(row["path"]).unlink()
    result = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    assert not result["can_launch"]
    assert result["database_opens"] == 0
    assert not result["runtime_path_binding"]
    assert code in {r["code"] for r in result["errors"]}, result
    if change == "missing_store":
        assert not Path(row["path"]).exists()


def test_test_only_acceptance_never_authorizes_production(tmp_path):
    result = evaluate(epoch_candidate(tmp_path), roots=[tmp_path])
    assert not result["can_launch"] and result["database_opens"] == 0
    assert "TEST_ONLY_RECEIPT_NOT_PRODUCTION" in {r["code"] for r in result["errors"]}


def test_boundary_tamper_fails_actual_read_only_worker(tmp_path):
    manifest = epoch_candidate(tmp_path)
    minute = next(r["path"] for r in manifest["databases"] if r["role"] == "minute")
    with closing(sqlite3.connect(minute)) as db, db:
        value = json.loads(db.execute("SELECT payload_json FROM data_epoch_boundary").fetchone()[0])
        value["old_position_continuity"] = "CONFIRMED"
        db.execute("UPDATE data_epoch_boundary SET payload_json=?", (json.dumps(value),))
    result = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    assert not result["can_launch"]
    assert "NEW_EPOCH_DATABASE_BOUNDARY_CHANGED" in {r["code"] for r in result["errors"]}


@pytest.mark.parametrize("change", ["hash", "missing", "derived_research", "fault_path"])
def test_module_path_binding_fails_without_creating_files(tmp_path, monkeypatch, change):
    manifest = epoch_candidate(tmp_path)
    binding = manifest["runtime_path_binding"]
    path = Path(binding["path"])
    value = json.loads(path.read_text())
    if change == "missing":
        Path(value["minute_path"]).unlink()
    elif change == "derived_research":
        value["opening_research_path"] = str(Path(value["minute_path"]).with_name("opening_trend_research.sqlite3"))
        path.write_text(json.dumps(value), encoding="ascii")
    elif change == "fault_path":
        value["minute_path"] = r"F:\never-read.sqlite3"
        path.write_text(json.dumps(value), encoding="ascii")
    expected = "0" * 64 if change == "hash" else sha256(path.read_bytes()).hexdigest()
    monkeypatch.setenv("KQUANT_RUNTIME_PATH_BINDING", str(path))
    monkeypatch.setenv("KQUANT_RUNTIME_PATH_BINDING_SHA256", expected)
    with pytest.raises((ValueError, FileNotFoundError)):
        resolve_stores(Path(manifest["runtime_root"]))
    if change == "missing":
        assert not Path(value["minute_path"]).exists()


def test_actual_business_modules_import_exact_independent_paths(tmp_path):
    manifest = epoch_candidate(tmp_path)
    binding = manifest["runtime_path_binding"]
    code = """
import json,os,sys
from pathlib import Path
os.environ['KQUANT_RUNTIME_PATH_BINDING']=sys.argv[1]
os.environ['KQUANT_RUNTIME_PATH_BINDING_SHA256']=sys.argv[2]
import kquant.options_data_paths as paths
original=paths.resolve_stores
paths.resolve_stores=lambda root: original(Path(sys.argv[3]))
from kquant import options_one_minute as minute, options_opening_trend_store as opening
print(json.dumps({'minute':str(minute.STORE),'opening':str(opening.STORE)}))
"""
    result = subprocess.run([sys.executable, "-c", code, binding["path"], binding["sha256"], manifest["runtime_root"]],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    value = json.loads(Path(binding["path"]).read_text())
    assert actual == {"minute": value["minute_path"], "opening": value["opening_research_path"]}


def test_bound_write_never_recreates_deleted_store(tmp_path, monkeypatch):
    missing = tmp_path / "missing.sqlite3"
    monkeypatch.setenv("KQUANT_RUNTIME_PATH_BINDING", "TEST_ONLY")
    with pytest.raises(sqlite3.OperationalError):
        connect_store(missing)
    assert not missing.exists()


def test_launcher_env_loader_cannot_override_verified_binding(tmp_path):
    launcher = Path(__file__).parents[1] / "start_kquant_workspace.ps1"
    env_file = tmp_path / "TEST_ONLY.env"
    env_file.write_text("KQUANT_RUNTIME_PATH_BINDING=F:\\never-read.json\n"
                        "KQUANT_RUNTIME_PATH_BINDING_SHA256=forged\nTEST_ONLY_VALUE=ok\n", encoding="ascii")
    command = """
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($env:TEST_ONLY_LAUNCHER,[ref]$tokens,[ref]$errors)
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Import-LocalEnv'},$true)
Invoke-Expression $function.Extent.Text
$env:KQUANT_RUNTIME_PATH_BINDING='TEST_ONLY_verified'
$env:KQUANT_RUNTIME_PATH_BINDING_SHA256='TEST_ONLY_verified_hash'
$env:TEST_ONLY_VALUE=''
Import-LocalEnv $env:TEST_ONLY_ENV_FILE
@{binding=$env:KQUANT_RUNTIME_PATH_BINDING;hash=$env:KQUANT_RUNTIME_PATH_BINDING_SHA256;ordinary=$env:TEST_ONLY_VALUE} | ConvertTo-Json -Compress
"""
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True, text=True, timeout=10, env={**os.environ,
            "TEST_ONLY_LAUNCHER": str(launcher), "TEST_ONLY_ENV_FILE": str(env_file)})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"binding": "TEST_ONLY_verified", "hash": "TEST_ONLY_verified_hash", "ordinary": "ok"}


@pytest.mark.parametrize("component", ["minute", "opening", "manual", "journal"])
def test_actual_writers_do_not_replace_missing_accepted_data(tmp_path, monkeypatch, component):
    from kquant import options_one_minute, options_opening_trend_store, options_one_minute_manual
    from kquant import options_opening_momentum_journal
    functions = {"minute": options_one_minute.initialize, "opening": options_opening_trend_store.initialize,
                 "manual": lambda path: options_one_minute_manual.persist_monitor_state({}, {}, path=path),
                 "journal": options_opening_momentum_journal.initialize}
    missing = tmp_path / "missing.sqlite3"
    monkeypatch.setenv("KQUANT_RUNTIME_PATH_BINDING", "TEST_ONLY")
    with pytest.raises(sqlite3.OperationalError):
        functions[component](missing)
    assert not missing.exists()
