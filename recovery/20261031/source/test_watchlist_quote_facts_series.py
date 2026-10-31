"""Offline scope, ledger, classifier, and harmless owned-process tests."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import run_watchlist_quote_facts_series as series


def native(raw):
    return {"raw": raw, "native_type": "OFFLINE_FIXTURE"}


def fixture_report(asset, binding, *, error=None):
    observations = [
        {"interface": "QuoteContext.trading_session", "state": "RETURNED", "rows": []},
        {"interface": "QuoteContext.trading_days", "state": "RETURNED"},
        {"interface": "QuoteContext.static_info", "state": "RETURNED", "rows": [{
            "symbol": native(asset["provider_symbol"]), "currency": native("USD"), "lot_size": native("1")}]},
        {"interface": "QuoteContext.quote", "state": "RETURNED", "rows": [{
            "symbol": native(asset["provider_symbol"]), "trade_status": native("TradeStatus.Normal"),
            "last_done": native("100"), "prev_close": native("99")}]},
        {"interface": "QuoteContext.option_chain_expiry_date_list", "state": "RETURNED", "expiry_dates": []},
    ]
    if error:
        observations[-1].update(state="PROVIDER_ERROR", error={"error_category": error,
            "provider_error_code": 401003 if error == "TOKEN_EXPIRED" else 301604,
            "provider_error_kind": "OpenApi", "error_type": "SECRET_TYPE_NOT_ALLOWED",
            "message": "RAW_SECRET_MUST_NOT_ESCAPE"})
    for observation in observations[2:]:
        observation["request_symbols"] = [asset["provider_symbol"]]
    return {"mode": "quote-facts", "status": "BLOCKED_" + error if error in series.GLOBAL_ERRORS else
            "FACTS_CAPTURED_WITH_PROVIDER_ERRORS" if error else "FACTS_CAPTURED",
            "requests": 5, "scope": {**asset, "manifest_sha256": binding["manifest_canonical_sha256"]},
            "timestamp_profile": {"name": "VERIFIED_SDK_NAIVE_ASIA_SHANGHAI", "evidence_sha256": binding["timestamp_evidence_sha256"]},
            "observations": observations, "market_date": "2026-10-07",
            "contract_discovery": {"state": "NO_MATCHING_RETURNED_CALENDAR_DTE", "selected_contracts": []},
            "provider_scope_kind": "APP_KEY_SHA256", "provider_scope_sha256": "a" * 64,
            **{name: False for name in series.FALSE_FLAGS}}


class SeriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binding, cls.assets, cls.skipped = series.bindings()
        cls.manifest = json.loads(series.MANIFEST.read_bytes())

    def setUp(self):
        base = series.ROOT / "evidence/offline-tests"
        base.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="watchlist-series-", dir=base)
        self.temp = Path(self.temporary.name).resolve()
        self.assertTrue(self.temp.is_relative_to(base.resolve()))
        self.market_out = self.temp / "market"
        self.market_out.mkdir()
        self.directory = self.temp / "series"
        self.calls = []

    def tearDown(self):
        # Verify the recursive cleanup target remains inside the named test area.
        self.assertTrue(self.temp.is_relative_to((series.ROOT / "evidence/offline-tests").resolve()))
        self.temporary.cleanup()

    def write_receipt(self, report):
        data = series.canonical(report); digest = series.sha(data)
        path = self.market_out / f"20261007T000000000000Z-{digest}.json"
        with path.open("xb") as handle:
            handle.write(data)
        return {"receipt_path": str(path), "receipt_sha256": digest, "requests": report.get("requests")}

    def invoke(self, asset, guarded, heartbeat):
        self.calls.append(asset["symbol"])
        guarded(424242)
        summary = self.write_receipt(fixture_report(asset, self.binding))
        return {"transport_status": "CHILD_RETURNED", "summary": summary, "child_tree_termination_verified": True}

    def run_series(self, **kwargs):
        defaults = {"max_symbols": 2, "max_seconds": 1200, "invoke": self.invoke,
                    "env_loader": lambda: {"longbridge_credentials_configured": True},
                    "emit": lambda value: None, "market_out": self.market_out}
        defaults.update(kwargs)
        return series.execute_series(self.directory, self.binding, self.assets, self.skipped, **defaults)

    def test_actual_scope_is_exact_100_and_unknown_11_never_queried(self):
        self.assertEqual((len(self.assets), len(self.skipped)), (100, 11))
        self.assertEqual(len({row["provider_symbol"] for row in self.assets}), 100)
        self.assertTrue(all(row["state"] == "SKIPPED_NO_QUERY" and row["provider_symbol"] is None for row in self.skipped))
        self.assertIn("run_watchlist_quote_facts_series.py", self.binding["original_source_sha256"])

    def test_duplicate_identity_is_rejected(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["items"][-1]["symbol"] = manifest["items"][0]["symbol"]
        with self.assertRaises(series.IntegrityError):
            series.retained_scope(manifest)

    def test_dry_plan_never_invokes_loader_or_child(self):
        with patch.object(sys, "argv", ["series", "--dry-plan", "--max-symbols", "2"]), \
                patch.object(series, "load_private_env") as loader, patch.object(series, "invoke_probe") as child, \
                patch.object(sys, "stdout", new_callable=io.StringIO) as output:
            self.assertEqual(series.main(), 0)
            report = json.loads(output.getvalue())
        loader.assert_not_called(); child.assert_not_called()
        self.assertEqual(report["requests"], 0)
        self.assertFalse(report["env_file_read"])

    def test_fact_capture_without_chain_is_not_eligible(self):
        facts = series.summarize_report(fixture_report(self.assets[0], self.binding), self.assets[0], self.binding)
        self.assertFalse(facts["eligible"])
        self.assertEqual(facts["discovery_state"], "NO_MATCHING_RETURNED_CALENDAR_DTE")
        self.assertIn("NO_MATCHING_NATIVE_3_TO_7_DAY_CONTRACT", facts["blocking_gates"])

    def test_global_calendar_call_only_does_not_prove_asset_visited(self):
        report = fixture_report(self.assets[0], self.binding, error="TOKEN_EXPIRED")
        report["observations"] = [report["observations"][0]]
        report["observations"][0].update(state="PROVIDER_ERROR", error={"error_category": "TOKEN_EXPIRED"})
        report["requests"] = 1
        facts = series.summarize_report(report, self.assets[0], self.binding)
        self.assertFalse(facts["has_provider_request_evidence"])
        self.assertFalse(facts["native_underlying_response_scope_verified"])

    def test_existing_nvda_receipt_parser_is_offline_only_not_series_visit(self):
        path = series.ROOT / "evidence/market-readiness/20261007T080541100598Z-73464aaad1bbf1f4a0cf0defc4cf0071e706500a919d439e157a681df5d4658b.json"
        asset = next(row for row in self.assets if row["symbol"] == "NVDA")
        report = json.loads(path.read_bytes())
        facts = series.summarize_report(report, asset, self.binding)
        self.assertEqual(facts["known_requests"], 11)
        self.assertTrue(facts["native_underlying_response_scope_verified"])
        self.assertEqual(len(facts["native_contracts"]), 2)
        self.assertTrue(all(row["native_basic_identity_matches"] for row in facts["native_contracts"]))
        self.assertFalse(facts["eligible"])
        self.assertFalse(self.calls)
        self.assertFalse(self.directory.exists())

    def test_auth_stops_whole_series_and_drops_arbitrary_error_text(self):
        def invoke(asset, guarded, heartbeat):
            self.calls.append(asset["symbol"]); guarded(424242)
            return {"transport_status": "CHILD_RETURNED", "child_tree_termination_verified": True,
                    "summary": self.write_receipt(fixture_report(asset, self.binding, error="TOKEN_EXPIRED"))}
        totals = self.run_series(invoke=invoke)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(totals["global_stop"], ["TOKEN_EXPIRED"])
        result = json.loads(next((self.directory / "attempts").glob("*.json")).read_bytes())
        self.assertNotIn("RAW_SECRET", json.dumps(result))
        self.assertNotIn("SECRET_TYPE", json.dumps(result))

    def test_asset_permission_failure_does_not_stop_next_asset(self):
        def invoke(asset, guarded, heartbeat):
            self.calls.append(asset["symbol"]); guarded(424242)
            error = "NO_QUOTE_ACCESS" if len(self.calls) == 1 else None
            return {"transport_status": "CHILD_RETURNED", "child_tree_termination_verified": True,
                    "summary": self.write_receipt(fixture_report(asset, self.binding, error=error))}
        totals = self.run_series(invoke=invoke)
        self.assertEqual(len(self.calls), 2)
        self.assertIsNone(totals["global_stop"])
        self.assertEqual(totals["eligible_assets_proven"], 0)

    def test_resume_skips_recorded_assets_and_preserves_reservation_bound(self):
        first = self.run_series(max_symbols=2)
        second = self.run_series(max_symbols=1)
        self.assertEqual(len(set(self.calls)), 3)
        self.assertEqual(second["asset_attempts_terminal"], 3)
        self.assertEqual(second["maximum_possible_requests_reserved"], 33)
        self.assertEqual(first["maximum_possible_requests_reserved"], 22)

    def test_all_100_attempts_are_not_market_eligibility_and_complete_resume_loads_no_env(self):
        totals = self.run_series(max_symbols=100)
        self.assertEqual(len(set(self.calls)), 100)
        self.assertTrue(totals["all_100_provider_requests_observed"])
        self.assertEqual(totals["maximum_possible_requests_reserved"], 1100)
        self.assertEqual(totals["known_requests"], 500)
        self.assertFalse(totals["production_admission_verified"])
        loader, child = Mock(side_effect=AssertionError("must not run")), Mock(side_effect=AssertionError("must not run"))
        resumed = self.run_series(env_loader=loader, invoke=child)
        self.assertEqual(resumed["asset_attempts_terminal"], 100)
        loader.assert_not_called(); child.assert_not_called()

    def test_reusing_preexisting_sample_is_rejected(self):
        summary = self.write_receipt(fixture_report(self.assets[0], self.binding))
        def invoke(asset, guarded, heartbeat):
            guarded(424242)
            return {"transport_status": "CHILD_RETURNED", "child_tree_termination_verified": True, "summary": summary}
        totals = self.run_series(invoke=invoke)
        self.assertEqual(totals["global_stop"], ["CHILD_RECEIPT_INTEGRITY_UNVERIFIED"])
        result = json.loads(next((self.directory / "attempts").glob("*.json")).read_bytes())
        self.assertIsNone(result["probe_receipt"])

    def test_receipt_tamper_is_detected_before_resume_env_load(self):
        self.run_series(max_symbols=1)
        path = next(self.market_out.glob("*.json")); path.write_bytes(path.read_bytes() + b" ")
        loader = Mock()
        with self.assertRaises(series.IntegrityError):
            self.run_series(env_loader=loader)
        loader.assert_not_called()

    def test_controller_binding_change_prevents_resume(self):
        self.run_series(max_symbols=1)
        changed = copy.deepcopy(self.binding)
        changed["original_source_sha256"]["run_watchlist_quote_facts_series.py"] = "0" * 64
        with self.assertRaises(series.IntegrityError):
            series.execute_series(self.directory, changed, self.assets, self.skipped, max_symbols=1,
                                  max_seconds=1200, invoke=self.invoke, market_out=self.market_out)

    def test_source_change_during_segment_stops_before_child(self):
        totals = self.run_series(binding_verifier=lambda: {"changed": True})
        self.assertFalse(self.calls)
        self.assertEqual(totals["global_stop"], ["BOUND_SOURCE_CHANGED_DURING_SEGMENT"])

    def test_contract_outside_calendar_3_to_7_is_rejected(self):
        report = fixture_report(self.assets[0], self.binding)
        report["contract_discovery"] = {"state": "NATIVE_STANDARD_CHAIN_CANDIDATES", "expiry_date": "2026-10-17",
            "selected_contracts": [{"symbol": "AAPL261017C100000.US", "right": "CALL", "strike": "100"}]}
        with self.assertRaises(series.IntegrityError):
            series.summarize_report(report, self.assets[0], self.binding)

    def test_guarded_interrupted_attempt_is_not_requeried(self):
        self.directory.mkdir(); (self.directory / "attempts").mkdir()
        state = {"schema": "KQUANT_WATCHLIST_QUOTES_V1", "binding": self.binding, "assets": self.assets,
            "results": {}, "request_reservations": 11, "global_stop": None, "provider_scope_sha256": None,
            "in_flight": {"asset": self.assets[0], "guard_state": "OWNED_CHILD_TREE_GUARDED", "receipt_files_before": []}}
        series.atomic_json(self.directory / "checkpoint.json", state)
        totals = self.run_series(max_symbols=1)
        self.assertEqual(self.calls, [self.assets[1]["symbol"]])
        self.assertEqual(totals["unknown_outcome_asset_count"], 1)
        self.assertEqual(totals["maximum_possible_requests_reserved"], 22)

    def test_unguarded_interrupted_attempt_fails_closed_without_loader(self):
        self.directory.mkdir(); (self.directory / "attempts").mkdir()
        state = {"schema": "KQUANT_WATCHLIST_QUOTES_V1", "binding": self.binding, "assets": self.assets,
            "results": {}, "request_reservations": 11, "global_stop": None, "provider_scope_sha256": None,
            "in_flight": {"asset": self.assets[0], "guard_state": "RESERVED_BEFORE_CHILD_START", "receipt_files_before": []}}
        series.atomic_json(self.directory / "checkpoint.json", state)
        loader = Mock(side_effect=AssertionError("must not load credentials"))
        totals = self.run_series(env_loader=loader)
        self.assertEqual(totals["global_stop"], ["INTERRUPTED_CHILD_OR_RECEIPT_UNVERIFIED"])
        self.assertFalse(self.calls); loader.assert_not_called()

    def test_owned_guard_failure_prevents_next_identity(self):
        def invoke(asset, guarded, heartbeat):
            self.calls.append(asset["symbol"])
            return {"transport_status": "CHILD_GUARD_OR_TRANSPORT_FAILED", "child_tree_termination_verified": False}
        totals = self.run_series(invoke=invoke)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(totals["global_stop"], ["OWNED_CHILD_TREE_TERMINATION_UNVERIFIED"])
        self.assertEqual(totals["maximum_possible_requests_reserved"], 11)

    def test_assignment_failure_never_releases_bootstrap_sdk_gate(self):
        marker = self.temp / "SDK_START_MARKER"
        harmless = self.temp / "harmless.py"
        harmless.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('started')\nprint('{{}}')\n")
        fake_job = Mock(handle=1)
        fake_job.assign.side_effect = OSError("assignment failed")
        with patch.object(series, "OwnedJob", return_value=fake_job), \
                patch.object(series, "command_for", return_value=[sys.executable, str(harmless)]):
            result = series.invoke_probe(self.assets[0], lambda pid: None, lambda: None)
        self.assertFalse(marker.exists())
        self.assertFalse(result["sdk_start_gate_released"])
        self.assertFalse(result["child_tree_termination_verified"])
        self.assertTrue(result["unassigned_bootstrap_terminated"])
        fake_job.stop_tree.assert_not_called()

    def test_actual_owned_job_terminates_harmless_descendant(self):
        harmless = self.temp / "harmless.py"
        harmless.write_text("import subprocess, sys\n"
                            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                            "print('{\"harmless\":true}')\n")
        guarded = []
        with patch.object(series, "command_for", return_value=[sys.executable, str(harmless)]), \
                patch.object(series, "CHILD_TIMEOUT", 2):
            result = series.invoke_probe(self.assets[0], guarded.append, lambda: None)
        self.assertTrue(guarded)
        self.assertTrue(result["sdk_start_gate_released"])
        self.assertTrue(result["child_tree_termination_verified"])


if __name__ == "__main__":
    unittest.main()
