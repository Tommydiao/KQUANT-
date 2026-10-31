"""Critical full-audit/read-only/false-projection tests; no API or credentials."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import minute_audit as audit
import minute_rebuild as rebuild

UTC = timezone.utc
AS_OF = datetime(2026, 10, 7, 7, tzinfo=UTC)
MANIFEST = {"items": [{"symbol": "NVDA", "provider_symbol": "NVDA.US", "identity_status": "verified"},
                       {"symbol": "AAPL", "provider_symbol": "AAPL.US", "identity_status": "verified"},
                       {"symbol": "UNCONFIRMED", "provider_symbol": None, "identity_status": "identity_unconfirmed"}]}
PROFILE = rebuild.timestamp_profile()


def bounds(day):
    opening = datetime(day.year, day.month, day.day, 13, 30, tzinfo=UTC)
    return opening, opening + timedelta(minutes=2)


CALENDAR = (lambda day: day.weekday() < 5, bounds)


def candles(task, offsets=(0, 1)):
    return rebuild.raw_rows([SimpleNamespace(timestamp=rebuild.aware(task["opening"]) + timedelta(minutes=offset),
        open=Decimal("10.00000000000000000001"), high=Decimal("11"), low=Decimal("9"), close=Decimal("10.5"),
        volume=123, turnover=Decimal("1291.1234567890123456789")) for offset in offsets])


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "original-cache"
    plan = rebuild.build_plan(MANIFEST, AS_OF, session_count=1, profile=PROFILE, calendar=CALENDAR)
    with rebuild.writer_lock(path):
        store = rebuild.PageStore(path)
        store.append(plan["tasks"][0], candles(plan["tasks"][0]), AS_OF, AS_OF + timedelta(seconds=1))
        store.append(plan["tasks"][1], [], AS_OF, AS_OF + timedelta(seconds=1))
    return path, plan


def snapshot(path):
    return {str(item.relative_to(path)): hashlib.sha256(item.read_bytes()).hexdigest()
            for item in Path(path).rglob("*") if item.is_file()}


def execute(source):
    path, plan = source
    return audit.audit_snapshot(plan, path, MANIFEST, PROFILE, calendar=CALENDAR)


def test_full_raw_audit_proves_source_unchanged_and_preserves_real_empty_gap(source, tmp_path):
    path, plan = source
    before = snapshot(path)
    report = execute(source)
    assert snapshot(path) == before
    assert report["status"] == "AUDIT_VERIFIED_WITH_GAPS"
    assert report["source_unchanged_verified"] and report["all_source_pages_revalidated"]
    assert report["source_index_pre_sha256"] == report["source_index_post_sha256"]
    assert report["source_pages_pre_inventory_sha256"] == report["source_pages_post_inventory_sha256"]
    assert report["coverage"]["task_states"] == {"COMPLETE": 1, "EMPTY": 1}
    assert report["coverage"]["accepted_unique_minutes"] == 2 and report["coverage"]["missing_minutes"] == 2
    assert report["task_audits"][1]["missing_ranges"][0]["minute_count"] == 2
    assert not report["production_admission_verified"] and not report["sdk_used"] and report["requests"] == 0
    saved = audit.save_receipt(report, tmp_path / "isolated-evidence")
    receipt = Path(saved["receipt_path"])
    assert hashlib.sha256(receipt.read_bytes()).hexdigest() == saved["receipt_sha256"]
    assert saved["receipt_sha256"] in receipt.name
    assert snapshot(path) == before
    with pytest.raises(ValueError, match="OUTSIDE_SOURCE"):
        audit.save_receipt(report, path / "forbidden-output")


def test_false_index_complete_flag_never_overrides_revalidated_raw(source):
    path, plan = source
    index_path = path / "coverage-index.json"
    index = json.loads(index_path.read_bytes())
    entry = index["tasks"][plan["tasks"][1]["task_id"]]
    entry["coverage"].update(state="COMPLETE", accepted_unique_minutes=2, historical_market_complete=True)
    index_path.write_bytes(rebuild.canonical(index))
    before = snapshot(path)
    report = execute(source)
    assert report["status"] == "AUDIT_PROJECTION_MISMATCH"
    assert report["coverage"]["task_states"]["EMPTY"] == 1
    assert report["projection_mismatches"][0]["kind"] == "INDEX_COVERAGE"
    assert report["source_unchanged_verified"] and snapshot(path) == before


def test_orphan_is_fully_validated_but_original_index_is_never_repaired(source):
    path, plan = source
    index_path = path / "coverage-index.json"
    prior = index_path.read_bytes()
    with rebuild.writer_lock(path):
        store = rebuild.PageStore(path)
        orphan = store.append(plan["tasks"][0], candles(plan["tasks"][0]), AS_OF + timedelta(seconds=2),
                              AS_OF + timedelta(seconds=3))
    index_path.write_bytes(prior)
    before = snapshot(path)
    report = execute(source)
    assert report["status"] == "AUDIT_INDEX_RECOVERY_REQUIRED"
    assert report["orphan_page_sha256"] == [orphan]
    assert report["source_unchanged_verified"] and report["all_source_pages_revalidated"]
    assert len(report["page_audits"]) == 3 and snapshot(path) == before
    assert index_path.read_bytes() == prior


def test_changed_native_page_cannot_pass_existing_hash_filename(source):
    path, plan = source
    page_path = next((path / "pages").glob("*.json"))
    page_path.write_bytes(page_path.read_bytes() + b" ")
    before = snapshot(path)
    report = execute(source)
    assert report["status"] == "AUDIT_BLOCKED_INTEGRITY"
    assert report["integrity_errors"] == ["IMMUTABLE_PAGE_CHANGED"]
    assert report["source_unchanged_verified"] and snapshot(path) == before


def test_stored_page_validation_is_recomputed_instead_of_trusted(source):
    path, plan = source
    index_path = path / "coverage-index.json"
    index = json.loads(index_path.read_bytes())
    task = plan["tasks"][0]
    entry = index["tasks"][task["task_id"]]
    old_sha = entry["pages"][0]
    old_path = path / "pages" / (old_sha + ".json")
    page = json.loads(old_path.read_bytes())
    page["validation"]["accepted_rows"][0]["volume"] = "999999"
    raw = rebuild.canonical(page)
    sha = hashlib.sha256(raw).hexdigest()
    (path / "pages" / (sha + ".json")).write_bytes(raw)
    # Keep the old valid immutable page as an orphan; audit must examine both.
    entry["pages"] = [sha]
    index_path.write_bytes(rebuild.canonical(index))
    before = snapshot(path)
    report = execute(source)
    assert report["status"] == "AUDIT_PROJECTION_MISMATCH"
    assert any(row.get("page_sha256") == sha and row["kind"] == "PAGE_STORED_VALIDATION"
               for row in report["projection_mismatches"])
    assert report["coverage"]["accepted_unique_minutes"] == 2
    assert snapshot(path) == before


def test_active_writer_blocks_audit_without_changing_source(source):
    path, plan = source
    with rebuild.writer_lock(path):
        # Windows byte locks also prevent another handle from reading the
        # locked byte, so snapshot only outside this context.
        with pytest.raises(rebuild.CacheIntegrityError, match="ANOTHER_REBUILD_WRITER_ACTIVE"):
            execute(source)
    assert execute(source)["source_unchanged_verified"]


def test_plan_identity_or_calendar_contract_cannot_be_changed(source):
    path, plan = source
    before = snapshot(path)
    modified = deepcopy(plan)
    modified["tasks"][0]["provider_symbol"] = "GWH.US"
    with pytest.raises(rebuild.CacheIntegrityError, match="AUDIT_PLAN_MANIFEST_CALENDAR_OR_CONTRACT_CHANGED"):
        audit.audit_snapshot(modified, path, MANIFEST, PROFILE, calendar=CALENDAR)
    assert snapshot(path) == before


def test_rogue_source_index_change_during_audit_is_detected(source, monkeypatch):
    path, plan = source
    original = audit.ReadOnlyPageStore._validated_page
    changed = False
    def changed_index(self, sha, page):
        nonlocal changed
        result = original(self, sha, page)
        if not changed:
            index_path = path / "coverage-index.json"
            index_path.write_bytes(index_path.read_bytes() + b" ")
            changed = True
        return result
    monkeypatch.setattr(audit.ReadOnlyPageStore, "_validated_page", changed_index)
    report = execute(source)
    assert report["status"] == "AUDIT_SOURCE_CHANGED" and not report["source_unchanged_verified"]
    assert report["source_index_pre_sha256"] != report["source_index_post_sha256"]


def test_missing_writer_lock_does_not_create_a_source_lock(source):
    path, plan = source
    (path / "writer.lock").unlink()
    before = snapshot(path)
    with pytest.raises(rebuild.CacheIntegrityError, match="SOURCE_WRITER_LOCK_MISSING"):
        execute(source)
    assert snapshot(path) == before


def test_index_provider_identity_metadata_is_bound_back_to_immutable_page(source):
    path, plan = source
    index_path = path / "coverage-index.json"
    index = json.loads(index_path.read_bytes())
    sha = index["tasks"][plan["tasks"][0]["task_id"]]["pages"][0]
    index["page_metadata"][sha]["provider_symbol"] = "GWH.US"
    index_path.write_bytes(rebuild.canonical(index))
    before = snapshot(path)
    report = execute(source)
    assert report["status"] == "AUDIT_PROJECTION_MISMATCH"
    assert any(row["kind"] == "INDEX_PAGE_PROVIDER_METADATA" for row in report["projection_mismatches"])
    assert report["coverage"]["accepted_unique_minutes"] == 2
    assert report["source_unchanged_verified"] and snapshot(path) == before


def test_quota_and_access_decisions_cannot_be_backed_by_a_successful_quote_page(source):
    path, plan = source
    index_path = path / "coverage-index.json"
    index = json.loads(index_path.read_bytes())
    sha = index["tasks"][plan["tasks"][0]["task_id"]]["pages"][0]
    index["quota_blocks"] = [{"page_sha256": sha, "provider_scope_sha256": None, "months": ["2026-10", "2026-10"]}]
    index["access_blocks"] = [{"page_sha256": sha, "provider_scope_sha256": None,
                               "provider_symbol": "NVDA.US", "month_utc": "2026-10"}]
    index_path.write_bytes(rebuild.canonical(index))
    before = snapshot(path)
    report = execute(source)
    assert report["status"] == "AUDIT_PROJECTION_MISMATCH"
    kinds = {row["kind"] for row in report["projection_mismatches"]}
    assert {"INDEX_MONTHLY_QUOTA_PROOF", "INDEX_SYMBOL_ACCESS_PROOF"} <= kinds
    assert snapshot(path) == before
