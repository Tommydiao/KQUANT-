"""Unchanged checkpoint wakeups cannot compete for the SQLite writer."""
from contextlib import closing, contextmanager
from copy import deepcopy
from datetime import timedelta
import json
import sqlite3

import pytest

from kquant import options_opening_momentum_journal as journal
from test_r58_p7_inputs import setup_job


def current_row(path, symbol="TEST"):
    with closing(sqlite3.connect(path)) as db:
        row = db.execute("SELECT state,deadline_at,payload_json FROM two_hour_jobs WHERE symbol=?", (symbol,)).fetchone()
    return row[:2], json.loads(row[2])


@pytest.mark.parametrize("state", ["READY", "LEASED", "COMPLETED", "WAIT_INPUT", "EXPIRED"])
def test_duplicate_fingerprint_uses_readonly_even_with_another_writer(tmp_path, state):
    path, args, key, job = setup_job(tmp_path)
    assert journal.ready(path, key, job, args["now"])
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE two_hour_jobs SET state=?", (state,))
    before = current_row(path)
    with closing(sqlite3.connect(path, timeout=.05)) as writer:
        writer.execute("BEGIN IMMEDIATE")
        assert journal.ready_many(path, [(key, job, args["now"], None)]) == [False]
        writer.rollback()
    assert current_row(path) == before


def test_mixed_duplicate_and_changed_inputs_preserve_order_generation_and_deadline(tmp_path):
    path, args, key, job = setup_job(tmp_path)
    assert journal.ready(path, key, job, args["now"])
    lease = journal.begin(path, key, job, args["now"])
    assert journal.finish(path, lease)
    changed = deepcopy(job)
    changed[2][0]["close"] += .01
    other_key, other_job = (*key[:2], "OTHER", 1), ("OTHER", *job[1:])
    assert journal.ready_many(path, [(key, job, args["now"], None),
        (other_key, other_job, args["now"], None), (key, changed, args["now"], None)]) == [False, True, True]
    row, payload = current_row(path)
    assert row == ("READY", (args["opening"] + timedelta(minutes=10)).isoformat())
    assert payload["input_generation"] == lease.generation + 1
    assert not journal.finish(path, lease)


def test_expiry_after_readonly_check_is_rechecked_before_admission(tmp_path, monkeypatch):
    path, args, key, job = setup_job(tmp_path)
    assert journal.ready(path, key, job, args["now"])
    changed = deepcopy(job)
    changed[2][0]["close"] += .01
    original = journal.read_connection

    @contextmanager
    def concurrent_expiry(*arguments, **keywords):
        with original(*arguments, **keywords) as db:
            yield db
        with closing(sqlite3.connect(path)) as writer, writer:
            writer.execute("UPDATE two_hour_jobs SET state='EXPIRED'")

    monkeypatch.setattr(journal, "read_connection", concurrent_expiry)
    assert not journal.ready(path, key, changed, args["now"])
    row, payload = current_row(path)
    assert row[0] == "EXPIRED"
    assert payload["input_generation"] == 1


def test_unchanged_input_at_original_deadline_is_archived_not_skipped(tmp_path):
    path, args, key, job = setup_job(tmp_path)
    assert journal.ready(path, key, job, args["now"])
    deadline = args["opening"] + timedelta(minutes=10)
    assert not journal.ready(path, key, job, deadline)
    row, payload = current_row(path)
    assert row == ("EXPIRED", deadline.isoformat())
    assert payload["input_generation"] == 1
    assert journal.begin(path, key, job, deadline) is None


def test_empty_or_oversized_admission_does_not_open_database(tmp_path):
    path, args, key, job = setup_job(tmp_path)
    missing = tmp_path / "NEVER-CREATED.sqlite3"
    assert journal.ready_many(missing, []) == []
    with pytest.raises(ValueError, match="CHECKPOINT_ADMISSION_BATCH_BOUND_EXCEEDED"):
        journal.ready_many(missing, [(key, job, args["now"], None)] * 65)
    assert not missing.exists()
