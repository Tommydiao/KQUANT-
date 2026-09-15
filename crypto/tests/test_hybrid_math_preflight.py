"""Stdlib-only synthetic tests; direct file loading avoids live package imports."""

import copy
import importlib.util
import math
from pathlib import Path
import random
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_offline(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "kquant_crypto" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


m = load_offline("_math_preflight_fixture", "hybrid_math_preflight.py")
c = load_offline("_risklines_offline_contract", "hybrid_contracts.py")


class PriorFixtureTests(unittest.TestCase):
    def spec(self, **changes):
        args = dict(parameters=((1, 2), (-1, 1)), innovations=(-2, 0, 2),
                    draws=12, max_draws=12, seed=20260905)
        args.update(changes)
        return m.PriorPredictiveFixture(**args)

    def test_repeatable_and_does_not_mutate_global_rng(self):
        state = random.getstate()
        a = m.prior_predictive_fixture(self.spec())
        self.assertEqual(a, m.prior_predictive_fixture(self.spec()))
        self.assertEqual(random.getstate(), state)
        self.assertEqual(len(a["predictive_returns"]), 12)
        self.assertEqual(a["source_kind"], m.SOURCE)

    def test_means_are_not_predictive_outcomes(self):
        result = m.prior_predictive_fixture(self.spec(parameters=((1, 2),), innovations=(-2,)))
        self.assertEqual(result["conditional_means"], [1] * 12)
        self.assertEqual(result["predictive_returns"], [-3] * 12)

    def test_explicit_support_and_bounds_required(self):
        for changes in ({"parameters": ()}, {"innovations": ()}, {"draws": 13},
                        {"seed": True}, {"draws": 0}, {"max_draws": False},
                        {"parameters": ((0, 0),)}, {"innovations": (math.nan,)},
                        {"parameters": ((math.inf, 1),)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.spec(**changes)

    def test_overflow_rejected(self):
        with self.assertRaises(ValueError):
            m.prior_predictive_fixture(self.spec(parameters=((1e308, 1e308),), innovations=(2,)))


class BlockFixtureTests(unittest.TestCase):
    def sample(self, **changes):
        args = dict(rows=[(i * 300, i, i + 100, i + 200) for i in range(8)],
                    block_length=3, blocks=4, max_rows=12, seed=20260905)
        args.update(changes)
        return m.synchronized_block_fixture(**args)

    def test_fixed_seed_and_synchronized_consecutive_blocks(self):
        result = self.sample()
        self.assertEqual(result, self.sample())
        self.assertEqual(result["symbols"], ("BTC", "ETH", "SOL"))
        for start, block in zip(result["starts"], result["blocks"]):
            self.assertEqual(block, tuple((i * 300, i, i + 100, i + 200)
                                          for i in range(start, start + 3)))

    def test_invalid_batch_is_rejected_atomically(self):
        for rows in ([], [(0, 1, 2)], [(0, 1, 2, 3), (600, 1, 2, 3)],
                     [(0, 1, 2, 3), (0, 1, 2, 3)], [(1, 1, 2, 3)],
                     [(0, 1, math.nan, 3)], [(300, 1, 2, 3), (0, 1, 2, 3)]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.sample(rows=rows)

    def test_resource_bounds_and_insufficient_history(self):
        for changes in ({"block_length": 9}, {"blocks": 5}, {"seed": None},
                        {"max_rows": 7}, {"block_length": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.sample(**changes)


class EvidenceTests(unittest.TestCase):
    def bundle(self):
        return m.seal_fixture({"fixture": [1, 2]}, {"rhat": None, "ess": None,
                                                    "divergences": None})

    def test_canonical_hash_and_alias_isolation(self):
        self.assertEqual(m.digest({"a": 1, "b": 2}), m.digest({"b": 2, "a": 1}))
        payload = {"fixture": [1]}
        bundle = m.seal_fixture(payload, {})
        payload["fixture"].append(2)
        self.assertEqual(bundle["artifact"]["payload"]["fixture"], [1])
        with self.assertRaises(ValueError):
            m.seal_fixture({}, {"ess": math.nan})

    def test_intact_evidence_still_abstains(self):
        result = m.abstention_contract(self.bundle())
        self.assertEqual(result["action"], "ABSTAIN")
        self.assertIn("UNAPPROVED", result["reason"])
        self.assertFalse(result["MATHEMATICAL_FILTERING_ENABLED"])
        self.assertEqual(result["MODEL_STATUS"], "NOT_TRAINED")

    def test_artifact_and_diagnostic_tampering(self):
        for key in ("artifact", "diagnostics"):
            bundle = copy.deepcopy(self.bundle())
            bundle[key]["extra"] = 1
            self.assertEqual(m.abstention_contract(bundle)["reason"], "ABSTAIN_HASH_MISMATCH")

    def test_rehashed_diagnostics_cannot_change_artifact_binding(self):
        bundle = self.bundle()
        bundle["diagnostics"]["artifact_sha256"] = "0" * 64
        bundle["diagnostics_sha256"] = m.digest(bundle["diagnostics"])
        self.assertEqual(m.abstention_contract(bundle)["reason"], "ABSTAIN_HASH_MISMATCH")

    def test_versions_missing_and_invalid_evidence_abstain(self):
        bundle = self.bundle()
        bundle["artifact"]["version"] = "unknown"
        self.assertEqual(m.abstention_contract(bundle)["reason"], "ABSTAIN_VERSION_MISMATCH")
        for invalid in ({}, None, {"artifact": [], "diagnostics": {}}):
            self.assertEqual(m.abstention_contract(invalid)["reason"], "ABSTAIN_INVALID_EVIDENCE")


class ExistingRiskLinesTests(unittest.TestCase):
    def test_daily_baseline_not_reset_and_boundary_inclusive(self):
        risk = c.RiskLines(10000, 9910, 11000, .01)
        self.assertEqual(risk.daily_loss_line, 9900)
        self.assertEqual(risk.remaining_daily_loss_budget, 10)
        self.assertTrue(risk.daily_breached(9900))
        self.assertFalse(risk.daily_breached(9900.01))
        self.assertEqual(c.RiskLines(10000, 9890, 11000, .01).remaining_daily_loss_budget, 0)

    def test_distinct_incremental_and_hwm_peaks(self):
        risk = c.RiskLines(10000, 9910, 11000, .01)
        self.assertAlmostEqual(risk.incremental_drawdown(9800), 1 - 9800 / 9910)
        self.assertAlmostEqual(risk.hwm_drawdown(9800), 1 - 9800 / 11000)
        self.assertAlmostEqual(risk.incremental_drawdown(9800, 12000), 1 - 9800 / 12000)
        self.assertAlmostEqual(risk.hwm_drawdown(9800, 12000), 1 - 9800 / 12000)

    def test_cost_adjusted_liquidation_equity_consumes_daily_distance(self):
        cash, quantity, liquidation_mark, exit_cost = 9000, 10, 92, 10
        equity = cash + quantity * liquidation_mark - exit_cost
        risk = c.RiskLines(10000, equity, 11000, .01)
        self.assertEqual(equity, 9910)
        self.assertEqual(risk.remaining_daily_loss_budget, 10)
        self.assertTrue(risk.daily_breached(equity - 10))

    def test_unknown_day_baseline_and_marks_cannot_be_zero_filled(self):
        for value in (None, 0, math.nan):
            with self.assertRaises(ValueError):
                c.RiskLines(value, 9910, 11000, .01)
        risk = c.RiskLines(10000, 9910, 11000, .01)
        for value in (None, math.nan, math.inf, -1):
            with self.assertRaises(ValueError):
                risk.daily_breached(value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
