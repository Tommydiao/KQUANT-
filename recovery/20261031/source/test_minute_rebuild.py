"""Critical isolated-rebuild recovery/quality tests; no credentials or network."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import csv
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import minute_rebuild as rebuild

UTC = timezone.utc
AS_OF = datetime(2026, 10, 7, 7, 0, tzinfo=UTC)


def test_calendar(day):
    opening = datetime(day.year, day.month, day.day, 14, 30, tzinfo=UTC)
    return opening, opening + timedelta(minutes=2)


# This is a two-minute synthetic session, so recovery tests remain small and
# explicitly exercise unions rather than mirroring a 390-row implementation.
test_calendar.__test__ = False


@pytest.fixture
def manifest():
    return {"items": [
        {"symbol": "AAPL", "provider_symbol": "AAPL.US", "identity_status": "verified"},
        {"symbol": "NVDA", "provider_symbol": "NVDA.US", "identity_status": "verified"},
        {"symbol": "UNKNOWN", "provider_symbol": None, "identity_status": "identity_unconfirmed"},
    ]}


@pytest.fixture
def plan(manifest):
    return rebuild.build_plan(manifest, AS_OF, session_count=2,
                              calendar=(lambda day: day.weekday() < 5, test_calendar))


@pytest.fixture
def task(plan):
    return plan["tasks"][0]


def candles(task, offsets=(0, 1), **changes):
    opening = rebuild.aware(task["opening"])
    return [SimpleNamespace(timestamp=opening + timedelta(minutes=offset),
                            open=Decimal("10.000000000000000001"), high=Decimal("11"),
                            low=Decimal("9"), close=Decimal("10.5"), volume=123,
                            turnover=Decimal("1271.1234567890123456789"), **{})
            for offset in offsets]


def append(store, task, offsets=(0, 1), *, instant=AS_OF, rows=None):
    return store.append(task, rebuild.raw_rows(rows if rows is not None else candles(task, offsets)),
                        instant, instant + timedelta(seconds=1))


def test_plan_latest_closed_session_first_and_identity_unresolved(plan):
    assert [s["session"] for s in plan["sessions_newest_first"]] == ["2026-10-06", "2026-10-05"]
    assert [(t["symbol"], t["session"]) for t in plan["tasks"]] == [
        ("NVDA", "2026-10-06"), ("AAPL", "2026-10-06"),
        ("NVDA", "2026-10-05"), ("AAPL", "2026-10-05")]
    assert plan["unresolved_symbols"] == [{"symbol": "UNKNOWN", "state": "IDENTITY_UNRESOLVED"}]
    assert plan["theoretical_slots"] == 8


def test_plan_uses_real_exchange_calendar_and_excludes_open_session(manifest):
    plan = rebuild.build_plan(manifest, datetime(2026, 10, 7, 15, 0, tzinfo=UTC), session_count=20)
    assert plan["sessions_newest_first"][0]["session"] == "2026-10-06"
    assert plan["sessions_newest_first"][-1]["session"] == "2026-09-09"
    assert all(s["expected_minutes"] == 390 for s in plan["sessions_newest_first"])


def test_reject_symbols_outside_manifest(manifest):
    with pytest.raises(ValueError, match="SYMBOL_OUTSIDE"):
        rebuild.build_plan(manifest, AS_OF, session_count=1, symbols=["SPY"])


def test_unresolved_index_future_labels_are_preserved_without_guessing(manifest):
    manifest["items"].extend([
        {"symbol": "/ES[Z26]", "provider_symbol": None, "identity_status": "identity_unconfirmed"},
        {"symbol": "$COMP", "provider_symbol": None, "identity_status": "identity_unconfirmed"},
        {"symbol": "HBM:XETA", "provider_symbol": None, "identity_status": "identity_unconfirmed"},
    ])
    plan = rebuild.build_plan(manifest, AS_OF, session_count=1,
                              calendar=(lambda day: day.weekday() < 5, test_calendar))
    assert plan["eligible_symbols"] == 2
    assert [item["symbol"] for item in plan["unresolved_symbols"]] == ["UNKNOWN", "/ES[Z26]", "$COMP", "HBM:XETA"]


def test_native_decimal_strings_preserved_without_unit_admission(task):
    rows = rebuild.raw_rows(candles(task))
    assert rows[0]["open"] == "10.000000000000000001"
    assert rows[0]["turnover"] == "1271.1234567890123456789"
    result = rebuild.validate_page(task, rows, AS_OF, AS_OF)
    assert result["historical_page_complete"]
    assert not result["production_admission_verified"]
    assert not result["accepted_rows"][0]["native_field_units_admission_verified"]


@pytest.mark.parametrize("field,value,reason", [
    ("volume", -1, "INVALID_NATIVE_VOLUME"),
    ("turnover", Decimal("NaN"), "INVALID_NATIVE_TURNOVER"),
    ("turnover", None, "INVALID_NATIVE_TURNOVER"),
    ("close", Decimal("Infinity"), "INVALID_NATIVE_CLOSE"),
    ("low", 0, "INVALID_NATIVE_LOW"),
    ("high", Decimal("9.5"), "INVALID_OHLC"),
    ("volume", True, "INVALID_NATIVE_VOLUME"),
])
def test_native_fields_and_ohlc_quality(task, field, value, reason):
    rows = candles(task)
    setattr(rows[0], field, value)
    result = rebuild.validate_page(task, rebuild.raw_rows(rows), AS_OF, AS_OF)
    assert not result["historical_page_complete"]
    assert reason in result["rejection_counts"]
    assert len(result["missing_minutes"]) == 1


def test_naive_timestamp_default_rejected_and_explicit_profile_applied(task):
    rows = candles(task)
    # Shanghai local naive 22:30 is the native adapter case; it is not inferred.
    for row in rows:
        row.timestamp = row.timestamp.astimezone(rebuild.ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    raw = rebuild.raw_rows(rows)
    rejected = rebuild.validate_page(task, raw, AS_OF, AS_OF)
    assert rejected["rejection_counts"] == {"UNVERIFIED_NAIVE_TIMESTAMP": 2}
    explicit_task = {**task, "contract": {**task["contract"], "timestamp_profile": {
        "name": "VERIFIED_SDK_NAIVE_ASIA_SHANGHAI", "naive_timezone": "Asia/Shanghai",
        "evidence_sha256": "a" * 64}}}
    admitted = rebuild.validate_page(explicit_task, raw, AS_OF, AS_OF)
    assert admitted["historical_page_complete"]
    assert admitted["accepted_rows"][0]["open_at"] == task["opening"]


def test_profile_requires_bound_evidence_and_rejects_secret_file():
    with pytest.raises(ValueError, match="REQUIRES_VERIFIED"):
        rebuild.timestamp_profile("verified-naive-asia-shanghai")
    with pytest.raises(ValueError, match="INVALID_TIMESTAMP_EVIDENCE_PATH"):
        rebuild.timestamp_profile("verified-naive-asia-shanghai", rebuild.ROOT / ".env")


def test_closed_grid_alignment_and_truncation(task):
    rows = candles(task, (0, 1, 2))
    rows[0].timestamp += timedelta(seconds=1)
    result = rebuild.validate_page(task, rebuild.raw_rows(rows), AS_OF, AS_OF)
    assert result["rejection_counts"]["OUTSIDE_REGULAR_MINUTE_GRID"] == 2
    with pytest.raises(ValueError, match="REQUEST_NOT_AFTER_SESSION"):
        rebuild.validate_page(task, [], rebuild.aware(task["opening"]), AS_OF)
    at_limit = rebuild.validate_page(task, rebuild.raw_rows(candles(task, (0,) * 1000)), AS_OF, AS_OF)
    assert at_limit["state"] == "PAGE_AT_PROVIDER_LIMIT"
    assert not at_limit["historical_page_complete"]


def test_partial_pages_union_survives_resume_and_complete_skips_fetch(tmp_path, task, plan):
    store = rebuild.PageStore(tmp_path)
    append(store, task, (0,))
    assert store.coverage(task)["state"] == "PARTIAL"
    append(store, task, (1,), instant=AS_OF + timedelta(seconds=2))
    assert rebuild.PageStore(tmp_path).coverage(task)["historical_market_complete"]
    one_task_plan = {**plan, "tasks": [task]}
    def forbidden(*args):
        pytest.fail("Complete cache should not cause a provider request")
    report = rebuild.execute_plan(one_task_plan, rebuild.PageStore(tmp_path), forbidden)
    assert report["requests"] == 0 and report["skipped_complete"] == 1


def test_orphaned_committed_page_repairs_atomic_index(tmp_path, task):
    store = rebuild.PageStore(tmp_path)
    append(store, task)
    # Simulate interruption after the immutable page was committed but before
    # the newer coverage index replaced its preceding empty version.
    rebuild.atomic_json(store.index_path, {"schema": rebuild.SCHEMA, "tasks": {}})
    resumed = rebuild.PageStore(tmp_path)
    assert resumed.coverage(task)["historical_market_complete"]
    assert resumed.index["tasks"][task["task_id"]]["pages"]


def test_immutable_page_tampering_blocks_resume(tmp_path, task):
    store = rebuild.PageStore(tmp_path)
    page_sha = append(store, task)
    page_path = store.pages / f"{page_sha}.json"
    page_path.write_bytes(page_path.read_bytes() + b" ")
    with pytest.raises(rebuild.CacheIntegrityError, match="IMMUTABLE_PAGE_CHANGED"):
        rebuild.PageStore(tmp_path).coverage(task)


def test_indexed_missing_page_blocks_skip(tmp_path, task):
    store = rebuild.PageStore(tmp_path)
    page_sha = append(store, task)
    (store.pages / f"{page_sha}.json").unlink()
    with pytest.raises(rebuild.CacheIntegrityError, match="INDEXED_PAGE_MISSING"):
        rebuild.PageStore(tmp_path)


def test_conflicts_preserve_both_pages_without_choosing_latest(tmp_path, task):
    store = rebuild.PageStore(tmp_path)
    first_sha = append(store, task)
    new = candles(task)
    new[0].close = Decimal("10.6")
    second_sha = append(store, task, rows=new, instant=AS_OF + timedelta(seconds=2))
    coverage = rebuild.PageStore(tmp_path).coverage(task)
    assert coverage["state"] == "CONFLICT"
    assert coverage["conflicting_minutes"] == [task["opening"]]
    assert coverage["accepted_unique_minutes"] == 1
    assert not coverage["historical_market_complete"]
    assert first_sha != second_sha and len(list(store.pages.glob("*.json"))) == 2


def test_economically_equivalent_decimal_spellings_do_not_conflict(tmp_path, task):
    store = rebuild.PageStore(tmp_path)
    append(store, task)
    new = candles(task)
    new[0].high = Decimal("11.000")
    append(store, task, rows=new, instant=AS_OF + timedelta(seconds=2))
    assert store.coverage(task)["historical_market_complete"]
    assert not store.coverage(task)["conflicting_minutes"]


def test_conflict_comparison_does_not_round_decimal_values_beyond_default_precision(tmp_path, task):
    store = rebuild.PageStore(tmp_path)
    original = candles(task)
    original[0].turnover = Decimal("123.123456789012345678901234567890123456")
    append(store, task, rows=original)
    revised = candles(task)
    revised[0].turnover = Decimal("123.123456789012345678901234567890123457")
    append(store, task, rows=revised, instant=AS_OF + timedelta(seconds=2))
    assert store.coverage(task)["state"] == "CONFLICT"


def test_matrix_keeps_unresolved_identity_counts_blank(tmp_path, plan, task):
    store = rebuild.PageStore(tmp_path)
    append(store, task)
    path = rebuild.export_coverage_matrix(plan, store)
    with open(path, encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 6
    assert rows[0]["state"] == "COMPLETE"
    unresolved = [row for row in rows if row["state"] == "IDENTITY_UNRESOLVED"]
    assert len(unresolved) == 2
    assert all(row["expected_minutes"] == "" and row["missing_minutes_count"] == "" for row in unresolved)


def test_duplicate_with_different_native_value_conflicts_inside_page(tmp_path, task):
    rows = candles(task, (0, 1, 0))
    rows[-1].close = Decimal("10.6")
    store = rebuild.PageStore(tmp_path)
    append(store, task, rows=rows)
    assert store.coverage(task)["state"] == "CONFLICT"


def test_capped_page_cannot_establish_coverage(tmp_path, task):
    store = rebuild.PageStore(tmp_path)
    append(store, task, rows=candles(task, (0, 1) * 500))
    coverage = store.coverage(task)
    assert coverage["state"] == "PAGE_AT_PROVIDER_LIMIT"
    assert coverage["accepted_unique_minutes"] == 0


class ProviderError(Exception):
    def __init__(self, code):
        self.code = code
        self.kind = "OpenApi"
        super().__init__("Private arbitrary SDK message SECRET_TOKEN_MUST_NOT_ESCAPE")


@pytest.mark.parametrize("code,category", [(401003, "TOKEN_EXPIRED"), (301607, "HISTORY_MONTHLY_SYMBOL_QUOTA")])
def test_auth_and_monthly_quota_stop_batch_without_secret_text(tmp_path, plan, code, category):
    calls = []
    def failing(symbol, day):
        calls.append((symbol, day))
        raise ProviderError(code)
    report = rebuild.execute_plan(plan, rebuild.PageStore(tmp_path), failing,
                                  max_requests=20, now=lambda: AS_OF, sleeper=lambda seconds: None)
    expected = "MONTHLY_QUOTA_RESTRICTED" if category == "HISTORY_MONTHLY_SYMBOL_QUOTA" else "BLOCKED_" + category
    assert report["status"] == expected and report["requests"] == 1
    assert len(calls) == 1
    assert "SECRET_TOKEN" not in json.dumps(report)
    assert "SECRET_TOKEN" not in b"".join(path.read_bytes() for path in tmp_path.rglob("*.json")).decode()


def test_rate_limit_bounded_retry_and_request_budget(tmp_path, plan, task):
    calls, waits = [], []
    def fetch(symbol, day):
        calls.append((symbol, day))
        if len(calls) == 1:
            raise ProviderError(301606)
        return candles(task)
    report = rebuild.execute_plan(plan, rebuild.PageStore(tmp_path), fetch, max_requests=2,
                                  now=lambda: AS_OF, sleeper=waits.append)
    assert report["requests"] == 2 and report["status"] == "REQUEST_BUDGET_REACHED"
    assert 30.0 in waits and 1.0 in waits
    assert report["completed_tasks"] == 1


def test_unverified_naive_sdk_stops_before_spending_more_symbol_quota(tmp_path, plan, task):
    calls = []
    def fetch(symbol, day):
        calls.append((symbol, day))
        rows = candles(task)
        for row in rows:
            row.timestamp = row.timestamp.replace(tzinfo=None)
        return rows
    report = rebuild.execute_plan(plan, rebuild.PageStore(tmp_path), fetch, max_requests=20,
                                  now=lambda: AS_OF, sleeper=lambda seconds: None)
    assert report["status"] == "BLOCKED_TIMESTAMP_CONTRACT"
    assert report["requests"] == 1 and len(calls) == 1


def test_single_day_at_cap_stops_for_diagnosis(tmp_path, plan, task):
    report = rebuild.execute_plan(plan, rebuild.PageStore(tmp_path),
                                  lambda *args: candles(task, (0, 1) * 500), max_requests=20,
                                  now=lambda: AS_OF, sleeper=lambda seconds: None)
    assert report["status"] == "BLOCKED_SINGLE_DAY_PAGE_AT_LIMIT" and report["requests"] == 1


def test_one_symbol_no_quote_access_allows_other_symbols_and_is_persisted(tmp_path, plan):
    scope, calls = "1" * 64, []
    task_map = {(task["provider_symbol"], date.fromisoformat(task["session"])): task for task in plan["tasks"]}
    def fetch(symbol, day):
        calls.append((symbol, day))
        if symbol == "NVDA.US":
            raise ProviderError(301604)
        return candles(task_map[(symbol, day)])
    report = rebuild.execute_plan(plan, rebuild.PageStore(tmp_path), fetch, max_requests=20,
                                  provider_scope_sha256=scope, now=lambda: AS_OF, sleeper=lambda seconds: None)
    assert report["no_quote_access"] == 1 and report["completed_tasks"] == 2
    assert [symbol for symbol, day in calls] == ["NVDA.US", "AAPL.US", "AAPL.US"]
    resumed = rebuild.execute_plan(plan, rebuild.PageStore(tmp_path),
                                    lambda *args: pytest.fail("Denied symbol needs an explicit retry"),
                                    provider_scope_sha256=scope, now=lambda: AS_OF, sleeper=lambda seconds: None)
    assert resumed["requests"] == 0 and resumed["skipped_no_quote_access"] == 2


def test_quota_continues_only_same_scope_current_month_successful_symbols(tmp_path, plan, task):
    scope, calls = "1" * 64, []
    store = rebuild.PageStore(tmp_path)
    proven_sha = store.append(task, rebuild.raw_rows(candles(task)), AS_OF, AS_OF,
                              provider_scope_sha256=scope)
    task_map = {(task["provider_symbol"], date.fromisoformat(task["session"])): task for task in plan["tasks"]}
    def fetch(symbol, day):
        calls.append((symbol, day))
        if symbol == "AAPL.US":
            raise ProviderError(301607)
        return candles(task_map[(symbol, day)])
    report = rebuild.execute_plan(plan, store, fetch, max_requests=20,
                                  provider_scope_sha256=scope, now=lambda: AS_OF, sleeper=lambda seconds: None)
    assert report["status"] == "MONTHLY_QUOTA_RESTRICTED"
    assert [symbol for symbol, day in calls] == ["AAPL.US", "NVDA.US"]
    assert report["completed_tasks"] == 1
    assert report["quota_deferred_tasks"] == 1
    assert proven_sha in report["quota_scope"]["known_provider_symbols_and_proof_pages"]["NVDA.US"]
    # A restarted batch keeps the same month/scope restriction and does not
    # waste another request on the newly rejected symbol.
    second = rebuild.execute_plan(plan, rebuild.PageStore(tmp_path),
                                  lambda *args: pytest.fail("Known month quota must survive restart"),
                                  provider_scope_sha256=scope, now=lambda: AS_OF, sleeper=lambda seconds: None)
    assert second["status"] == "MONTHLY_QUOTA_RESTRICTED" and second["requests"] == 0
    assert second["quota_deferred_tasks"] == 2


def test_quota_excludes_old_month_unbound_and_other_app_successes(tmp_path, plan, task):
    store = rebuild.PageStore(tmp_path)
    scope = "1" * 64
    # Request dates can be later than their historical session, and the current
    # month proof must refer to the actual request, not the candle's date.
    store.append(task, rebuild.raw_rows(candles(task)), AS_OF, AS_OF, provider_scope_sha256="2" * 64)
    append(store, task, instant=AS_OF + timedelta(seconds=1))
    november = datetime(2026, 11, 7, tzinfo=UTC)
    assert store.used_symbol_sources(AS_OF, scope) == {}
    assert store.used_symbol_sources(november, "2" * 64) == {}


def test_quota_index_cannot_relabel_old_failure_page_as_current_month(tmp_path, task):
    scope = "1" * 64
    store = rebuild.PageStore(tmp_path)
    page_sha = store.append(task, [], AS_OF, AS_OF, error=rebuild.safe_error(ProviderError(301607)),
                             provider_scope_sha256=scope)
    store.record_quota_block(page_sha, AS_OF, scope)
    store.index["quota_blocks"][-1]["months"] = ["2026-11", "2026-11"]
    store.commit_index()
    with pytest.raises(rebuild.CacheIntegrityError, match="MONTHLY_QUOTA_PROOF_CHANGED"):
        store.active_quota_block(datetime(2026, 11, 7, tzinfo=UTC), scope)


def test_reporting_summary_and_csv_do_not_revalidate_entire_archive(tmp_path, plan, task, monkeypatch):
    store = rebuild.PageStore(tmp_path)
    append(store, task)
    original = Path.read_bytes
    def forbid_raw_page_read(path):
        if path.parent.name == "pages":
            pytest.fail("Batch reporting must not re-read/validate every raw page")
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", forbid_raw_page_read)
    resumed = rebuild.PageStore(tmp_path)
    summary = rebuild.summarize(plan, resumed)
    assert summary["accepted_unique_minutes"] == 2
    assert summary["coverage_basis"] == "ATOMIC_INDEX_REPORTING_PROJECTION"
    rebuild.export_coverage_matrix(plan, resumed)


def test_bounded_resume_progresses_pending_work_before_full_archive_audit(tmp_path, plan, task, monkeypatch):
    store = rebuild.PageStore(tmp_path)
    append(store, task)
    original = store.coverage
    seen, calls = [], []
    def observed_coverage(candidate):
        seen.append(candidate["task_id"])
        return original(candidate)
    monkeypatch.setattr(store, "coverage", observed_coverage)
    second = plan["tasks"][1]
    def fetch(symbol, day):
        calls.append((symbol, day))
        return candles(second)
    report = rebuild.execute_plan(plan, store, fetch, max_requests=1,
                                  now=lambda: AS_OF, sleeper=lambda seconds: None)
    assert calls == [(second["provider_symbol"], date.fromisoformat(second["session"]))]
    assert task["task_id"] not in seen
    assert report["cached_complete_tasks_not_selected_first"] == 1
    assert report["requests"] == 1


def test_worker_deadline_preserves_receipt_budget_instead_of_sleeping_past_parent(tmp_path, plan):
    # The next monotonic instant is outside the deadline before any request.
    report = rebuild.execute_plan(plan, rebuild.PageStore(tmp_path),
                                  lambda *args: pytest.fail("Expired work budget must not issue a request"),
                                  deadline_monotonic=5.0, monotonic=lambda: 6.0)
    assert report["requests"] == 0 and report["status"] == "RUN_TIME_BUDGET_REACHED"


def test_partial_pages_stop_after_finite_successful_page_attempts(tmp_path, plan, task):
    store = rebuild.PageStore(tmp_path)
    for seconds in range(3):
        append(store, task, (0,), instant=AS_OF + timedelta(seconds=seconds))
    report = rebuild.execute_plan({**plan, "tasks": [task]}, store,
                                  lambda *args: pytest.fail("No unbounded partial retries"))
    assert report["requests"] == 0 and report["partial_final"] == 1
    assert store.coverage(task)["state"] == "PARTIAL"


def test_single_writer_lock_released_after_exception(tmp_path):
    with pytest.raises(RuntimeError, match="simulated"):
        with rebuild.writer_lock(tmp_path):
            with pytest.raises(rebuild.CacheIntegrityError, match="ANOTHER"):
                with rebuild.writer_lock(tmp_path):
                    pass
            raise RuntimeError("simulated")
    with rebuild.writer_lock(tmp_path):
        pass


def test_parent_timeout_recovers_child_committed_page_without_claiming_request_count(tmp_path, manifest, monkeypatch, capsys):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(rebuild, "ROOT", tmp_path)
    monkeypatch.setattr(rebuild, "CACHE_ROOT", tmp_path / "minute-rebuild")
    monkeypatch.setattr(sys, "argv", ["minute_rebuild.py", "bounded-live", "--manifest", str(manifest_path),
                                    "--sessions", "1", "--symbols", "NVDA", "--cache-name", "timeout-test"])
    def timed_out_child(*args, **kwargs):
        directory = tmp_path / "minute-rebuild/timeout-test"
        frozen_plan = json.loads(next((directory / "plans").glob("*.json")).read_bytes())
        task = frozen_plan["tasks"][0]
        with rebuild.writer_lock(directory):
            store = rebuild.PageStore(directory)
            request = datetime.now(UTC)
            store.append(task, rebuild.raw_rows(candles(task, (0,))), request, request)
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(rebuild.subprocess, "run", timed_out_child)
    rebuild.main()
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "WORKER_TIMED_OUT" and report["child_terminated"]
    assert report["requests"] is None
    assert report["coverage"]["accepted_unique_minutes"] == 1
    assert report["coverage"]["task_states"] == {"PARTIAL": 1}
    assert Path(report["receipt_path"]).exists()
