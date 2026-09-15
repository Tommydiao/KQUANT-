"""Standard-library-only T20 tests and bounded synthetic evidence delivery.

Run this file with --deliver in the isolated interpreter to save preregistered
synthetic geometry, actual test logs, deterministic common paths, and hashes.
No real market window is opened by this harness.
"""
from dataclasses import asdict, replace
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_mc_paths_v12 import (  # noqa: E402
    DevPathSpec, PathInputError, SYMBOLS, audit_history, bind_alternatives,
    digest, generate_paths, seal_risk_snapshot,
)


def fixture():
    as_of, count = 20000 * 86400 + 86100, 289
    start = as_of - count * 300
    history = []
    previous = {s: p for s, p in zip(SYMBOLS, (60000., 3000., 150.))}
    for i in range(count):
        bars = {}
        for symbol in SYMBOLS:
            opening = previous[symbol] * (1 + (i % 7 - 3) * .0002)
            close = opening * (1 + (i % 5 - 2) * .0003)
            bars[symbol] = {"start": start + i * 300, "available_at": start + (i + 1) * 300,
                            "source_bar_id": f"synthetic:{symbol}:{i}", "open": opening,
                            "high": max(opening, close) * 1.001, "low": min(opening, close) * .999,
                            "close": close}
            previous[symbol] = close
        history.append({"start": start + i * 300, "bars": bars})
    spec = DevPathSpec(start, as_of, as_of, 12, 72, 32, 20260906, 289, 6912,
                       digest({"fixture": "synchronized_geometry_v1", "history": history}), "SYNTHETIC_DEV")
    anchors = dict(zip(SYMBOLS, (61000., 3100., 155.)))
    snapshot = {"portfolio_version": "fixture-v1", "as_of": as_of, "cash": 9000., "reserved_cash": 100.,
        "available_cash": 8900., "positions": {"position-A": {"symbol": "BTCUSDT", "quantity": .015,
            "risk_amount": 20., "liquidation_value": 910., "expires_at": as_of + 600}},
        "pending_entry_intents": {"intent-B": {"symbol": "ETHUSDT", "quantity": .02, "risk_amount": 10.,
            "reserved_cash": 100., "expires_at": as_of + 1800}},
        "pending_exit_intents": {"exit-A": {"position_id": "position-A", "reason": "mode_invalidated"}},
        "protective_prices": {"position-A": {"stop": 59000., "target": 64000.},
                              "intent-B": {"stop": 2900., "target": 3300.}},
        "remaining_holding_time": {"position-A": 600, "intent-B": 1800},
        "current_liquidation_equity": 9910., "mark_prices": anchors,
        "mark_quality_by_symbol": {s: "synthetic_owner_supplied_liquidation_fixture" for s in SYMBOLS},
        "risk_day_id": as_of // 86400, "day_start_equity": 10000., "day_baseline_status": "ESTABLISHED",
        "historical_high_watermark": 10050., "remaining_daily_loss_budget": 10.,
        "remaining_position_risk_budget": 25., "loss_streak": 2, "cooldown_until": as_of + 1200,
        "cost_policy_id": "BASE_10_5_FIXTURE", "execution_policy_id": "OHLCV_PROXY_FIXTURE",
        "daily_loss_limit": .01, "owner_valuation_note": "Liquidation values are explicit synthetic scalars, not market valuation."}
    proposal = {"intent_id": "new-C", "symbol": "SOLUSDT", "quantity": 1., "risk_amount": 5.,
                "reserved_cash": 156., "stop": 150., "target": 170., "expires_at": as_of + 21600}
    return history, anchors, spec, snapshot, proposal


class MCPathTests(unittest.TestCase):
    def setUp(self):
        self.history, self.anchors, self.spec, self.snapshot, self.proposal = fixture()
        self.small = replace(self.spec, paths=2)

    def test_same_seed_identical_and_different_seed_changes_indices(self):
        first = generate_paths(self.history, self.anchors, self.small)
        self.assertEqual(first, generate_paths(self.history, self.anchors, self.small))
        other = generate_paths(self.history, self.anchors, replace(self.small, seed=18))
        self.assertNotEqual(first["path_bank"]["paths"][0]["block_starts"], other["path_bank"]["paths"][0]["block_starts"])

    def test_three_symbols_share_source_indices_and_relative_geometry(self):
        bank = generate_paths(self.history, self.anchors, self.small)["path_bank"]
        for path in bank["paths"]:
            previous = dict(self.anchors)
            for step, batch in enumerate(path["batches"]):
                self.assertEqual(batch["start"], self.spec.as_of + step * 300)
                ratios = []
                for symbol in SYMBOLS:
                    bar = batch["bars"][symbol]
                    source = self.history[batch["source_index"]]["bars"][symbol]
                    self.assertEqual(bar["source_bar_id"], source["source_bar_id"])
                    self.assertGreaterEqual(bar["high"], max(bar["open"], bar["close"]))
                    self.assertLessEqual(bar["low"], min(bar["open"], bar["close"]))
                    self.assertAlmostEqual(bar["high"] / bar["open"], source["high"] / source["open"])
                    self.assertAlmostEqual(bar["open"] / previous[symbol], bar["open_previous_close_ratio"])
                    ratios.append(bar["close"] / previous[symbol])
                    previous[symbol] = bar["close"]
                self.assertAlmostEqual(ratios[0], ratios[1])
                self.assertAlmostEqual(ratios[1], ratios[2])

    def test_seams_preserve_source_predecessor_and_future_day_clock(self):
        path = generate_paths(self.history, self.anchors, self.small)["path_bank"]["paths"][0]
        self.assertEqual(path["batches"][1]["start"] % 86400, 0)
        for step, batch in enumerate(path["batches"]):
            self.assertEqual(batch["block_seam"], step % 12 == 0)
            self.assertEqual(batch["source_predecessor_index"], batch["source_index"] - 1)
            self.assertLess(batch["source_start"], self.spec.as_of)
            if step % 12:
                self.assertEqual(batch["source_index"], path["batches"][step - 1]["source_index"] + 1)

    def test_gaps_duplicates_order_and_cross_symbol_missing_fail_with_audit(self):
        for mutate in (lambda h: h[3].update(start=h[2]["start"]),
                       lambda h: h[3]["bars"].pop("ETHUSDT"),
                       lambda h: h[3]["bars"]["BTCUSDT"].update(start=h[2]["start"])):
            history = copy.deepcopy(self.history)
            mutate(history)
            with self.assertRaises(PathInputError) as error:
                audit_history(history, self.spec)
            self.assertTrue(error.exception.audit["rejected"])

    def test_nonfinite_and_illegal_ohlc_never_repaired(self):
        for field, value in (("open", 0), ("high", float("inf")), ("low", float("nan")), ("high", 1.)):
            history = copy.deepcopy(self.history)
            history[5]["bars"]["BTCUSDT"][field] = value
            with self.assertRaises(PathInputError):
                generate_paths(history, self.anchors, self.small)

    def test_future_availability_and_unclosed_bars_refused(self):
        for stamp in (self.spec.as_of + 1, self.history[3]["start"]):
            history = copy.deepcopy(self.history)
            history[3]["bars"]["SOLUSDT"]["available_at"] = stamp
            with self.assertRaisesRegex(PathInputError, "PRE_CUTOFF"):
                audit_history(history, self.spec)
        with self.assertRaisesRegex(PathInputError, "PRE_CUTOFF"):
            replace(self.spec, history_end=self.spec.as_of + 300)

    def test_missing_source_and_resource_bounds_refused(self):
        self.history[1]["bars"]["BTCUSDT"]["source_bar_id"] = ""
        with self.assertRaisesRegex(PathInputError, "SOURCE_ID"):
            audit_history(self.history, self.spec)
        with self.assertRaisesRegex(PathInputError, "OUTPUT_BUDGET"):
            replace(self.spec, paths=5000)
        with self.assertRaisesRegex(PathInputError, "SOURCE_KIND"):
            replace(self.spec, source_kind="HELDOUT")

    def test_snapshots_preserve_pending_and_do_not_double_debit(self):
        frozen = seal_risk_snapshot(self.snapshot)
        self.assertEqual(frozen["snapshot"], self.snapshot)
        self.assertEqual(frozen["snapshot"]["current_liquidation_equity"], 9910)
        self.assertEqual(frozen["existing_risk_amount"], 20)
        self.assertEqual(frozen["pending_risk_amount"], 10)
        self.snapshot["positions"].clear()
        self.assertEqual(len(frozen["snapshot"]["positions"]), 1)

    def test_cash_day_budget_and_pending_exit_failures(self):
        for field, value in (("available_cash", 9000), ("current_liquidation_equity", 9810),
                             ("remaining_daily_loss_budget", 99.1), ("risk_day_id", 0)):
            snapshot = copy.deepcopy(self.snapshot)
            snapshot[field] = value
            with self.assertRaises(PathInputError):
                seal_risk_snapshot(snapshot)
        self.snapshot["pending_exit_intents"]["exit-A"]["position_id"] = "absent"
        with self.assertRaisesRegex(PathInputError, "ORPHAN"):
            seal_risk_snapshot(self.snapshot)

    def test_pending_day_baseline_is_preserved_not_reset(self):
        self.snapshot.update(day_baseline_status="DAY_BASELINE_PENDING", day_start_equity=None,
                             remaining_daily_loss_budget=None)
        sealed = seal_risk_snapshot(self.snapshot)
        self.assertIsNone(sealed["snapshot"]["remaining_daily_loss_budget"])
        self.assertTrue(sealed["snapshot"]["pending_exit_intents"])

    def test_common_paths_across_alternatives_zero_retains_all_existing_risk(self):
        paths = generate_paths(self.history, self.anchors, self.small)
        before = copy.deepcopy(self.snapshot)
        result = bind_alternatives(paths, self.snapshot, self.proposal, [1., .5, 0.])
        self.assertEqual(result["risk_snapshot"]["snapshot"], before)
        self.assertEqual(self.snapshot, before)
        self.assertEqual(len({a["path_bank_hash"] for a in result["alternatives"]}), 1)
        self.assertIsNone(result["alternatives"][-1]["proposed_entry"])
        self.assertEqual(result["alternatives"][1]["proposed_entry"]["quantity"], .5)
        self.assertTrue(all(a["admission"] == "ABSTAIN" and not a["selected"] for a in result["alternatives"]))
        self.assertEqual(result["remaining_daily_loss_budget"], 10)
        self.assertFalse(result["sizing_enabled"])

    def test_hash_binding_invalidates_risk_changes_and_tampered_paths(self):
        a = seal_risk_snapshot(self.snapshot)["portfolio_snapshot_hash"]
        self.snapshot["cost_policy_id"] = "other"
        self.assertNotEqual(a, seal_risk_snapshot(self.snapshot)["portfolio_snapshot_hash"])
        self.snapshot["portfolio_snapshot_hash"] = a
        with self.assertRaisesRegex(PathInputError, "HASH_MISMATCH"):
            seal_risk_snapshot(self.snapshot)
        self.snapshot.pop("portfolio_snapshot_hash")
        bank = generate_paths(self.history, self.anchors, self.small)
        bank["path_bank"]["paths"][0]["batches"][0]["bars"]["BTCUSDT"]["close"] = 1
        with self.assertRaisesRegex(PathInputError, "PATH_BANK_HASH"):
            bind_alternatives(bank, self.snapshot, self.proposal, [0])

    def test_horizon_and_snapshot_clock_binding(self):
        bank = generate_paths(self.history, self.anchors, replace(self.small, horizon_bars=1))
        with self.assertRaisesRegex(PathInputError, "HORIZON"):
            bind_alternatives(bank, self.snapshot, self.proposal, [0])
        bank = generate_paths(self.history, self.anchors, self.small)
        self.snapshot["mark_prices"]["BTCUSDT"] += 1
        with self.assertRaisesRegex(PathInputError, "ANCHOR"):
            bind_alternatives(bank, self.snapshot, self.proposal, [0])

    def test_no_news_strategy_fields_or_activation_carried_to_future(self):
        self.history[4]["news"] = "known-historical-event"
        bank = generate_paths(self.history, self.anchors, self.small)["path_bank"]
        self.assertNotIn("known-historical-event", json.dumps(bank))
        self.assertFalse(bank["recursive_entries"])
        self.assertFalse(bank["recursive_news"])
        self.assertEqual(bank["execution_quality"], "proxy")
        self.assertIsNone(bank["risk_probabilities"])


def deliver():
    out = ROOT / "outputs/hybrid_delivery/mc_paths_20260906"
    expected = ROOT / "work/hybrid_dev_fit_fast_env/Scripts/python.exe"
    if Path(sys.executable).resolve() != expected.resolve():
        raise ValueError("Use existing isolated interpreter for artifact delivery")
    out.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    history, anchors, spec, snapshot, proposal = fixture()

    def save(name, value):
        with (out / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")

    def file_sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    save("preregistration.json", {"scope": "DEV_ONLY_SYNTHETIC_ENGINEERING", "spec": asdict(spec),
         "parameters_are_production_gate": False, "multipliers": [1., .5, 0.],
         "real_market_rows_read": False, "market_loader_implemented": False,
         "as_of_is_synthetic": True, "repeated_sampling_until_pass": False,
         "history_hash": digest(history), "risk_snapshot_hash": seal_risk_snapshot(snapshot)["portfolio_snapshot_hash"],
         "command": [sys.executable, "-B", *sys.argv], "cwd": str(Path.cwd()),
         "registered_raw_host_utc": datetime.now(timezone.utc).isoformat(),
         "source_hashes": {str(p.relative_to(ROOT)): file_sha(p) for p in (
             ROOT / "kquant_crypto/hybrid_mc_paths_v12.py", Path(__file__))}})
    log = io.StringIO()
    tests = unittest.TextTestRunner(stream=log, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(MCPathTests))
    with (out / "tests.log").open("x", encoding="utf-8") as stream:
        stream.write(log.getvalue())
    save("tests_result.json", {"tests_run": tests.testsRun, "failures": len(tests.failures),
         "errors": len(tests.errors), "skipped": len(tests.skipped), "exit_code": 0 if tests.wasSuccessful() else 1})
    if not tests.wasSuccessful():
        raise RuntimeError("Bounded tests failed; evidence retained")
    paths = generate_paths(history, anchors, spec)
    again = generate_paths(history, anchors, spec)
    assert paths == again
    bindings = bind_alternatives(paths, snapshot, proposal, [1., .5, 0.])
    save("synthetic_inputs.json", {"history": history, "anchors": anchors, "snapshot": snapshot, "proposal": proposal})
    save("paths.json", paths)
    save("risk_bindings.json", bindings)
    tasks = json.loads((ROOT / "plan/hybrid_to_live_tasks.v1_2.json").read_text(encoding="utf-8"))["tasks"]
    task = next(t for t in tasks if t["id"] == "T20")
    save("acceptance.json", {"task": "T20", "scope": "ENGINEERING_INPUTS_ONLY", "criteria": [
        {"requirement": text, "coverage": "VERIFIED_SYNTHETIC_ENGINEERING"} for text in task["acceptance"]],
        "remaining": ["Bounded authorized real-history loader/manifest qualification not implemented or exercised.",
            "Protected-owner path execution including current and pending fills/exits and UTC baselines remains downstream.",
            "No loss probabilities, current-state conditioning, stress likelihood, VaR/ES, numerical admission or sizing activation.",
            "5000-path performance and seed/block/window sensitivity are not established by this 32-path smoke delivery."],
        "G4": "NOT_PASSED", "parent_task_state_modified": False})
    report = """# T20 MC Paths - 2026-09-06

Implemented synchronized three-symbol OHLC block reconstruction and frozen risk-input binding.
DEV_ONLY synthetic engineering; ABSTAIN. No model fit, market scan, production import, sizing or execution activation.

## Actual Bounded Evidence
- 289 synchronized input batches, including one predecessor-close batch; 277 eligible 12-bar starts.
- 32 paths x 72 future 5m bars (6h), shared across multipliers 1, 0.5, 0. Seed 20260906.
- Repeated generation matches exactly. Original source indices, timestamps, IDs and block seams are retained.
- Whole-window gap/missing/nonfinite/pre-cutoff rejection; no repairs, drop-and-stitch or per-symbol shuffling.
- Risk snapshot retains current position, pending entry, pending exit, protection, expiry, reservations, cooldown and historical HWM.
- Cash 9000, reserved 100, available 8900; liquidation equity 9910; daily-loss budget remains 10, not reset to 99.1.
- m=0 removes only the proposal; current/pending risk is retained and no new entry is approved.
- Future times cross UTC midnight, but this input component never resets day baselines or executes protection.

## Boundary And Remaining Work
T20 acceptance is covered at the synthetic path/input layer (acceptance.json); no real-market qualification is claimed.
No bounded authorized real-history loader was established, so no history files or heldout intervals were opened.
OHLC is an execution proxy: extrema are not simultaneous bids and block seams lose serial dependence.
Existing candidate protected semantics were read but not imported or duplicated; no third stop implementation was introduced.
Downstream owner must replay preserved current/pending risk with compatible protected semantics and frozen cost policy.
Risk probabilities, numerical error bounds, daily/HWM breach evaluation, 5000-path performance and sensitivity remain unverified.
All history/block/window/resource parameters here are explicit DEV preregistration, never a production gate. G4 NOT PASSED.

preregistration.json contains the command and source hashes; tests.log/tests_result.json contain actual test evidence.
paths.json and risk_bindings.json share the immutable path-bank hash. manifest.json binds the outputs.
Parent owns task state, subsequent execution integration and scheduling.
"""
    with (out / "report.md").open("x", encoding="utf-8") as stream:
        stream.write(report)
    save("manifest.json", {"exit_code": 0, "elapsed_seconds": time.perf_counter() - started,
         "output_hashes": {p.name: file_sha(p) for p in out.iterdir() if p.is_file()},
         "plan_sha256": file_sha(ROOT / "docs/KQUANT_Crypto_Hybrid_PLAN_V1.1.md"),
         "task_contract_sha256": file_sha(ROOT / "plan/hybrid_to_live_tasks.v1_2.json"),
         "python": sys.version, "executable": sys.executable, "executable_sha256": file_sha(sys.executable),
         "environment_modified": False, "test_success": True, "deterministic_repeat_match": True})
    print(log.getvalue())
    print(f"Saved bounded MC engineering evidence: {out}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--deliver"]:
        deliver()
    else:
        unittest.main()
