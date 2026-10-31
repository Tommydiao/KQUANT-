"""Policy identity is consistent within a batch and never read under a writer."""
from contextlib import closing
import json
import sqlite3

import pytest

from kquant import options_one_minute as common
from kquant import options_opening_momentum_journal as journal
from test_r58_p7_inputs import setup_job


def entries_for(args, key, job):
    return [(key[:2] + (name, 1), (name, *job[1:]), args["now"],
             journal.input_fingerprint((name, *job[1:])))
            for name in ("ONE", "TWO", "THREE")]


def test_admission_uses_one_policy_identity_for_ids_and_payloads(tmp_path, monkeypatch):
    path, args, key, job = setup_job(tmp_path)
    calls = []

    def changing_policy():
        calls.append(len(calls) + 1)
        return {"policy_hash": f"snapshot-{calls[-1]}"}

    monkeypatch.setattr(journal, "load_policy", changing_policy)
    entries = entries_for(args, key, job)
    assert journal.ready_many(path, entries) == [True] * 3
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute("SELECT job_id,payload_json FROM two_hour_jobs").fetchall()
    for job_id, raw in rows:
        payload = json.loads(raw)
        ownkey = (*key[:2], payload["symbol"], 1)
        assert job_id == common.digest([journal.KIND, ownkey, "scope", payload["policy_hash"]])
        assert payload["policy_hash"] == "snapshot-1"
    assert len(calls) == 1
    assert journal.ready_many(path, entries) == [True] * 3
    assert len(calls) == 2
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT COUNT(*) FROM two_hour_jobs").fetchone()[0] == 6


@pytest.mark.parametrize("operation", ["ready_many", "begin_many", "restore"])
def test_policy_read_is_once_and_outside_any_sqlite_transaction(tmp_path, monkeypatch, operation):
    path, args, key, job = setup_job(tmp_path)
    entries = entries_for(args, key, job)
    policy = journal.load_policy()
    if operation != "ready_many":
        assert journal.ready_many(path, entries) == [True] * 3
    connections, calls = [], []
    original = sqlite3.connect

    def connect(*arguments, **keywords):
        db = original(*arguments, **keywords)
        connections.append(db)
        return db

    def policy_read():
        for db in connections:
            try:
                assert not db.in_transaction, "POLICY_IO_INSIDE_SQLITE_TRANSACTION"
            except sqlite3.ProgrammingError:
                pass
        calls.append(True)
        return policy

    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(journal, "load_policy", policy_read)
    if operation == "restore":
        result = journal.restore(path, args["now"])
    else:
        result = getattr(journal, operation)(path, entries)
    assert len(result) == 3
    assert len(calls) == 1


def test_empty_or_oversized_compute_batch_has_no_policy_or_database_io(tmp_path, monkeypatch):
    path = tmp_path / "not-created.sqlite3"

    def unexpected(*args, **kwargs):
        raise AssertionError("EMPTY_OR_OVERSIZED_BATCH_IO")

    monkeypatch.setattr(journal, "load_policy", unexpected)
    monkeypatch.setattr(sqlite3, "connect", unexpected)
    assert journal.begin_many(path, []) == []
    with pytest.raises(ValueError, match="CHECKPOINT_COMPUTE_BATCH_BOUND_EXCEEDED"):
        journal.begin_many(path, [None] * 65)
    assert not path.exists()
