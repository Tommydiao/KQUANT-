from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import subprocess
import sqlite3
import sys

import pytest

from kquant.recovery_preflight import BoundaryError, ROLES, checked_path, evaluate, safe_relative


def ready(tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    def receipt(name, value):
        path = root / (name + ".json")
        path.write_text(json.dumps({"test_only": True, **value}), encoding="ascii")
        return {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}
    source = receipt("source", {"scope": "TEST_ONLY"})
    databases = []
    for role in sorted(ROLES):
        path = root / (role + ".sqlite3")
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE test_only (id INTEGER)")
            integrity = [r[0] for r in db.execute("PRAGMA integrity_check")]
        proof = receipt(role, {"role": role, "database_path": str(path), "bytes": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns, "integrity": integrity, "verified_at": "TEST_ONLY", "wal_shm": []})
        databases.append({"role": role, "path": str(path), "recovery_state": "COMPLETE_VERIFIED", "receipt": proof})
    continuity = receipt("continuity", {"status": "CONFIRMED",
        "database_receipts": {r["role"]: r["receipt"]["sha256"] for r in databases},
        "watermarks": {r: "TEST_ONLY" for r in ROLES}, "unresolved_business_gaps": []})
    dependencies = {"verified_versions": {"test-only": "1"}, "active_paths": [str(root)]}
    dependencies["receipt"] = receipt("dependencies", {"status": "VERIFIED", "versions": dependencies["verified_versions"],
        "active_paths": dependencies["active_paths"]})
    acceptance = receipt("acceptance", {"status": "APPROVED", "approved_by": "OWNER", "runtime_root": str(root),
        "candidate_id": "TEST_ONLY", "continuity_receipt_sha256": continuity["sha256"]})
    manifest = {"schema": "KQUANT_SAFE_RECOVERY_V1", "runtime_root": str(root),
        "candidate_id": "TEST_ONLY", "approved_runtime_root": str(root), "required_source": [source], "frontend": [source],
        "databases": databases, "continuity": {"status": "CONFIRMED", "reconciled_roles": sorted(ROLES), "receipt": continuity},
        "dependencies": dependencies, "final_runtime_accepted": True, "acceptance_receipt": acceptance}
    return manifest


def test_positive_gate_only_does_small_file_checks(tmp_path):
    manifest = ready(tmp_path)
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    result = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    assert result["can_launch"]
    assert result["database_opens"] == result["business_writes"] == result["f_drive_reads"] == 0
    assert result["qualified_signal_authorized"] is False
    assert before == {p: p.stat().st_mtime_ns for p in before}


def test_f_path_rejected_before_any_stat(tmp_path, monkeypatch):
    def no_io(*args, **kwargs):
        raise AssertionError("filesystem access before drive rejection")
    monkeypatch.setattr(Path, "lstat", no_io)
    with pytest.raises(BoundaryError, match="FORBIDDEN"):
        checked_path(r"F:\KQUANT-\work\minute.sqlite3", [tmp_path])


@pytest.mark.parametrize("value", ["../x", "/absolute", "x\\y", "F:x", ""])
def test_relative_artifact_boundaries(value):
    with pytest.raises(BoundaryError):
        safe_relative(value)


@pytest.mark.parametrize("mutation,code", [
    ("source", "FileNotFoundError"), ("same_size_change", "HASH_MISMATCH"),
    ("partial", "DATABASE_RECOVERY_NOT_COMPLETE"), ("missing", "MISSING_DATABASE_NO_AUTOCREATE"),
    ("copilot", "UNDECLARED_BUSINESS_DATABASE"), ("continuity", "CROSS_STORE_CONTINUITY_UNCONFIRMED"),
    ("dependencies", "DEPENDENCY_RUNTIME_UNVERIFIED"), ("acceptance", "FINAL_RUNTIME_NOT_ACCEPTED"),
    ("target", "RUNTIME_TARGET_NOT_ACCEPTED"), ("active_f", "FORBIDDEN_OR_RELATIVE_PATH"),
])
def test_missing_changed_partial_or_unaccepted_candidate_fails(tmp_path, mutation, code):
    manifest = ready(tmp_path)
    if mutation == "source":
        manifest["required_source"].append({"path": str(tmp_path / "missing.py"), "sha256": "0" * 64})
    elif mutation == "same_size_change":
        p = Path(manifest["required_source"][0]["path"])
        p.write_bytes(p.read_bytes().replace(b"TEST_ONLY", b"TEST_LOST"))
    elif mutation == "partial":
        manifest["databases"][0]["recovery_state"] = "PARTIAL_DO_NOT_OPEN"
        manifest["databases"][0]["path"] = r"F:\never-read.sqlite3"
    elif mutation == "missing":
        Path(manifest["databases"][0]["path"]).unlink()
    elif mutation == "copilot":
        manifest["databases"] = [r for r in manifest["databases"] if r["role"] != "signal_copilot"]
    elif mutation == "continuity":
        manifest["continuity"]["status"] = "UNKNOWN"
    elif mutation == "dependencies":
        manifest["dependencies"]["verified_versions"] = {}
    elif mutation == "acceptance":
        manifest["final_runtime_accepted"] = False
    elif mutation == "target":
        manifest["runtime_root"] = str(tmp_path / "unaccepted")
    elif mutation == "active_f":
        manifest["dependencies"]["active_paths"] = [r"F:\old-env"]
    result = evaluate(manifest, roots=[tmp_path])
    assert not result["can_launch"]
    assert code in {row["code"] for row in result["errors"]}
    assert result["database_opens"] == result["f_drive_reads"] == 0


def test_reparse_parent_is_rejected(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    link = tmp_path / "junction"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(original)], check=True, capture_output=True)
    try:
        with pytest.raises(BoundaryError, match="REPARSE"):
            checked_path(str(link / "future.sqlite3"), [tmp_path])
    finally:
        # Remove the junction entry only; never recurse through its destination.
        link.rmdir()


def test_budget_exhaustion_is_not_success(tmp_path):
    result = evaluate(ready(tmp_path), roots=[tmp_path], budget_seconds=0)
    assert not result["can_launch"]
    assert "PREFLIGHT_BUDGET_EXHAUSTED" in {row["code"] for row in result["errors"]}


def test_existing_wal_not_declared_in_receipt_cannot_pass(tmp_path):
    manifest = ready(tmp_path)
    Path(manifest["databases"][0]["path"] + "-wal").write_bytes(b"TEST_ONLY")
    result = evaluate(manifest, roots=[tmp_path])
    assert not result["can_launch"]
    assert "DATABASE_COMPANION_SET_MISMATCH" in {r["code"] for r in result["errors"]}


def test_old_or_unrelated_receipt_cannot_pass(tmp_path):
    manifest = ready(tmp_path)
    manifest["databases"][0]["receipt"] = manifest["required_source"][0]
    result = evaluate(manifest, roots=[tmp_path])
    assert not result["can_launch"]
    assert "DATABASE_VERIFICATION_RECEIPT_MISMATCH" in {r["code"] for r in result["errors"]}


def test_test_only_receipts_are_not_production_acceptance(tmp_path):
    result = evaluate(ready(tmp_path), roots=[tmp_path])
    assert not result["can_launch"]
    assert "TEST_ONLY_RECEIPT_NOT_PRODUCTION" in {r["code"] for r in result["errors"]}


def test_actual_launcher_rejects_f_manifest_before_lifecycle(tmp_path):
    launcher = Path(__file__).parents[1] / "start_kquant_workspace.ps1"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher),
        "-RecoveryManifest", r"F:\never-open-manifest.json", "-OptionsFoundation", "-OneMinuteShadow", "-NoBrowser"],
        capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "SAFE_RECOVERY_PATH_NOT_ON_APPROVED_LOCAL_DRIVE" in result.stderr
    assert "FoundationLifecycle" not in result.stderr


def test_actual_launcher_stops_before_lifecycle_and_credential_load(tmp_path):
    launcher = Path(__file__).parents[1] / "start_kquant_workspace.ps1"
    main_db = launcher.parent / "work/kquant_us.sqlite3"
    def file_hash(path):
        if not path.is_file():
            return None
        value = sha256()
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                value.update(block)
        return value.hexdigest()
    before = file_hash(main_db)
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher),
        "-OptionsFoundation", "-OneMinuteShadow", "-NoBrowser"], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "SAFE_RECOVERY_REQUIRED" in result.stderr
    assert "FoundationLifecycle" not in result.stderr
    assert file_hash(main_db) == before


def checker_module():
    path = Path(__file__).parents[1] / "scripts/check_safe_recovery.py"
    spec = importlib.util.spec_from_file_location("TEST_ONLY_entry_checker", path)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    return checker


@pytest.mark.parametrize("field", ["runtime_root", "approved_runtime_root"])
def test_unbound_entry_rejected_before_evaluator_can_observe_databases(tmp_path, monkeypatch, field):
    checker = checker_module()
    entry = tmp_path / "actual-entry"
    entry.mkdir()
    value = {"runtime_root": str(entry), "approved_runtime_root": str(entry)}
    value[field] = str(tmp_path / "other-entry")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(value), encoding="ascii")
    monkeypatch.setattr(checker.module, "evaluate", lambda *a, **k: pytest.fail("unbound evaluator called"))
    result = checker.check_manifest(manifest, [tmp_path], entry)
    assert not result["can_launch"] and result["database_opens"] == 0
    assert result["errors"][0]["code"] == "MANIFEST_NOT_BOUND_TO_ACTUAL_RECOVERY_ENTRY"


def test_checker_uses_one_bounded_read_and_same_bound_manifest_value(tmp_path, monkeypatch):
    checker = checker_module()
    entry = tmp_path / "actual-entry"
    entry.mkdir()
    manifest = tmp_path / "manifest.json"
    value = {"runtime_root": str(entry), "approved_runtime_root": str(entry), "candidate_id": "TEST_ONLY first read"}
    manifest.write_text(json.dumps(value), encoding="ascii")
    original_open = Path.open
    reads = []
    def only_one_open(path, *args, **kwargs):
        if path == manifest and args and args[0] == "rb":
            reads.append(path)
            assert len(reads) == 1
        return original_open(path, *args, **kwargs)
    observed = []
    def evaluation(payload, *, roots):
        observed.append(payload)
        return {"can_launch": False, "database_opens": 0}
    monkeypatch.setattr(Path, "open", only_one_open)
    monkeypatch.setattr(checker.module, "evaluate", evaluation)
    assert not checker.check_manifest(manifest, [tmp_path], entry)["can_launch"]
    assert len(reads) == 1 and observed == [value]


def test_local_entry_manifest_is_validated_with_explicit_root(tmp_path, monkeypatch):
    checker = checker_module()
    entry = tmp_path / "entry"
    entry.mkdir()
    manifest = entry / "manifest.json"
    manifest.write_text(json.dumps({"runtime_root": str(entry), "approved_runtime_root": str(entry)}), encoding="ascii")
    monkeypatch.setattr(checker.module, "evaluate", lambda *a, **k: {"can_launch": False, "database_opens": 0})
    assert checker.check_manifest(manifest, [tmp_path], entry)["database_opens"] == 0


def test_split_code_and_runtime_are_bound_before_evaluation(tmp_path, monkeypatch):
    checker = checker_module()
    entry, runtime = tmp_path / "code", tmp_path / "runtime"
    entry.mkdir()
    runtime.mkdir()
    value = {"code_root": str(entry), "runtime_root": str(runtime),
             "approved_runtime_root": str(runtime)}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(value), encoding="ascii")
    observed = []
    def evaluation(payload, *, roots):
        observed.append(payload)
        return {"can_launch": False, "database_opens": 0}
    monkeypatch.setattr(checker.module, "evaluate", evaluation)
    assert not checker.check_manifest(manifest, [tmp_path], entry, runtime)["can_launch"]
    assert observed == [value]
    value["code_root"] = str(tmp_path / "wrong-code")
    manifest.write_text(json.dumps(value), encoding="ascii")
    result = checker.check_manifest(manifest, [tmp_path], entry, runtime)
    assert result["errors"][0]["code"] == "MANIFEST_NOT_BOUND_TO_ACTUAL_RECOVERY_ENTRY"
    assert len(observed) == 1


def test_split_runtime_does_not_accept_unapproved_target(tmp_path, monkeypatch):
    checker = checker_module()
    entry, runtime = tmp_path / "code", tmp_path / "runtime"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"code_root": str(entry), "runtime_root": str(runtime),
        "approved_runtime_root": str(tmp_path / "other")}), encoding="ascii")
    monkeypatch.setattr(checker.module, "evaluate", lambda *a, **k: pytest.fail("unbound evaluator"))
    result = checker.check_manifest(manifest, [tmp_path], entry, runtime)
    assert not result["can_launch"] and result["database_opens"] == 0


def test_explicit_python_must_be_bound_in_manifest_and_dependencies(tmp_path, monkeypatch):
    checker = checker_module()
    entry, runtime, python = tmp_path / "code", tmp_path / "runtime", tmp_path / "env/Scripts/python.exe"
    value = {"code_root": str(entry), "runtime_root": str(runtime), "approved_runtime_root": str(runtime),
             "python_executable": str(python), "dependencies": {"active_paths": []}}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(value), encoding="ascii")
    calls = []
    monkeypatch.setattr(checker.module, "evaluate", lambda *a, **k: calls.append(a) or {"can_launch": False})
    result = checker.check_manifest(manifest, [tmp_path], entry, runtime, python)
    assert result["errors"][0]["code"] == "MANIFEST_PYTHON_BINDING_MISMATCH"
    assert not calls
    value["dependencies"]["active_paths"] = [str(python)]
    manifest.write_text(json.dumps(value), encoding="ascii")
    assert not checker.check_manifest(manifest, [tmp_path], entry, runtime, python)["can_launch"]
    assert len(calls) == 1


def test_actual_split_launcher_rejects_wrong_code_before_lifecycle(tmp_path):
    launcher = Path(__file__).parents[1] / "start_kquant_workspace.ps1"
    runtime = tmp_path / "runtime"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"code_root": str(tmp_path / "wrong"),
        "runtime_root": str(runtime), "approved_runtime_root": str(runtime)}), encoding="ascii")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher),
        "-RecoveryManifest", str(manifest), "-RuntimeRoot", str(runtime),
        "-PythonExecutable", sys.executable, "-RecoveryLocalRoot", str(tmp_path),
        "-OptionsFoundation", "-OneMinuteShadow", "-NoBrowser"],
        capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "SAFE_RECOVERY_PREFLIGHT_FAILED" in result.stderr
    assert "FoundationLifecycle" not in result.stderr
    assert not runtime.exists()


def test_ads_manifest_is_rejected_before_filesystem_io(tmp_path, monkeypatch):
    checker = checker_module()
    monkeypatch.setattr(Path, "lstat", lambda *a, **k: pytest.fail("ADS filesystem access"))
    with pytest.raises(ValueError, match="FORBIDDEN"):
        checker.check_manifest(Path(str(tmp_path / "manifest.json") + ":payload"), [tmp_path], tmp_path)
from contextlib import closing
