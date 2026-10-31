"""Actual disposable children; no business-store creation, SDK, or host refresh."""
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys
from time import monotonic
from zoneinfo import ZoneInfo

import pytest

from kquant import options_host_clock as host
from kquant import status_child_telemetry as telemetry
from kquant import status_worker as worker


GUARD = r'''
import os, sys
def guard(event, args):
    if event.startswith("socket.") or event in {"subprocess.Popen", "os.system"}:
        raise RuntimeError("P13_NETWORK_OR_HOST_CALL_FORBIDDEN")
    if event == "import" and str(args[0]).split(".")[0] in {"longbridge", "futu", "requests", "httpx", "dotenv"}:
        raise RuntimeError("P13_SDK_IMPORT_FORBIDDEN")
    if event == "sqlite3.connect" and "mode=ro" not in str(args[0]):
        raise RuntimeError("P13_DATABASE_WRITE_FORBIDDEN")
    if event == "sqlite3.connect" and "/f:/" in str(args[0]).lower():
        raise RuntimeError("P13_F_DRIVE_FORBIDDEN")
    if event == "open" and isinstance(args[0], (str, bytes)):
        name, mode, flags = os.fsdecode(args[0]).lower(), args[1] or "", args[2] or 0
        if name.startswith(("f:\\", "f:/", "\\\\?\\f:\\")):
            raise RuntimeError("P13_F_DRIVE_FORBIDDEN")
        if any(word in name for word in ("credential", "secret", ".env")) or any(char in mode for char in "wax+") or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            raise RuntimeError("P13_WRITE_OR_CREDENTIAL_READ_FORBIDDEN")
sys.addaudithook(guard)
'''


def command(program):
    return [sys.executable, "-B", "-c", GUARD + "\n" + program]


def test_actual_child_success_and_failure_share_denominator():
    success = worker.run_json(command('print("{\\"ok\\":true}")'), diagnostics=True)
    before = success["query_transport"]["denominator"]
    with pytest.raises(worker.StatusQueryFailure) as problem:
        worker.run_json(command('import sys; print("{}"); sys.exit(7)'), diagnostics=True)
    failure = problem.value.diagnostic["query_transport"]
    after = failure["denominator"]
    assert failure["child_pid"] > 0 and failure["returncode"] == 7
    assert after["attempts"] == before["attempts"] + 1
    assert after["successes"] == before["successes"]
    assert after["failures"] == before["failures"] + 1
    assert after["successes"] + after["failures"] == after["attempts"]
    assert len(success['query_transport']['request_id'])==32
    assert success['query_transport']['request_id']!=failure['request_id']
    assert 0<=success['query_transport']['first_stdout_ms']<=success['query_transport']['process_ms']


@pytest.mark.parametrize("phase", ["import", "query", "clock", "encode", "ipc"])
def test_actual_timeout_reaps_child_and_keeps_last_phase(phase):
    program = ('import time, sys\nfrom kquant.status_child_telemetry import begin_child, emit_stage\n'
               'begin_child()\nemit_stage(' + repr(phase) + ', "start")\n'
               'sys.stderr.write("PRIVATE_TOKEN=value private/path\\n"); sys.stderr.flush()\ntime.sleep(30)')
    with pytest.raises(worker.StatusQueryTimeout) as problem:
        worker.run_json(command(program), timeout=1.5, diagnostics=True)
    detail = problem.value.diagnostic
    transport = detail["query_transport"]
    assert detail["code"] == "PROCESS_DEADLINE"
    assert transport["last_phase"] == phase
    assert transport["child_pid"] > 0 and transport["returncode"] is not None
    assert transport["child_reaped"] and transport["ipc_complete"]
    assert transport["deadline_ms"] == 1500
    assert transport["stages_ms"][phase] is None
    assert len(transport["stderr_sanitized"]) <= telemetry.STDERR_LIMIT
    assert "PRIVATE_TOKEN" not in str(detail) and "private/path" not in str(detail)


def test_actual_stderr_flood_is_drained_bounded_and_sanitized():
    program = ('import sys\nfrom kquant.status_child_telemetry import begin_child, emit_stage\n'
               'begin_child()\nemit_stage("query", "start")\n'
               'sys.stderr.write("PRIVATE_TOKEN=secret\\n" * 20000); sys.stderr.flush()\n'
               'emit_stage("query", "done", elapsed_ms=3.5)\nprint("{}")')
    transport = worker.run_json(command(program), diagnostics=True)["query_transport"]
    assert transport["stderr_bytes"] > telemetry.STDERR_LIMIT
    assert transport["stderr_truncated"]
    assert transport["stages_ms"]["query"] == 3.5
    assert "PRIVATE_TOKEN" not in str(transport) and "secret" not in str(transport)


@pytest.mark.parametrize("value", ["[1]", "{", "null", '{"_status_error":{}}'])
def test_actual_invalid_serialization_has_transport(value):
    with pytest.raises(worker.StatusQueryFailure) as problem:
        worker.run_json(command("print(" + repr(value) + ")"), diagnostics=True)
    detail = problem.value.diagnostic
    assert detail["code"] == "SERIALIZATION_INVALID"
    assert detail["query_transport"]["returncode"] == 0
    assert detail["query_transport"]["decode_ms"] >= 0


def test_actual_response_bound_is_enforced(monkeypatch):
    monkeypatch.setattr(telemetry, "STDOUT_LIMIT", 128)
    with pytest.raises(worker.StatusQueryFailure) as problem:
        worker.run_json(command('print("{\\"text\\":\\"" + "x" * 65536 + "\\"}")'), diagnostics=True)
    transport = problem.value.diagnostic["query_transport"]
    assert transport["response_truncated"] and transport["response_bytes"] > 65536
    assert transport["child_reaped"] and transport["ipc_complete"]


def test_process_start_failure_has_same_schema(tmp_path):
    with pytest.raises(worker.StatusQueryFailure) as problem:
        worker.run_json([str(tmp_path / "NONEXISTENT.exe")], diagnostics=True)
    detail = problem.value.diagnostic
    assert detail["code"] == "PROCESS_START_FAILED"
    assert detail["query_transport"]["schema"] == "STATUS_TRANSPORT_V1"
    assert detail["query_transport"]["child_pid"] is None


def test_actual_over_nested_json_keeps_failure_in_denominator():
    with pytest.raises(worker.StatusQueryFailure) as problem:
        worker.run_json(command('print("[" * 10000 + "]" * 10000)'), diagnostics=True)
    assert problem.value.diagnostic["code"] == "SERIALIZATION_INVALID"
    assert problem.value.diagnostic["query_transport"]["outcome"] == "SERIALIZATION_INVALID"


def test_malformed_stage_protocol_cannot_export_arbitrary_fields():
    program = ('import sys\nsys.stderr.write(' + repr(
        'STATUS_STAGE_V1 {"stage":"query","event":"start","at_ms":0,"private_token":"PRIVATE_TOKEN"}\n'
        'STATUS_STAGE_V1 {"stage":"query","event":"start","at_ms":NaN}\n') + ')\nprint("{}")')
    result = worker.run_json(command(program), diagnostics=True)["query_transport"]
    assert result["stderr_sanitized"] == ""
    assert result["last_phase"] == "spawn"


def test_policy_preflight_failure_uses_same_denominator_without_spawning(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    with pytest.raises(worker.StatusQueryFailure) as problem:
        worker.load_current_cards(tmp_path / "NONEXISTENT.sqlite3", research_strategy="opening_momentum")
    transport = problem.value.diagnostic["query_transport"]
    assert transport["child_pid"] is None and transport["last_phase"] == "policy"
    assert transport["denominator"]["attempts"] == transport["denominator"]["successes"] + transport["denominator"]["failures"]


def test_safe_failure_cannot_export_unknown_sqlite_or_exception_identifiers():
    class PRIVATE_TOKEN(Exception):
        sqlite_errorname = "PRIVATE_TOKEN"
    result = worker.safe_failure(PRIVATE_TOKEN("private/path"))
    assert "PRIVATE_TOKEN" not in str(result) and "private/path" not in str(result)
    assert result["error_type"] == "RuntimeError" and result["sqlite_code"] is None


def test_actual_missing_database_entrypoint_never_creates_it(tmp_path):
    missing = tmp_path / "NONEXISTENT.sqlite3"
    program = ('import runpy, sys\nsys.argv = ' + repr(["kquant.status_worker", str(missing),
        "--strategy", "opening_momentum", "--diagnostic-envelope"]) +
        '\nrunpy.run_module("kquant.status_worker", run_name="__main__")')
    with pytest.raises(worker.StatusQueryFailure) as problem:
        worker.run_json(command(program), diagnostics=True)
    detail = problem.value.diagnostic
    assert detail["code"] == "DATABASE_MISSING"
    transport = detail["query_transport"]
    assert transport["stages_ms"]["import"] is not None
    assert transport["stages_ms"]["query"] is not None
    assert transport["stages_ms"]["encode"] is not None
    assert transport["stages_ms"]["ipc"] is not None
    assert not missing.exists()


@pytest.mark.parametrize("kind", ["current", "compact"])
def test_actual_retained_status_child_is_read_only_and_sdk_host_free(kind, monkeypatch):
    root_value = os.environ.get("KQUANT_P13_READONLY_ROOT")
    if not root_value:
        pytest.skip("explicit retained-store root required; this test never creates or copies DBs")
    root = Path(root_value).resolve()
    main = root / "runtime/work/kquant_us.sqlite3"
    research = root / "runtime/work/options_one_minute/opening_trend_research.sqlite3"
    assert main.is_file() and research.is_file()
    with sqlite3.connect(research.as_uri() + "?mode=ro", uri=True, timeout=.05) as db:
        deadline = monotonic() + .2
        db.execute("PRAGMA query_only=ON")
        db.set_progress_handler(lambda: monotonic() >= deadline, 1000)
        row = db.execute("SELECT evaluated_at FROM evaluations ORDER BY rowid DESC LIMIT 1").fetchone()
    assert row is not None
    for name in ("KQUANT_RUNTIME_DATA_ROOT", "KQUANT_RUNTIME_PATH_BINDING",
                 "KQUANT_RUNTIME_PATH_BINDING_SHA256", "KQUANT_RUNTIME_MANIFEST"):
        monkeypatch.delenv(name, raising=False)
    args = ["kquant.status_worker", str(main), "--strategy", "opening_momentum",
            "--research-store", str(research), "--as-of", row[0], "--diagnostic-envelope"]
    args.extend(["--current-cards"] if kind == "current" else ["--compact", "--projection-after", "0"])
    program = 'import runpy, sys\nsys.argv = ' + repr(args) + '\nrunpy.run_module("kquant.status_worker", run_name="__main__")'
    result = worker.run_json(command(program), diagnostics=True, lane=f"opening_momentum:{kind}")
    transport = result["query_transport"]
    assert transport["query_lane"] == f"opening_momentum:{kind}"
    assert transport["outcome"] == "SUCCESS" and transport["deadline_ms"] == 2000
    assert transport["returncode"] == 0 and transport["child_reaped"]
    for phase in ("spawn", "import", "query", "clock", "encode", "ipc"):
        assert transport["stages_ms"][phase] is not None
    assert result["external_clock"]["precision_verified"] is False
    assert result["external_clock"]["qualification_approval"] is False


NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)


def clock_file(tmp_path, **changes):
    status = {"state": "SYNCED_SYSTEM_REPORT", "source": "time.windows.com", "leap": 0,
        "stratum": 3, "last_sync_error": 0, "last_sync_age_seconds": 50,
        "checked_at": (NOW - timedelta(seconds=30)).isoformat()}
    status.update(changes)
    path = tmp_path / host.SNAPSHOT_NAME
    path.write_text(json.dumps({"schema": host.SCHEMA, "status": status}), encoding="utf-8")
    return path


def test_shared_clock_read_never_calls_host_and_never_renews_proof(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("cached clock read must not query the host")
    monkeypatch.setattr(host.subprocess, "run", forbidden)
    path = clock_file(tmp_path, precision_verified=True, qualification_approval=True,
                      private_token="PRIVATE_TOKEN=value")
    first = host.read_status(path=path, now=NOW)
    later = host.read_status(path=path, now=NOW + timedelta(seconds=10))
    assert first["state"] == "SYNCED_SYSTEM_REPORT" and first["snapshot_state"] == "FRESH"
    assert first["checked_at"] == later["checked_at"]
    assert first["last_sync_age_seconds"] == 80 and later["last_sync_age_seconds"] == 90
    assert first["precision_verified"] is False and first["qualification_approval"] is False
    assert "PRIVATE_TOKEN" not in str(first)


@pytest.mark.parametrize("offset", [-901, 1])
def test_stale_or_future_shared_clock_fails_closed(tmp_path, offset):
    result = host.read_status(path=clock_file(tmp_path, checked_at=(NOW + timedelta(seconds=offset)).isoformat()), now=NOW)
    assert result["state"] == "UNAVAILABLE" and result["snapshot_state"] == "STALE"
    assert result["error_code"] == "CLOCK_SNAPSHOT_STALE_OR_FUTURE"


@pytest.mark.parametrize("raw", ["{", "[]", '{"schema":"WRONG"}', "x" * (host.MAX_SNAPSHOT_BYTES + 1)])
def test_invalid_or_oversized_clock_is_bounded(tmp_path, raw):
    path = tmp_path / host.SNAPSHOT_NAME
    path.write_text(raw, encoding="utf-8")
    result = host.read_status(path=path, now=NOW)
    assert result["state"] == "UNAVAILABLE"
    assert result["error_code"] in {"CLOCK_SNAPSHOT_INVALID", "CLOCK_SNAPSHOT_TOO_LARGE"}


def test_missing_shared_clock_does_not_refresh_or_create_it(tmp_path, monkeypatch):
    path = tmp_path / host.SNAPSHOT_NAME
    monkeypatch.setenv("KQUANT_OPTION_FOUNDATION_ROOT", str(tmp_path))
    result = host.read_status(now=NOW)
    assert result["error_code"] == "CLOCK_SNAPSHOT_MISSING" and not path.exists()


def test_system_report_parser_keeps_public_host_allowlist():
    text = ("Leap Indicator: 0\nStratum: 3\nLast Sync Error: 0\n"
            "Time since Last Good Sync Time: 50\nSource: time.windows.com,0x9\n")
    assert host.parse_status(text)["state"] == "SYNCED_SYSTEM_REPORT"
    assert host.parse_status(text.replace("time.windows.com", "PRIVATE_TOKEN"))["source"] is None


def test_cached_sync_report_age_is_not_frozen(tmp_path):
    result = host.read_status(path=clock_file(tmp_path, last_sync_age_seconds=3590), now=NOW)
    assert result["state"] == "SYNC_REPORT_STALE" and result["last_sync_age_seconds"] == 3620


@pytest.mark.parametrize("changes", [{"leap": float("nan")}, {"source": "PRIVATE_TOKEN"}, {"stratum": True}])
def test_cached_invalid_host_fields_never_authorize(tmp_path, changes):
    result = host.read_status(path=clock_file(tmp_path, **changes), now=NOW)
    assert result["state"] == "UNVERIFIED"
    assert result["precision_verified"] is False and "PRIVATE_TOKEN" not in str(result)


def test_existing_http_snapshot_read_is_memory_only_and_unavailable_stays_explicit(monkeypatch):
    from kquant.research_http_snapshots import ResearchHttpSnapshots
    from kquant.status_snapshot import SnapshotUnavailable
    def forbidden(*args, **kwargs):
        pytest.fail("HTTP snapshot reads must not load, query SDK, or refresh the host")
    monkeypatch.setattr(host, "read_status", forbidden)
    monkeypatch.setattr(host, "read_system_status", forbidden)
    feed = ResearchHttpSnapshots(forbidden, forbidden, forbidden, clock=lambda: NOW)
    try:
        with pytest.raises(SnapshotUnavailable):
            feed.read("opening_momentum", "current")
        day = NOW.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        feed.context = day, "TEST_SCOPE", {"research_ready": True}
        feed.context_at = monotonic()
        feed.observation.value = {"state": "RUNNING", "enforced": False}
        feed.observation.cache_key = "runtime"
        feed.observation.cache_generation = 0
        feed.observation.completed = monotonic()
        for kind in ("current", "compact"):
            cache = feed.caches["opening_momentum", kind]
            cache.value = {"session": day, "evaluations": [], "candidates": []}
            cache.cache_key = day, "TEST_SCOPE"
            cache.cache_generation = 0
            cache.completed = monotonic()
            assert feed.read("opening_momentum", kind)["snapshot"]["state"] == "FRESH"
            assert cache.future is None
    finally:
        feed.close()
