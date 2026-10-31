"""TEST_ONLY exact release acceptance plus actual contract pipeline functions.

Fixtures are synthetic and outside the production config. No OWNER acceptance,
broker, SDK context, production database or real-market claim is created.
"""
from datetime import timedelta
from hashlib import sha256
import json

from test_r58_positive_chain import prepare
from kquant import options_one_minute as common
from kquant import options_opening_momentum as model
from kquant import options_opening_trend_store as store
from kquant import options_opening_trend_approval as approvals
from kquant import options_release_acceptance as release
from kquant.options_opening_trend_pipeline import step


def test_exact_release_binds_positive_contract_and_changed_build_blocks(tmp_path, monkeypatch):
    args, original, services, strategy_path = prepare(tmp_path, monkeypatch)
    frontend = tmp_path / "TEST_ONLY-build.html"
    frontend.write_text("TEST_ONLY_not_a_production_build", encoding="utf-8")
    front_hashes = {frontend.name: sha256(frontend.read_bytes()).hexdigest()}
    directory = tmp_path / "TEST_ONLY-runtime"
    directory.mkdir()
    source_hash = common.digest({"test_only": True, "contract": "ISOLATED_ACCEPTANCE_ONLY"})
    runtime = {"test_only": True, "frontend": ".", "frontend_files": front_hashes,
               "source_contract_policy_hash": source_hash}
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps(runtime), encoding="utf-8")
    runtime_hash = sha256(manifest.read_bytes()).hexdigest()
    bundle = {"test_only": True, "runtime_manifest_sha256": runtime_hash,
              "source_contract_policy_hash": source_hash}
    bundle["bundle_sha256"] = common.digest(bundle)
    (tmp_path / "TEST_ONLY-bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
    record = {"test_only": True, "status": "APPROVED", "approved_by": "OWNER",
              "runtime_manifest_sha256": runtime_hash,
              "frontend_files_hash": common.digest(front_hashes),
              "bundle_path": "TEST_ONLY-bundle.json", "bundle_sha256": bundle["bundle_sha256"],
              "source_contract_policy_hash": source_hash}
    environment = {"KQUANT_RUNTIME_MANIFEST": str(manifest),
                   "KQUANT_BACKEND_MANIFEST_SHA256": runtime_hash,
                   "KQUANT_BACKEND_RELEASE_ID": directory.name,
                   "KQUANT_GATEWAY_WEB_DIST": str(tmp_path)}
    verify = release.verify
    monkeypatch.setattr(release, "verify", lambda value: verify(value, root=tmp_path, environment=environment))
    strategy = json.loads(strategy_path.read_bytes())
    strategy["release_acceptance"] = record
    strategy_path.write_text(json.dumps(strategy), encoding="utf-8")
    accepted = approvals.status(model.load_policy(), "scope")
    assert accepted["qualified_signal_pipeline_enabled"]
    assert accepted["release_acceptance"]["status"] == "PASS"

    path = tmp_path / "TEST_ONLY-positive.sqlite3"
    store.initialize(path)
    store.persist([original], path)
    job = {"evaluation": original, "progress": {}}
    for _ in range(6):
        progress, _, revision = step(job, services, clock=lambda: args["now"])
        job["progress"] = progress
    assert revision["state"] == "QUALIFIED"
    saved = store.append_revision(original["evaluation_id"], revision, path)
    current = store.current_cards(path=path, session=original["session"], scope_hash="scope",
                                  now=args["now"], policy=model.load_policy())
    assert current["candidates"][0]["contract_id"] == "TEST261006C105000.US"
    assert saved["deadline_at"] == original["deadline_at"]
    assert revision["valid_until"] == (args["now"] + timedelta(seconds=3)).isoformat()
    assert store.current_cards(path=path, session=original["session"], scope_hash="scope",
                               now=args["now"] + timedelta(seconds=3), policy=model.load_policy())["candidates"] == []
    assert not model.load_policy()["qualified_publication_enabled"]

    frontend.write_text("TEST_ONLY_changed_build", encoding="utf-8")
    changed = approvals.status(model.load_policy(), "scope")
    assert not changed["qualified_signal_pipeline_enabled"]
    assert changed["release_acceptance"]["reason"] == "FRONTEND_ARTIFACT_CHANGED"
    environment["KQUANT_BACKEND_MANIFEST_SHA256"] = "0" * 64
    assert verify(record, root=tmp_path, environment=environment)["reason"] == "RUNTIME_ACCEPTANCE_CHANGED"
    assert verify(None, root=tmp_path, environment=environment)["status"] == "BLOCKED"
