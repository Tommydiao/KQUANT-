"""Isolated input/recovery tests. No SDK, owner approval, or live signals."""
from copy import deepcopy
from datetime import timedelta
import json
import sqlite3
from contextlib import closing

import pytest

from test_options_opening_momentum import inputs
from test_r58_signal_recovery import proof, reference
from kquant import options_one_minute as common
from kquant import options_opening_momentum_journal as journal
from kquant import options_opening_trend_store as store
from kquant import options_price_facts as facts
from kquant import options_minute_decisions as decisions


def setup_job(tmp_path):
    args = inputs()
    path = tmp_path / "isolated.sqlite3"
    store.initialize(path)
    journal.initialize(path)
    key = "opening_momentum", "2026-10-02", "TEST", 1
    job = "TEST", args["opening"].date(), deepcopy(args["bars"]), "scope", args["reference"]
    return path, args, key, job


def test_completed_same_reference_new_minute_generation_is_admitted(tmp_path):
    path, args, key, job = setup_job(tmp_path)
    assert journal.ready(path, key, job, args["now"])
    lease = journal.begin(path, key, job, args["now"])
    assert journal.finish(path, lease)
    assert not journal.ready(path, key, job, args["now"])
    changed = deepcopy(job)
    changed[2][0]["close"] += .01
    assert journal.ready(path, key, changed, args["now"])
    newer = journal.begin(path, key, changed, args["now"])
    assert newer.generation == lease.generation + 1
    assert journal.finish(path, newer)


def test_batch_admission_and_completion_keep_independent_cas(tmp_path):
    path, args, key, job = setup_job(tmp_path)
    entries = []
    for name in ("ONE", "TWO"):
        ownkey = key[:2] + (name, 1)
        ownjob = (name, *job[1:])
        entries.append((ownkey, ownjob, args["now"], journal.input_fingerprint(ownjob)))
    assert journal.ready_many(path, entries) == [True, True]
    leases = journal.begin_many(path, entries)
    changed = deepcopy(entries[0][1])
    changed[2][0]["close"] += .01
    assert journal.ready(path, entries[0][0], changed, args["now"])
    assert journal.finish_many(path, [(leases[0], False, []), (leases[1], False, [])]) == [False, True]
    with closing(sqlite3.connect(path)) as db:
        assert dict(db.execute("SELECT symbol,state FROM two_hour_jobs")) == {"ONE": "READY", "TWO": "COMPLETED"}
    assert journal.begin_many(path, [entries[0]]) == [None]


def test_old_worker_cannot_commit_evidence_or_complete_new_ready(tmp_path):
    path, args, key, job = setup_job(tmp_path)
    lease = journal.begin(path, key, job, args["now"])
    changed = deepcopy(job)
    changed[2][0]["close"] += .01
    assert journal.ready(path, key, changed, args["now"])
    assert not journal.finish(path, lease, rows=[{"invalid": "must not be persisted"}])
    with closing(sqlite3.connect(path)) as db:
        state, raw = db.execute("SELECT state,payload_json FROM two_hour_jobs").fetchone()
        assert state == "READY" and json.loads(raw)["input_generation"] == 2
        assert db.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0] == 0
    assert key in journal.restore(path, args["now"])


def test_delivery_timestamp_alone_is_not_new_price_input(tmp_path):
    _, args, _, job = setup_job(tmp_path)
    copy = deepcopy(job)
    copy[2][0]["received_at"] = args["now"].isoformat()
    assert journal.input_fingerprint(job) == journal.input_fingerprint(copy)
    copy[2][0]["received_at"] = (args["opening"] - timedelta(seconds=1)).isoformat()
    assert journal.input_fingerprint(job) != journal.input_fingerprint(copy)


def test_wait_input_and_deadline_do_not_move_to_a_later_checkpoint(tmp_path):
    path, args, key, job = setup_job(tmp_path)
    lease = journal.begin(path, key, job, args["now"])
    assert journal.finish(path, lease, waiting=True)
    changed = deepcopy(job)
    changed[4]["previous_close"] += .01
    late = args["opening"] + timedelta(minutes=10)
    assert not journal.ready(path, key, changed, late)
    assert journal.begin(path, key, changed, late) is None
    assert journal.restore(path, late) == {}


def fact_inputs(tmp_path, monkeypatch):
    args, quote, reviews = reference(tmp_path, monkeypatch)
    quote["currency_evidence"]["provider_symbol"] = "TEST.US"
    quote["currency_evidence"]["source_hash"] = common.digest(
        {k: v for k, v in quote["currency_evidence"].items() if k != "source_hash"})
    for name, assertion in (("previous_close_interface", "MAIN_QUOTE_PREVIOUS_CLOSE"),
                            ("price_binding_method", "QUOTE_AND_NO_ADJUST_PRICE_BASIS")):
        claim = dict(field_path="secu_quote.prev_close", assertion=assertion)
        reviews[name] = proof(tmp_path, args["now"], contract_version="INTERFACE_FACT_V1",
            claim=claim, claim_hash=common.digest(claim), price_basis="NoAdjust")
    raw = "TEST_ONLY isolated source fact, not a production proof; prev_close 昨收价".encode("utf-8")
    (tmp_path / "test-fact.txt").write_bytes(raw)
    from hashlib import sha256
    for value in (reviews["previous_close_interface"], reviews["price_binding_method"]):
        value["source_sha256"] = sha256(raw).hexdigest()
    reviews["previous_close_interface"]["excerpt"] = "prev_close 昨收价"
    reviews["instrument_price_actions"] = {"TEST": proof(tmp_path, args["now"], underlying="TEST",
        price_scale_state="UNCHANGED", complete=True, coverage_from_session="2026-10-01", coverage_through_session="2026-10-05")}
    # proof() rewrites the shared test file; restore the exact synthetic source.
    (tmp_path / "test-fact.txt").write_bytes(raw)
    reviews["instrument_price_actions"]["TEST"]["source_sha256"] = sha256(raw).hexdigest()
    return args, quote, reviews


def test_three_layer_binding_automatically_rebinds_day_and_keeps_original(tmp_path, monkeypatch):
    args, quote, reviews = fact_inputs(tmp_path, monkeypatch)
    path = tmp_path / "facts.sqlite3"
    journal.initialize(path)
    value = facts.persist_binding(path, facts.bind(quote, symbol="TEST", session="2026-10-02",
        now=args["now"], reviews=reviews, root=tmp_path))
    assert facts.valid(value, symbol="TEST", session="2026-10-02", now=args["now"], root=tmp_path)
    assert not facts.valid(value, symbol="OTHER", session="2026-10-02", now=args["now"], root=tmp_path)
    next_day = facts.persist_binding(path, facts.bind(quote, symbol="TEST", session="2026-10-05",
        now=args["now"], reviews=reviews, root=tmp_path))
    assert "PREPARED_PENDING_CURRENT_SESSION" in next_day["reasons"]
    assert next_day["reference_session"] == "2026-10-02"
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT COUNT(*) FROM two_hour_jobs WHERE slot=?", (facts.BINDING,)).fetchone()[0] == 2


def test_verified_v3_binding_reaches_actual_price_model_without_root_argument(tmp_path, monkeypatch):
    from kquant import options_price_reference as price_reference
    from kquant import options_opening_momentum as model
    args, quote, reviews = fact_inputs(tmp_path, monkeypatch)
    path = tmp_path / "facts.sqlite3"
    journal.initialize(path)
    quote["session_price_binding"] = facts.persist_binding(path, facts.bind(quote,
        symbol="TEST", session="2026-10-02", now=args["now"], reviews=reviews, root=tmp_path))
    assert quote["session_price_binding"]["status"] == "VERIFIED"
    monkeypatch.setattr(price_reference, "ROOT", tmp_path)
    built = price_reference.build(quote, symbol="TEST", session="2026-10-02",
        now=args["now"], reviews=reviews, root=tmp_path)
    assert price_reference.valid(built, symbol="TEST", session="2026-10-02", now=args["now"])
    args["reference"] = built
    assert model.evaluate(**args)["state"] == "NUMERIC_PASS"


@pytest.mark.parametrize("change", ["field_only", "split", "currency", "business_day", "wrong_asset"])
def test_binding_does_not_convert_config_flags_into_facts(tmp_path, monkeypatch, change):
    args, quote, reviews = fact_inputs(tmp_path, monkeypatch)
    if change == "field_only": reviews["previous_close_interface"].pop("claim")
    if change == "split": reviews["instrument_price_actions"]["TEST"]["price_scale_state"] = "UNKNOWN"
    if change == "currency": quote["currency"] = "HKD"
    if change == "business_day": quote["quote_time"] = "2026-10-01T19:59:00+00:00"
    if change == "wrong_asset": reviews["instrument_price_actions"]["TEST"]["underlying"] = "OTHER"
    value = facts.bind(quote, symbol="TEST", session="2026-10-02", now=args["now"], reviews=reviews, root=tmp_path)
    assert value["status"] == "PREPARED_WITH_GAPS" and value["reasons"]


def test_documented_revision_accepts_proved_old_replay_not_unknown_late_data(tmp_path, monkeypatch):
    path, args, _, _ = setup_job(tmp_path)
    monkeypatch.setattr(decisions, "ROOT", tmp_path)
    first = deepcopy(args["bars"][0])
    first["sdk_evidence"] = {"fields": {"revision": {"value": "1"}}}
    corrected = deepcopy(first)
    corrected["close"] += .01
    corrected["sdk_evidence"]["fields"]["revision"]["value"] = "2"
    corrected["received_at"] = args["now"].isoformat()
    method = proof(tmp_path, args["now"], interface="US_EQUITY_CANDLESTICK_1M",
                   semantics="DOCUMENTED_PROVIDER_REVISION", revision_field="revision")
    resolved = decisions.resolve(path, [first, corrected], symbol="TEST", session="2026-10-02",
        now=args["now"], proof=method, root=tmp_path)
    assert len(resolved) == 1 and resolved[0]["provider_permanently_final"] is False
    replay = {**first, "received_at": (args["now"] + timedelta(seconds=1)).isoformat()}
    assert decisions.accepted(resolved[0], [first, corrected, replay], symbol="TEST",
        start=common.timestamp(first["open_at"]), now=args["now"] + timedelta(seconds=2), root=tmp_path) == corrected
    replay["sdk_evidence"] = {}
    assert decisions.accepted(resolved[0], [first, corrected, replay], symbol="TEST",
        start=common.timestamp(first["open_at"]), now=args["now"] + timedelta(seconds=2), root=tmp_path) is None


def test_confirmed_does_not_authorize_arbitrary_correction(tmp_path):
    path, args, _, job = setup_job(tmp_path)
    versions = [deepcopy(job[2][0]), deepcopy(job[2][0])]
    versions[1]["close"] += .01
    for value in versions: value["sdk_evidence"] = {"provider_confirmed": True}
    method = proof(tmp_path, args["now"], interface="US_EQUITY_CANDLESTICK_1M", semantics="PROVIDER_CONFIRMED_BAR")
    assert decisions.resolve(path, versions, symbol="TEST", session="2026-10-02", now=args["now"], proof=method, root=tmp_path) == []


def test_111_checkpoint_jobs_have_independent_generations(tmp_path):
    path, args, key, job = setup_job(tmp_path)
    for index in range(111):
        symbol = f"TEST_ONLY_{index}"
        ownkey = key[:2] + (symbol, 1)
        ownjob = symbol, job[1], job[2], "scope", job[4]
        assert journal.ready(path, ownkey, ownjob, args["now"])
    restored = journal.restore(path, args["now"])
    assert len(restored) == 111
    for ownkey, ownjob in restored.items():
        lease = journal.begin(path, ownkey, ownjob, args["now"])
        assert journal.finish(path, lease, waiting=True)
    assert len(journal.restore(path, args["now"])) == 111


def test_input_change_withdraws_old_setup_without_overwriting_original(tmp_path):
    from kquant import options_opening_momentum as model
    path, args, _, _ = setup_job(tmp_path)
    original = model.evaluate(**args)
    original["runtime_inputs"] = {"input_fingerprint": "first"}
    original["computed_at"] = args["now"].isoformat()
    store.persist([original], path)
    changed = {**original, "evaluation_id": "revised-input", "state": "NO_TRIGGER",
        "computed_at": (args["now"] + timedelta(seconds=1)).isoformat(),
        "runtime_inputs": {"input_fingerprint": "second"}}
    store.persist([changed], path)
    saved = store.detail(original["evaluation_id"], path)
    assert saved["state"] == "NUMERIC_PASS"
    assert saved["current_eligibility"]["state"] == "WITHDRAWN"
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT state FROM qualification_jobs").fetchone()[0] == "WITHDRAWN"


def test_reference_callback_between_compute_and_wait_registration_is_not_lost(tmp_path, monkeypatch):
    from threading import Event
    from kquant import options_opening_trend_runtime as runtime
    from kquant import options_price_reference as prices
    from kquant import options_opening_momentum as model
    from kquant import options_opening_trend_reference as refs
    path, args, key, job = setup_job(tmp_path)
    minute = tmp_path / "minutes.sqlite3"
    common.initialize(minute)
    for bar in job[2]: common.save_bar(bar, key[1], minute)
    done, changed = Event(), Event()
    class History:
        def __init__(self, *a, **kw): pass
        def get(self, *a): return {}, {"state": "READY"}
        def snapshot(self): return {}
        def request(self, *a, **kw): pass
        def close(self): pass
    class Hub:
        def publish(self, value): done.set()
    monkeypatch.setattr(runtime, "HistoryCache", History)
    monkeypatch.setattr(refs, "load_reviews", lambda: {})
    monkeypatch.setattr(prices, "build", lambda *a, **kw: args["reference"])
    evaluate = model.evaluate
    lane = runtime.TrendLane(minute, Hub(), path=path, clock=lambda: args["now"])
    def during_compute(**kwargs):
        value = evaluate(**kwargs)
        if not changed.is_set():
            changed.set()
            lane.reference_ready("TEST", job[1], {"source_revision": "new"})
            value["state"] = "INCOMPLETE"
        return value
    monkeypatch.setattr(model, "evaluate", during_compute)
    try:
        lane.enqueue(*job)
        assert done.wait(3)
        from time import monotonic, sleep
        limit = monotonic() + 3
        while monotonic() < limit:
            with closing(sqlite3.connect(path)) as db:
                row = db.execute("SELECT state,payload_json FROM two_hour_jobs WHERE slot='1' AND symbol='TEST'").fetchone()
            if row and row[0] == "COMPLETED" and json.loads(row[1]).get("input_generation", 0) >= 2:
                break
            sleep(.01)
        else:
            pytest.fail(str(lane.state))
        assert row[0] == "COMPLETED"
    finally:
        lane.close()


def test_exact_runtime_frontend_bundle_acceptance_and_changed_build(tmp_path):
    from hashlib import sha256
    from kquant.options_release_acceptance import verify
    front = tmp_path / "index.html"
    front.write_text("TEST_ONLY_BUILD")
    front_hashes = {"index.html": sha256(front.read_bytes()).hexdigest()}
    directory = tmp_path / "test-runtime"
    directory.mkdir()
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps({"frontend": ".", "frontend_files": front_hashes, "source_contract_policy_hash": "test-contract"}))
    runtime_hash = sha256(manifest.read_bytes()).hexdigest()
    bundle = dict(runtime_manifest_sha256=runtime_hash, source_contract_policy_hash="test-contract")
    bundle["bundle_sha256"] = common.digest(bundle)
    (tmp_path / "bundle.json").write_text(json.dumps(bundle))
    record = dict(status="APPROVED", approved_by="OWNER", test_only=True,
        runtime_manifest_sha256=runtime_hash, frontend_files_hash=common.digest(front_hashes),
        bundle_path="bundle.json", bundle_sha256=bundle["bundle_sha256"], source_contract_policy_hash="test-contract")
    env = dict(KQUANT_RUNTIME_MANIFEST=str(manifest), KQUANT_BACKEND_MANIFEST_SHA256=runtime_hash,
               KQUANT_BACKEND_RELEASE_ID=directory.name, KQUANT_GATEWAY_WEB_DIST=str(tmp_path))
    assert verify(record, root=tmp_path, environment=env)["status"] == "PASS"
    assert verify(record, root=tmp_path, environment={**env, "KQUANT_GATEWAY_WEB_DIST": str(directory)})["reason"] == "ACTUAL_SERVED_FRONTEND_NOT_ACCEPTED"
    front.write_text("DIFFERENT_BUILD")
    assert verify(record, root=tmp_path, environment=env)["status"] == "BLOCKED"
    assert verify(None, root=tmp_path, environment=env)["status"] == "BLOCKED"


def test_bad_symbol_input_does_not_block_other_checkpoint_admissions(tmp_path, monkeypatch):
    from threading import Event
    from kquant import options_opening_trend_runtime as runtime
    from kquant import options_price_reference as prices
    from kquant import options_opening_trend_reference as refs
    path, args, key, job = setup_job(tmp_path)
    minute = tmp_path / "minutes.sqlite3"
    common.initialize(minute)
    for bar in job[2]:
        common.save_bar(bar, key[1], minute)
    done = Event()
    class History:
        def __init__(self, *a, **kw): pass
        def get(self, *a): return {}, {"state": "READY"}
        def snapshot(self): return {}
        def request(self, *a, **kw): pass
        def close(self): pass
    class Hub:
        def publish(self, value):
            if value.get("symbol") == "TEST": done.set()
    original = runtime.TrendLane._checkpoint_inputs
    def inputs(lane, candidate_key, candidate_job, *a, **kw):
        if candidate_job[0] == "TEST_ONLY_BAD":
            raise ValueError("MINUTE_VERSION_READ_BOUND_EXCEEDED")
        return original(lane, candidate_key, candidate_job, *a, **kw)
    monkeypatch.setattr(runtime, "HistoryCache", History)
    monkeypatch.setattr(runtime.TrendLane, "_checkpoint_inputs", inputs)
    monkeypatch.setattr(refs, "load_reviews", lambda: {})
    monkeypatch.setattr(prices, "build", lambda *a, **kw: args["reference"])
    lane = runtime.TrendLane(minute, Hub(), path=path, clock=lambda: args["now"])
    try:
        lane.enqueue("TEST_ONLY_BAD", *job[1:])
        lane.enqueue(*job)
        assert done.wait(3), lane.state
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT state FROM two_hour_jobs WHERE symbol='TEST' AND slot='1'").fetchone()[0] == "COMPLETED"
        assert lane.state["journal_error"] == "ValueError"
    finally:
        lane.close()


def test_failed_admission_has_original_deadline_and_explicit_archive(tmp_path):
    path, args, key, job = setup_job(tmp_path)
    journal.record_missed(path, key, job, args["opening"] + timedelta(minutes=11),
                          reason="INPUT_ADMISSION_FAILED")
    with closing(sqlite3.connect(path)) as db:
        row = db.execute("SELECT state,deadline_at,reason FROM two_hour_jobs").fetchone()
    assert row == ("EXPIRED", (args["opening"] + timedelta(minutes=10)).isoformat(), "INPUT_ADMISSION_FAILED")


def test_reference_api_metadata_is_opt_in_and_preserves_field_times(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from kquant.config import KquantConfig
    from kquant.dashboard import app as dashboard
    from kquant.options_opening_trend_pipeline import Services
    calls = []
    snapshot = dict(contract_symbol="TEST_ONLY_C", bbo_received_at="2026-10-02T13:35:01+00:00")
    monkeypatch.setattr(dashboard, "option_contract_snapshot", lambda *a: dict(snapshot))
    def contract(service, identity, **kw):
        calls.append(identity)
        return {"snapshot": {**snapshot, "currency": "USD",
            "currency_evidence": {"source": "TEST_ONLY_STATIC_RESPONSE"}}}
    monkeypatch.setattr(Services, "contract", contract)
    client = TestClient(dashboard.create_app(config=KquantConfig(
        db_path=tmp_path / "isolated.sqlite3", outputs_dir=tmp_path / "outputs")))
    plain = client.get("/api/options/contracts/TEST_ONLY_C").json()
    assert "currency" not in plain and calls == []
    rich = client.get("/api/options/contracts/TEST_ONLY_C?include_metadata=true").json()
    assert rich["currency"] == "USD" and calls == ["TEST_ONLY_C"]
    assert rich["bbo_received_at"] == snapshot["bbo_received_at"]
