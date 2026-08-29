from datetime import UTC, datetime, timedelta

from kquant_crypto.collection_session import classify_collection_session, read_collection_gate, read_collection_session


def test_stale_running_marker_is_not_reported_as_live():
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    value = classify_collection_session(
        {"status": "running", "heartbeat_at": "2026-08-24T11:50:00+00:00"},
        now=now,
        stale_after_seconds=180,
    )
    assert value["status"] == "stale"
    assert value["collector_liveness"] == "stale"
    assert value["failed_checks"] == ["collector_heartbeat_stale"]


def test_fresh_running_marker_remains_live(tmp_path):
    now = datetime.now(UTC)
    (tmp_path / "crypto_collection_running.json").write_text(
        '{"status":"running","heartbeat_at":"' + (now - timedelta(seconds=5)).isoformat() + '"}',
        encoding="utf-8",
    )
    value = read_collection_session(tmp_path, now=now)
    assert value["status"] == "running"
    assert value["collector_liveness"] == "running"


def test_completed_report_gate_is_shared_by_readiness_and_collection_checks(tmp_path):
    (tmp_path / "crypto_collection_latest.json").write_text(
        '{"status":"completed","collection_gate":{"status":"PASS","observed_hours":24.0}}',
        encoding="utf-8",
    )
    value = read_collection_gate(tmp_path)
    assert value["status"] == "PASS"
    assert value["observed_hours"] == 24.0
