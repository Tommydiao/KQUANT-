"""Offline immutable-source and eligibility-boundary audit tests; no SDK/API."""
import copy
import csv
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

import audit_watchlist_quote_facts as audit
import run_watchlist_quote_facts_series as series
from test_watchlist_quote_facts_series import fixture_report


class QuoteAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binding, cls.assets, cls.skipped = series.bindings()
        cls.aapl_path = series.ROOT / "evidence/market-readiness/20261007T085835925763Z-cc0fe6a04019e305342114d9824ca46ad6065aa7122c96c1774d6bca44be2449.json"
        cls.aapl = json.loads(cls.aapl_path.read_bytes())

    def setUp(self):
        area = series.ROOT / "evidence/offline-tests"
        area.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="quote-audit-", dir=area)
        self.temp = Path(self.temporary.name).resolve()
        self.assertTrue(self.temp.is_relative_to(area.resolve()))
        self.directory = self.temp / "series"
        self.market_out = self.temp / "market"
        self.market_out.mkdir()

    def tearDown(self):
        self.assertTrue(self.temp.is_relative_to((series.ROOT / "evidence/offline-tests").resolve()))
        self.temporary.cleanup()

    def make_series(self, count=2):
        def invoke(asset, guarded, heartbeat):
            guarded(999999)
            report = fixture_report(asset, self.binding)
            report["timestamp_profile"]["naive_timezone"] = "Asia/Shanghai"
            for index, observation in enumerate(report["observations"]):
                requested = datetime(2026, 10, 7, 8, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=index)
                observation.update(source_kind="SDK_OBJECT_FIELDS_NOT_WIRE_RESPONSE",
                    requested_at=requested.isoformat(), received_at=(requested + timedelta(milliseconds=100)).isoformat())
            raw = series.canonical(report); sha = series.sha(raw)
            path = self.market_out / f"20261007T000000000000Z-{sha}.json"
            path.write_bytes(raw)
            return {"transport_status": "CHILD_RETURNED", "child_tree_termination_verified": True,
                "summary": {"receipt_path": str(path), "receipt_sha256": sha, "requests": 5}}
        series.execute_series(self.directory, self.binding, self.assets, self.skipped,
            max_symbols=count, max_seconds=1200, invoke=invoke, market_out=self.market_out,
            env_loader=lambda: {"longbridge_credentials_configured": True}, emit=lambda value: None)

    def test_genuine_aapl_native_chain_identity_and_timestamps_offline(self):
        result = audit.inspect_report(self.aapl, self.assets[0], self.binding)
        self.assertEqual(result["known_requests"], 11)
        self.assertTrue(result["native_quote_scope_verified"])
        self.assertEqual(result["native_timestamp_values_revalidated"], 4)
        self.assertEqual(len(result["contracts"]), 2)
        self.assertTrue(all(item["native_standard_chain_flag_verified"] and item["native_basic_identity_matches"] for item in result["contracts"]))
        self.assertTrue(all(item["calendar_dte"] == 5 and not item["standard_deliverable_qualified"] and not item["bbo_freshness_proven"] for item in result["contracts"]))

    def test_native_naive_adapter_tamper_rejected(self):
        report = copy.deepcopy(self.aapl)
        report["observations"][3]["rows"][0]["timestamp"]["utc"] = "2026-10-07T04:00:01+00:00"
        with self.assertRaisesRegex(audit.AuditError, "UTC_ADAPTER_MISMATCH"):
            audit.inspect_report(report, self.assets[0], self.binding)

    def test_native_standard_false_cannot_be_accepted(self):
        report = copy.deepcopy(self.aapl)
        report["observations"][5]["selected_native_chain_rows"][0]["standard"]["raw"] = False
        with self.assertRaisesRegex(audit.AuditError, "NATIVE_STANDARD_CHAIN"):
            audit.inspect_report(report, self.assets[0], self.binding)

    def test_depth_cannot_borrow_event_time_from_latest_price(self):
        report = copy.deepcopy(self.aapl)
        report["observations"][8]["native_depth_event_timestamp_available"] = True
        with self.assertRaisesRegex(audit.AuditError, "DEPTH_SCOPE_OR_EVENT_TIME"):
            audit.inspect_report(report, self.assets[0], self.binding)

    def test_unknown_request_code_rejected(self):
        report = copy.deepcopy(self.aapl)
        report["observations"][2]["request_symbols"].append("UNCONFIRMED.US")
        with self.assertRaisesRegex(audit.AuditError, "UNRETAINED_OR_UNBOUND"):
            audit.inspect_report(report, self.assets[0], self.binding)

    def test_request_limit_and_production_promotion_rejected(self):
        report = copy.deepcopy(self.aapl)
        report["requests"] = 12
        with self.assertRaises(audit.AuditError):
            audit.inspect_report(report, self.assets[0], self.binding)
        report = copy.deepcopy(self.aapl); report["owner_acceptance_created"] = True
        with self.assertRaises(audit.AuditError):
            audit.inspect_report(report, self.assets[0], self.binding)

    def test_partial_source_hashes_unchanged_and_csv_all111_not_eligible(self):
        self.make_series()
        before = {path: path.read_bytes() for path in self.directory.rglob("*") if path.is_file()}
        result = audit.audit_snapshot(self.directory, market_out=self.market_out)
        self.assertEqual(result["audit_mode"], "PARTIAL")
        self.assertEqual(result["terminal_attempts"], 2)
        self.assertEqual(result["provider_asset_request_evidence_count"], 2)
        self.assertEqual(result["known_requests"], 10)
        self.assertEqual(result["maximum_possible_requests_reserved"], 22)
        self.assertTrue(result["snapshot_all_source_hashes_unchanged"])
        self.assertEqual(result["source_pre_inventory_sha256"], result["source_post_inventory_sha256"])
        self.assertEqual(result["eligible_assets_proven"], 0)
        self.assertFalse(result["per_asset_native_job_active_count_receipts_available"])
        records = list(csv.DictReader(io.StringIO(audit.csv_bytes(result).decode("utf-8-sig"))))
        self.assertEqual(len(records), 111)
        self.assertEqual(sum(row["attempt_state"] == "IDENTITY_UNCONFIRMED_NO_QUERY" for row in records), 11)
        self.assertTrue(all(row["eligible"] == "False" for row in records))
        self.assertEqual(before, {path: path.read_bytes() for path in self.directory.rglob("*") if path.is_file()})

    def test_final_incomplete_rejected_without_changing_lock(self):
        self.make_series()
        lock_before = (self.directory / "controller.lock").read_bytes()
        with self.assertRaisesRegex(audit.AuditError, "FINAL_REQUIRES_100"):
            audit.audit_snapshot(self.directory, final=True, market_out=self.market_out)
        self.assertEqual(lock_before, (self.directory / "controller.lock").read_bytes())

    def test_final_100_exact_scope_explicit_receipt_closure_and_no_eligibility(self):
        self.make_series(count=100)
        result = audit.audit_snapshot(self.directory, final=True, market_out=self.market_out)
        self.assertEqual(result["status"], "FINAL_SOURCE_FACTS_AUDITED_NOT_ELIGIBILITY")
        self.assertEqual(result["terminal_attempts"], 100)
        self.assertEqual(result["provider_asset_request_evidence_count"], 100)
        self.assertEqual(result["known_requests"], 500)
        self.assertEqual(result["maximum_possible_requests_reserved"], 1100)
        self.assertTrue(result["controller_lock_acquired_readonly"])
        self.assertTrue(result["snapshot_all_source_hashes_unchanged"])
        self.assertEqual(len(result["receipt_files"]), 100)
        self.assertEqual(len(result["attempt_receipt_files"]), 100)
        self.assertTrue(all(not Path(ref["path"]).is_absolute() and "\\" not in ref["path"] for ref in result["receipt_files"]))
        self.assertEqual(result["assets_without_original_probe_receipt"], [])
        self.assertEqual(result["eligible_assets_proven"], 0)
        self.assertFalse(result["clock_precision_verified"])

    def test_final_controller_active_rejected(self):
        self.make_series()
        with series.series_lock(self.directory):
            with self.assertRaisesRegex(audit.AuditError, "CONTROLLER_STILL_ACTIVE"):
                audit.audit_snapshot(self.directory, final=True, market_out=self.market_out)

    def test_raw_receipt_tamper_rejected(self):
        self.make_series()
        path = next(self.market_out.glob("*.json"))
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(audit.AuditError, "REFERENCE_HASH_MISMATCH"):
            audit.audit_snapshot(self.directory, market_out=self.market_out)

    def test_attempt_projection_tamper_rejected_after_rehash(self):
        self.make_series()
        checkpoint = self.directory / "checkpoint.json"
        state = json.loads(checkpoint.read_bytes())
        original = Path(state["results"]["AAPL"]["path"])
        result = json.loads(original.read_bytes())
        result["facts"]["native_underlying_response_scope_verified"] = False
        raw = series.canonical(result); sha = series.sha(raw)
        path = original.parent / f"asset-AAPL-{sha}.json"; path.write_bytes(raw)
        state["results"]["AAPL"] = {"path": str(path), "sha256": sha}
        checkpoint.write_bytes(series.canonical(state))
        with self.assertRaisesRegex(audit.AuditError, "PROJECTION_MISMATCH"):
            audit.audit_snapshot(self.directory, market_out=self.market_out)

    def test_output_cannot_write_into_series_or_workspace(self):
        self.make_series()
        result = audit.audit_snapshot(self.directory, market_out=self.market_out)
        with self.assertRaises(audit.AuditError):
            audit.write_outputs(result, self.directory)
        with self.assertRaises(audit.AuditError):
            audit.write_outputs(result, series.ROOT / "development/workspace")


if __name__ == "__main__":
    unittest.main()
