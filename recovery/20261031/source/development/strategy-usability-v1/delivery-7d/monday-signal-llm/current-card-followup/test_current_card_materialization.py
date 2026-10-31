"""Isolated actual store reads, including a concurrent withdrawal between phases."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parents[1]
BASE = HERE.parents[4] / "source/development/workspace"
sys.path.insert(0, str(BASE))
from kquant import options_one_minute as common
from kquant import options_intraday_comparison as comparison
from kquant import options_opening_trend_store as original
from kquant import bounded_sqlite
from kquant.options_opening_momentum import load_policy

spec = importlib.util.spec_from_file_location("kquant._test_card_materialization",
    HERE / "current-card-followup/patches/kquant/options_opening_trend_store.py")
followup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = followup
spec.loader.exec_module(followup)


@pytest.fixture
def saved(tmp_path, monkeypatch):
    monkeypatch.delenv("KQUANT_RUNTIME_PATH_BINDING", raising=False)
    monkeypatch.delenv("KQUANT_RUNTIME_PATH_BINDING_SHA256", raising=False)
    monkeypatch.delenv("KQUANT_RUNTIME_DATA_ROOT", raising=False)
    from kquant import options_research_ai_store
    monkeypatch.setattr(options_research_ai_store, "summaries", lambda *args, **kwargs: {})
    args = json.loads((HERE / "evidence/real-btdr-input.json").read_text(encoding="utf-8"))["arguments"]
    for key in ("opening", "closing", "now", "checkpoint"):
        args[key] = common.timestamp(args[key])
    rows = comparison.evaluate_comparison_pair(**args)
    path = tmp_path / "TEST_ONLY-research.sqlite3"
    original.initialize(path)
    from kquant.options_opening_momentum_journal import initialize
    initialize(path)
    original.persist(rows, path)
    query = dict(path=path, session="2026-10-15", scope_hash=args["scope_hash"],
        now=args["now"], policy=load_policy())
    return path, rows, query


def test_real_saved_input_retains_counts_and_original_deadline(saved):
    _, _, query = saved
    value = followup.current_cards(**query)
    assert value["evaluations_total"] == 1
    assert value["evaluations"][0]["strategy_comparison"]["s1"]["state"] == "NUMERIC_PASS"
    assert value["candidates"] == []
    assert value["current_projection"]["sql_returned_rows"] == 1
    assert followup.current_cards(**{**query, "now": query["now"]+timedelta(seconds=301)})["evaluations"] == []


def test_concurrent_withdrawal_is_next_generation_not_mixed_snapshot(saved, monkeypatch):
    path, rows, query = saved
    child = next(row["strategy_comparison"]["s1"] for row in rows
        if row["strategy_comparison"]["s1"]["state"] == "NUMERIC_PASS")
    original_read = bounded_sqlite.read_connection
    inserted = []

    class SelectionCursor:
        def __init__(self, cursor):
            self.cursor = cursor

        def fetchall(self):
            values = self.cursor.fetchall()
            if not inserted:
                inserted.append(original.append_revision(child["evaluation_id"],
                    dict(checked_at=(query["now"]+timedelta(seconds=1)).isoformat(),
                        state="WITHDRAWN", reasons=["TEST_ONLY_CONCURRENT_SOURCE_REVISION"]), path))
            return values

    class ObservedConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, *args):
            cursor = self.connection.execute(sql, *args)
            return SelectionCursor(cursor) if "SELECT e.rowid,e.symbol" in sql else cursor

    @contextmanager
    def observed_read(database, *, seconds=1.0):
        assert seconds == .3
        with original_read(database, seconds=seconds) as connection:
            yield ObservedConnection(connection)

    monkeypatch.setattr(bounded_sqlite, "read_connection", observed_read)
    first = followup.current_cards(**query)
    assert inserted
    assert first["current_projection"]["source_watermark"]["revision_id"] is None
    assert first["evaluations"][0]["strategy_comparison"]["reference_eligibility"] == {}
    second = followup.current_cards(**{**query, "now": query["now"]+timedelta(seconds=2)})
    assert second["current_projection"]["source_watermark"]["revision_id"] == inserted[0]["revision"]
    assert second["evaluations"][0]["strategy_comparison"]["reference_eligibility"]["state"] == "WITHDRAWN"
    assert second["candidates"] == []


def test_overflow_is_rejected_not_hidden_by_eight_card_limit(saved):
    path, rows, query = saved
    template = rows[0]
    copied = []
    for number in range(223):
        row = deepcopy(template)
        row["symbol"] = f"TEST_ONLY_{number:03d}"
        row["evaluation_id"] = f"TEST_ONLY_parent_{number}"
        row["event_id"] = f"TEST_ONLY_event_{number}"
        child = row["strategy_comparison"]["s1"]
        child.update(state="NUMERIC_PASS", evaluation_id=f"TEST_ONLY_child_{number}",
            event_id=f"TEST_ONLY_child_event_{number}")
        copied.append(row)
    original.persist(copied, path)
    with pytest.raises(ValueError, match="LIVE_CARD_BOUND_EXCEEDED"):
        followup.current_cards(**query)


def test_wrong_scope_keeps_watermark_and_no_cards(saved):
    _, _, query = saved
    value = followup.current_cards(**{**query, "scope_hash": "TEST_ONLY_DIFFERENT_SCOPE"})
    assert value["evaluations_total"] == 0
    assert value["evaluations"] == []
    assert value["candidates"] == []
    assert value["current_projection"]["source_watermark"]["evaluation_rowid"] > 0
