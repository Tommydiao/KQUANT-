import json
import sqlite3

import pytest

from kquant.options_one_minute import SCHEMA
from kquant.options_one_minute_manual import manual_status


def store(tmp_path, boundary=None):
    file = tmp_path / "one_minute.sqlite3"
    with sqlite3.connect(file) as db:
        db.executescript(SCHEMA)
        if boundary is not None:
            db.execute("CREATE TABLE data_epoch_boundary(id INTEGER PRIMARY KEY, payload_json TEXT)")
            db.execute("INSERT INTO data_epoch_boundary VALUES(1,?)", (json.dumps(boundary),))
    return file


def test_absent_store_is_unknown_not_zero_positions_and_not_created(tmp_path):
    file = tmp_path / "missing.sqlite3"
    result = manual_status(file)
    assert not file.exists()
    assert result["positions"] == []
    assert result["status"] == "UNAVAILABLE"
    assert result["old_position_continuity"] == "UNKNOWN"
    assert result["position_records_complete"] is False


def test_new_epoch_empty_tables_do_not_establish_no_prior_positions(tmp_path):
    boundary = {"schema": "KQUANT_NEW_MINUTE_EPOCH_V1", "epoch_id": "TEST_ONLY",
                "session": "2026-10-07", "record_kind": "NEW_DATA_NOT_OLD_RECOVERY",
                "old_position_continuity": "UNKNOWN", "complete_restoration_claimed": False,
                "unresolved_old_records": ["manual_position_revisions"]}
    file = store(tmp_path, boundary)
    before = file.read_bytes()
    result = manual_status(file)
    assert result["positions"] == [] and result["status"] == "CURRENT_EPOCH_ONLY"
    assert result["old_position_continuity"] == "UNKNOWN"
    assert result["data_epoch"]["epoch_id"] == "TEST_ONLY"
    assert not result["paper_enabled"] and not result["real_orders_enabled"]
    assert file.read_bytes() == before


@pytest.mark.parametrize("boundary", [{}, [], {"complete_restoration_claimed": True}])
def test_invalid_epoch_cannot_claim_complete_positions(tmp_path, boundary):
    result = manual_status(store(tmp_path, boundary))
    assert result["old_position_continuity"] == "UNKNOWN"
    assert result["continuity_reason"] == "EPOCH_BOUNDARY_INVALID"
    assert not result["position_records_complete"]


def test_legacy_store_remains_compatible_without_fabricating_continuity(tmp_path):
    result = manual_status(store(tmp_path))
    assert result["positions"] == result["alerts"] == []
    assert result["record_scope"] == "CURRENT_STORE_ONLY"
    assert "old_position_continuity" not in result


def test_epoch_namespace_requires_its_boundary(tmp_path):
    namespace = tmp_path / "options_one_minute-epoch-20261007"
    namespace.mkdir()
    result = manual_status(store(namespace))
    assert result["continuity_reason"] == "EPOCH_BOUNDARY_MISSING"
    assert result["old_position_continuity"] == "UNKNOWN"
