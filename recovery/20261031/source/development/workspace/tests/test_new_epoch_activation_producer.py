"""Actual SQLite/worker checks using only isolated, explicitly TEST_ONLY material."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

import pytest

from kquant.recovery_activation import NEW_EPOCH_REQUEST, produce
from kquant.recovery_preflight import NEW_EPOCH, OLD_RECORDS, ROLES, candidate_hash, canonical_hash, evaluate
from new_data_epoch import initialize
from test_r58_p10_activation_producer import material


def receipt(runtime, name, value):
    path = runtime / (name + ".json")
    path.write_text(json.dumps({"test_only": True, **value}), encoding="ascii")
    return {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}


def epoch_material(tmp_path):
    request = material(tmp_path)
    runtime = Path(request["runtime_root"])
    request["schema"] = NEW_EPOCH_REQUEST
    request["databases"] = [row for row in request["databases"] if row["role"] != "minute"]
    minute = runtime / "work/options_one_minute-epoch-20261007/one_minute.sqlite3"
    schema = "CREATE TABLE business_events (id INTEGER PRIMARY KEY,payload TEXT);"
    declaration = {"schema": "KQUANT_NEW_MINUTE_EPOCH_V1", "runtime_root": str(runtime),
        "minute_path": str(minute), "epoch_id": "TEST_ONLY-activation-20261007", "session": "2026-10-07",
        "schema_sha256": sha256(schema.encode()).hexdigest(), "preserved_roles": sorted(ROLES - {"minute"}),
        "unresolved_old_records": sorted(OLD_RECORDS), "old_position_continuity": "UNKNOWN",
        "complete_restoration_claimed": False, "execution_enabled": False,
        "qualified_signal_authorized": False, "test_only": True}
    acceptance = {"gate": "O-SETUP", "status": "APPROVED", "approved_by": "OWNER",
        "decision": "NEW_MINUTE_EPOCH", "runtime_root": str(runtime), "minute_path": str(minute),
        "epoch_id": declaration["epoch_id"], "session": declaration["session"],
        "declaration_sha256": canonical_hash(declaration), "old_position_continuity": "UNKNOWN",
        "accepted_at": "2026-10-07T05:00:00+00:00", "human_decision_evidence": "TEST_ONLY isolated fixture",
        "test_only": True}
    assert initialize(declaration, acceptance, roots=[tmp_path], schema=schema, allow_test_only=True)["ok"]
    with closing(sqlite3.connect(minute)) as db, db:
        db.execute("INSERT INTO business_events VALUES (1,'TEST_ONLY new epoch event')")
    request["epoch_declaration"] = receipt(runtime, "declaration", declaration)
    request["data_scope_acceptance"] = receipt(runtime, "data-scope", acceptance)
    request["databases"].append({"role": "minute", "path": str(minute), "recovery_state": "NEW_EPOCH_VERIFIED",
        "watermarks": [{"table": "data_epoch_boundary", "column": "id"},
                       {"table": "business_events", "column": "id"}]})
    return request


def gate_manifest(request, result):
    runtime = Path(request["runtime_root"])
    rows = request["databases"]
    for row, proof in zip(rows, result["activation_receipts"]):
        assert row["role"] == proof["role"]
        row["activation_receipt"] = receipt(runtime, row["role"] + "-activation", proof)
    minute_proof = next(p for p in result["activation_receipts"] if p["role"] == "minute")
    declaration = json.loads(Path(request["epoch_declaration"]["path"]).read_text())
    scope = json.loads(Path(request["data_scope_acceptance"]["path"]).read_text())
    source = receipt(runtime, "source", {"kind": "TEST_ONLY source/frontend fixture"})
    binding = receipt(runtime, "binding", {"schema": "KQUANT_NEW_EPOCH_RUNTIME_PATHS_V1",
        "runtime_root": str(runtime), "minute_path": declaration["minute_path"],
        "opening_research_path": next(r["path"] for r in rows if r["role"] == "opening_research"),
        "session": declaration["session"], "epoch_id": declaration["epoch_id"],
        "data_scope_acceptance_sha256": canonical_hash(scope)})
    continuity = receipt(runtime, "continuity", {"status": "NEW_EPOCH_OLD_RECORDS_UNKNOWN",
        "old_position_continuity": "UNKNOWN", "unresolved_old_records": sorted(OLD_RECORDS),
        "epoch_boundary": minute_proof["epoch_boundary"],
        "watermarks": {p["role"]: p["watermarks"] for p in result["activation_receipts"]},
        "database_receipts": {r["role"]: r["receipt"]["sha256"] for r in rows if r["role"] != "minute"},
        "activation_receipts": {r["role"]: r["activation_receipt"]["sha256"] for r in rows}})
    dependencies = {"verified_versions": {"TEST_ONLY": "1"}, "active_paths": [str(runtime)]}
    dependencies["receipt"] = receipt(runtime, "dependencies", {"status": "VERIFIED",
        "versions": dependencies["verified_versions"], "active_paths": dependencies["active_paths"]})
    manifest = {"schema": NEW_EPOCH, "candidate_id": "TEST_ONLY exact new epoch",
        "runtime_root": str(runtime), "approved_runtime_root": str(runtime),
        "required_source": [source], "frontend": [source], "databases": rows,
        "epoch_declaration": request["epoch_declaration"], "data_scope_acceptance": request["data_scope_acceptance"],
        "runtime_path_binding": binding, "dependencies": dependencies,
        "continuity": {"status": "NEW_EPOCH_OLD_RECORDS_UNKNOWN", "reconciled_roles": sorted(ROLES - {"minute"}),
                       "receipt": continuity}, "final_runtime_accepted": False}
    # Human approval is a marked fixture supplied separately, never a producer output.
    manifest["acceptance_receipt"] = receipt(runtime, "final-acceptance", {"gate": "O-LAUNCH", "status": "APPROVED",
        "approved_by": "OWNER", "candidate_id": manifest["candidate_id"], "runtime_root": str(runtime),
        "continuity_receipt_sha256": continuity["sha256"], "candidate_payload_sha256": candidate_hash(manifest),
        "accepted_at": scope["accepted_at"], "human_decision_evidence": "TEST_ONLY separate final-decision fixture"})
    return manifest


def test_four_retained_and_new_minute_facts_do_not_claim_recovery_or_acceptance(tmp_path):
    request = epoch_material(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.sqlite3")}
    result = produce(request, roots=[tmp_path], allow_test_only=True)
    assert result["ok"], result
    assert result["database_opens"] == 9
    assert result["business_writes"] == result["database_copies"] == result["f_drive_reads"] == 0
    assert not result["can_launch"] and not result["owner_acceptance_written"]
    assert not result["cross_store_continuity_confirmed"] and not result["qualified_signal_authorized"]
    assert result["old_position_continuity"] == result["old_business_continuity"] == "UNKNOWN"
    assert before == {p: p.read_bytes() for p in before}
    proofs = result["activation_receipts"]
    minute = next(p for p in proofs if p["role"] == "minute")
    assert minute["schema"] == "KQUANT_NEW_EPOCH_ACTIVATION_V1"
    assert "recovery_receipt_sha256" not in minute and "baseline_snapshot" not in minute
    assert all(p["schema"] == "KQUANT_DATABASE_ACTIVATION_V1" for p in proofs if p["role"] != "minute")
    assert {m["table"]: m["minimum"] for m in minute["watermarks"]} == {"data_epoch_boundary": 1, "business_events": 1}


def test_actual_producer_facts_feed_new_epoch_gate_and_detect_new_business_tamper(tmp_path):
    request = epoch_material(tmp_path)
    result = produce(request, roots=[tmp_path], allow_test_only=True)
    assert result["ok"], result
    manifest = gate_manifest(request, result)
    denied = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    assert not denied["can_launch"] and denied["database_opens"] == 0
    manifest["final_runtime_accepted"] = True
    assert evaluate(manifest, roots=[tmp_path], allow_test_only=True)["can_launch"]
    assert not evaluate(manifest, roots=[tmp_path])["can_launch"]
    minute = next(row["path"] for row in request["databases"] if row["role"] == "minute")
    with closing(sqlite3.connect(minute)) as db, db:
        db.execute("INSERT INTO business_events VALUES (2,'TEST_ONLY later new event')")
    assert evaluate(manifest, roots=[tmp_path], allow_test_only=True)["can_launch"]
    with closing(sqlite3.connect(minute)) as db, db:
        db.execute("UPDATE business_events SET payload='TEST_ONLY rewritten baseline' WHERE id=1")
    changed = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    assert not changed["can_launch"]
    assert "ACTIVE_DATABASE_BUSINESS_BASELINE_CHANGED" in {r["code"] for r in changed["errors"]}


@pytest.mark.parametrize("mutation,code", [
    ("unaccepted", "EXACT_DATA_SCOPE_ACCEPTANCE_MISMATCH"),
    ("material_hash", "NEW_EPOCH_MATERIAL_HASH_MISMATCH"),
    ("scope_mismatch", "EXACT_DATA_SCOPE_ACCEPTANCE_MISMATCH"),
    ("invalid_stamp", "EXACT_DATA_SCOPE_ACCEPTANCE_MISMATCH"),
    ("test_only", "TEST_ONLY_RECEIPT_NOT_PRODUCTION"),
    ("fake_recovery", "NEW_EPOCH_ACTIVATION_REQUEST_MISMATCH"),
    ("missing", "NEW_EPOCH_ACTIVATION_REQUEST_MISMATCH"),
    ("wrong_session_path", "NEW_EPOCH_DECLARATION_MISMATCH"),
    ("missing_boundary_mark", "NEW_EPOCH_BOUNDARY_WATERMARK_REQUIRED"),
])
def test_invalid_new_epoch_material_never_starts_db_worker(tmp_path, monkeypatch, mutation, code):
    request = epoch_material(tmp_path)
    row = request["databases"][-1]
    allow_test_only = mutation != "test_only"
    if mutation in {"unaccepted", "scope_mismatch", "invalid_stamp"}:
        scope = json.loads(Path(request["data_scope_acceptance"]["path"]).read_text())
        if mutation == "invalid_stamp":
            scope["accepted_at"] = 1
        else:
            scope["status" if mutation == "unaccepted" else "epoch_id"] = "TEST_ONLY mismatch"
        request["data_scope_acceptance"] = receipt(Path(request["runtime_root"]), "data-scope", scope)
    elif mutation == "material_hash":
        Path(request["epoch_declaration"]["path"]).write_text("{}")
    elif mutation == "fake_recovery":
        row["recovery_state"] = "COMPLETE_VERIFIED"
    elif mutation == "missing":
        Path(row["path"]).unlink()
    elif mutation == "wrong_session_path":
        declaration = json.loads(Path(request["epoch_declaration"]["path"]).read_text())
        declaration["session"] = "2026-10-08"
        request["epoch_declaration"] = receipt(Path(request["runtime_root"]), "declaration", declaration)
    elif mutation == "missing_boundary_mark":
        row["watermarks"] = [{"table": "business_events", "column": "id"}]
    monkeypatch.setattr("kquant.recovery_activation.subprocess.Popen", lambda *a, **k: pytest.fail("DB worker started"))
    result = produce(request, roots=[tmp_path], allow_test_only=allow_test_only)
    assert not result["ok"] and result["code"] == code, result
    assert result["database_opens"] == 0 and not result["activation_receipts"]
    if mutation == "missing":
        assert not Path(row["path"]).exists()


def test_actual_boundary_tamper_is_rejected_by_worker(tmp_path):
    request = epoch_material(tmp_path)
    minute = request["databases"][-1]["path"]
    with closing(sqlite3.connect(minute)) as db, db:
        payload = json.loads(db.execute("SELECT payload_json FROM data_epoch_boundary").fetchone()[0])
        payload["old_position_continuity"] = "CONFIRMED"
        db.execute("UPDATE data_epoch_boundary SET payload_json=?", (json.dumps(payload),))
    result = produce(request, roots=[tmp_path], allow_test_only=True)
    assert not result["ok"] and result["code"] == "NEW_EPOCH_DATABASE_BOUNDARY_CHANGED", result
    assert not result["activation_receipts"] and not result["owner_acceptance_written"]
