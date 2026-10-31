from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from kquant.options_data_paths import resolve_stores
from kquant.recovery_preflight import ROLES, candidate_hash, evaluate
from test_new_epoch_runtime import epoch_candidate


def all_store_binding(tmp_path):
    manifest = epoch_candidate(tmp_path)
    ref = manifest["runtime_path_binding"]
    path = Path(ref["path"])
    binding = json.loads(path.read_text())
    binding["stores"] = {r["role"]: r["path"] for r in manifest["databases"]}
    path.write_text(json.dumps(binding), encoding="ascii")
    ref["sha256"] = sha256(path.read_bytes()).hexdigest()
    final_ref = manifest["acceptance_receipt"]
    final_path = Path(final_ref["path"])
    decision = json.loads(final_path.read_text())
    decision["candidate_payload_sha256"] = candidate_hash(manifest)
    final_path.write_text(json.dumps(decision), encoding="ascii")
    final_ref["sha256"] = sha256(final_path.read_bytes()).hexdigest()
    return manifest, binding


def test_exact_five_store_binding_passes_actual_gate_and_maps_all_roles(tmp_path, monkeypatch):
    manifest, binding = all_store_binding(tmp_path)
    result = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    assert result["can_launch"], result
    assert result["database_opens"] == 5
    ref = result["runtime_path_binding"]
    monkeypatch.setenv("KQUANT_RUNTIME_PATH_BINDING", ref["path"])
    monkeypatch.setenv("KQUANT_RUNTIME_PATH_BINDING_SHA256", ref["sha256"])
    assert resolve_stores(Path(manifest["runtime_root"])) == {r: Path(p) for r, p in binding["stores"].items()}


@pytest.mark.parametrize("change", ["missing_role", "extra_role", "wrong_minute", "shared_file", "foreign_root"])
def test_all_role_binding_rejects_bad_mapping_before_opening_database(tmp_path, monkeypatch, change):
    manifest, binding = all_store_binding(tmp_path)
    stores = binding["stores"]
    if change == "missing_role":
        stores.pop("main")
    elif change == "extra_role":
        stores["extra"] = stores["main"]
    elif change == "wrong_minute":
        stores["minute"] = stores["opening_research"]
    elif change == "shared_file":
        stores["main"] = stores["full_watch"]
    elif change == "foreign_root":
        stores["main"] = str(tmp_path / "outside.sqlite3")
    ref = manifest["runtime_path_binding"]
    Path(ref["path"]).write_text(json.dumps(binding), encoding="ascii")
    ref["sha256"] = sha256(Path(ref["path"]).read_bytes()).hexdigest()
    monkeypatch.setenv("KQUANT_RUNTIME_PATH_BINDING", ref["path"])
    monkeypatch.setenv("KQUANT_RUNTIME_PATH_BINDING_SHA256", ref["sha256"])
    with pytest.raises(ValueError):
        resolve_stores(Path(manifest["runtime_root"]))
    result = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    assert not result["can_launch"] and result["database_opens"] == 0


def test_actual_imports_and_configuration_use_exact_main_full_watch_copilot_paths(tmp_path):
    manifest, binding = all_store_binding(tmp_path)
    ref = manifest["runtime_path_binding"]
    code = """
import json,os,sys
from pathlib import Path
os.environ['KQUANT_RUNTIME_PATH_BINDING']=sys.argv[1]
os.environ['KQUANT_RUNTIME_PATH_BINDING_SHA256']=sys.argv[2]
os.environ['KQUANT_RUNTIME_DATA_ROOT']=sys.argv[3]
from kquant import options_full_watch as full, options_signal_copilot as copilot
from kquant.config import load_config
print(json.dumps({'main':str(load_config('TEST_ONLY-missing-config.yml').db_path),
                 'copilot_main':str(copilot.MAIN_STORE_PATH),
                 'full_watch':str(full.DEFAULT_STORE_PATH),'signal_copilot':str(copilot.DEFAULT_STORE_PATH)}))
"""
    result = subprocess.run([sys.executable, "-c", code, ref["path"], ref["sha256"], manifest["runtime_root"]],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed == {"main": binding["stores"]["main"], "copilot_main": binding["stores"]["main"],
                        "full_watch": binding["stores"]["full_watch"],
                        "signal_copilot": binding["stores"]["signal_copilot"]}


def test_split_runtime_override_requires_exact_map(tmp_path, monkeypatch):
    monkeypatch.setenv("KQUANT_RUNTIME_DATA_ROOT", str(tmp_path / "runtime"))
    monkeypatch.delenv("KQUANT_RUNTIME_PATH_BINDING", raising=False)
    monkeypatch.delenv("KQUANT_RUNTIME_PATH_BINDING_SHA256", raising=False)
    with pytest.raises(ValueError, match="EXACT_RUNTIME_PATH_BINDING_REQUIRED"):
        resolve_stores(tmp_path / "code")


def test_split_runtime_wrong_root_cannot_use_valid_map(tmp_path, monkeypatch):
    manifest, binding = all_store_binding(tmp_path)
    ref = manifest["runtime_path_binding"]
    monkeypatch.setenv("KQUANT_RUNTIME_PATH_BINDING", ref["path"])
    monkeypatch.setenv("KQUANT_RUNTIME_PATH_BINDING_SHA256", ref["sha256"])
    monkeypatch.setenv("KQUANT_RUNTIME_DATA_ROOT", str(tmp_path / "different-runtime"))
    with pytest.raises(ValueError):
        resolve_stores(tmp_path / "code")


@pytest.mark.parametrize("component", ["full_init", "full_write", "copilot_init", "copilot_write",
                                        "main_migrations", "main_write"])
def test_all_retained_write_factories_refuse_missing_bound_store(tmp_path, monkeypatch, component):
    from kquant import options_full_watch, options_signal_copilot, stock_store
    from kquant.db.migrations import apply_sqlite_migrations

    writers = {"full_init": options_full_watch.initialize_full_watch_store,
               "full_write": options_full_watch._connect,
               "copilot_init": options_signal_copilot.initialize_copilot_store,
               "copilot_write": options_signal_copilot._connect,
               "main_migrations": apply_sqlite_migrations,
               "main_write": stock_store.connect}
    missing = tmp_path / "TEST_ONLY-missing.sqlite3"
    monkeypatch.setenv("KQUANT_RUNTIME_PATH_BINDING", "TEST_ONLY")
    import sqlite3
    with pytest.raises(sqlite3.OperationalError):
        writers[component](missing)
    assert not missing.exists()


def test_two_role_legacy_binding_remains_compatible_without_inventing_existing_stores(tmp_path, monkeypatch):
    manifest = epoch_candidate(tmp_path)
    ref = manifest["runtime_path_binding"]
    monkeypatch.setenv("KQUANT_RUNTIME_PATH_BINDING", ref["path"])
    monkeypatch.setenv("KQUANT_RUNTIME_PATH_BINDING_SHA256", ref["sha256"])
    root = Path(manifest["runtime_root"])
    paths = resolve_stores(root)
    assert set(paths) == ROLES
    assert paths["main"] == root / "work/kquant_us.sqlite3"
    assert not paths["main"].exists()
    assert evaluate(manifest, roots=[tmp_path], allow_test_only=True)["can_launch"]
