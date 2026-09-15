import ast
from importlib.util import find_spec
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from kquant_crypto import hybrid_posterior_review as review

OPTIONAL_MATH = all(find_spec(name) is not None for name in ("arviz", "numpy", "scipy", "xarray"))


class PosteriorReviewTests(unittest.TestCase):
    def test_non_dev_purpose_refused_before_io(self):
        for purpose in ("LIVE", "PAPER", "SHADOW", "EVAL", "QUOTE_AWARE", None):
            with self.subTest(purpose=purpose), patch.object(review, "sha") as sha:
                with self.assertRaisesRegex(ValueError, "non-DEV_ONLY"):
                    review.verify_frozen(purpose=purpose)
                sha.assert_not_called()

    def test_unapproved_path_refused_before_read(self):
        with patch.object(review, "sha") as sha:
            with self.assertRaisesRegex(ValueError, "only dev_fit"):
                review.verify_frozen("restricted_interval")
            sha.assert_not_called()

    def test_manifest_tampering_refused(self):
        with patch.object(review, "sha", return_value="changed"):
            with self.assertRaisesRegex(ValueError, "manifest hash"):
                review.verify_frozen()

    def test_posterior_tampering_refused(self):
        real = review.sha
        with patch.object(review, "sha", side_effect=lambda p: "changed" if Path(p).name == "posterior.nc" else real(p)):
            with self.assertRaisesRegex(ValueError, "artifact hash"):
                review.verify_frozen()

    def test_real_frozen_hashes(self):
        hashes = review.verify_frozen()
        self.assertEqual(hashes["posterior.nc"], "0ecd5412500f820e96c8629d5a1b2e0d6f3751216c25556b6e457601b131dc61")
        self.assertEqual(hashes["delivery_manifest.json"], review.MANIFEST_SHA)

    def test_unsupported_groups_and_execution_targets_abstain(self):
        coverage = {"SOLUSDT:UP_TREND": 14}
        result = review.output_permission(coverage, "BTCUSDT", "RANGE", "QUOTE_AWARE")
        self.assertEqual(result["admission"], "ABSTAIN")
        self.assertIn("UNSUPPORTED_GROUP", result["reasons"])
        self.assertIn("UNSUPPORTED_EXECUTION_TARGET", result["reasons"])
        for name in ("p_win", "p_edge", "q05_mu", "outcome_quantiles"):
            self.assertIsNone(result[name])
        self.assertFalse(any(result[k] for k in review.PERMISSIONS))

    def test_observed_group_is_not_automatically_valid(self):
        result = review.output_permission({"SOLUSDT:UP_TREND": 14}, "SOLUSDT", "UP_TREND", review.TARGET,
                                          feature_in_range=False)
        self.assertEqual(result["admission"], "ABSTAIN")
        self.assertNotIn("UNSUPPORTED_GROUP", result["reasons"])
        self.assertIn("OUTSIDE_OBSERVED_FEATURE_RANGE", result["reasons"])

    @unittest.skipUnless(OPTIONAL_MATH, "isolated ArviZ math environment required")
    def test_probability_mean_and_outcome_quantiles_separated(self):
        import numpy as np
        from scipy.stats import t
        mu = np.tile(np.linspace(.1, .3, 200), (4, 1))
        sigma, nu = np.ones_like(mu) * 2, np.ones_like(mu) * 5
        pred = np.tile(np.linspace(-4, 4, 200), (4, 1))
        result = review.critical_outputs(mu, sigma, nu, pred)
        self.assertAlmostEqual(result["p_win"]["estimate"], float(t.sf(0, 5, loc=mu, scale=sigma).mean()))
        self.assertEqual(result["p_edge"]["estimate"], 1)
        self.assertIsNone(result["p_edge"]["mcse"])
        self.assertLess(result["p_win"]["estimate"], .6)
        self.assertGreater(result["q05_mu"]["estimate"], 0)
        self.assertLess(result["q05_outcome"]["estimate"], -3)

    @unittest.skipUnless(OPTIONAL_MATH, "isolated ArviZ math environment required")
    def test_mcse_matches_autocorrelation_aware_arviz_quantile(self):
        import arviz as az
        import numpy as np
        rng = np.random.default_rng(17)
        values = rng.normal(size=(4, 400))
        for i in range(1, 400):
            values[:, i] += .8 * values[:, i - 1]
        result = review.estimate(values, quantile=.05)
        self.assertAlmostEqual(result["mcse"], float(az.mcse(values, method="quantile", prob=.05)))
        self.assertEqual(len(result["per_chain"]), 4)
        self.assertAlmostEqual(review.estimate(values)["mcse"], float(az.mcse(values, method="mean")))

    @unittest.skipUnless(OPTIONAL_MATH, "isolated ArviZ math environment required")
    def test_invalid_and_constant_draws_do_not_fake_zero_mcse(self):
        import numpy as np
        self.assertIsNone(review.estimate(np.ones((4, 20)))["mcse"])
        for values in (np.ones(20), np.ones((4, 2)), np.full((4, 20), np.nan)):
            with self.assertRaises(ValueError):
                review.estimate(values)

    @unittest.skipUnless(OPTIONAL_MATH, "isolated ArviZ math environment required")
    def test_depth_and_steps_caps_are_distinct(self):
        import numpy as np
        import xarray as xr
        values = np.arange(8).reshape(2, 4).astype(float)
        posterior = xr.Dataset({name: (("chain", "draw"), values + i) for i, name in enumerate(review.PARAMETERS)},
                               coords={"chain": [0, 1], "draw": range(4)})
        stats = xr.Dataset({"tree_depth": (("chain", "draw"), [[10, 10, 9, 8], [9, 8, 7, 6]]),
                            "n_steps": (("chain", "draw"), [[1023, 600, 511, 255], [511, 255, 127, 63]]),
                            "diverging": (("chain", "draw"), np.zeros((2, 4), dtype=bool))})
        result = review.chain_diagnostics(posterior, stats, 10)
        self.assertEqual(result[0]["at_depth_cap"], 2)
        self.assertEqual(result[0]["steps_at_cap"], 1)
        self.assertEqual(result[1]["steps_at_cap_fraction"], 0)
        self.assertAlmostEqual(result[0]["top_parameter_correlations"][0]["pearson_r"], 1)
        self.assertIsNone(result[1]["parameter_depth_correlations"][0]["cap_indicator_r"])

    def test_evidence_write_is_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            review.write_new(path, {"original": True})
            with self.assertRaises(FileExistsError):
                review.write_new(path, {"original": False})
            self.assertEqual(json.loads(path.read_text()), {"original": True})

    def test_import_does_not_load_sampler_or_production(self):
        command = [sys.executable, "-B", "-c",
                   "import sys; import kquant_crypto.hybrid_posterior_review; "
                   "assert not any(x in sys.modules for x in ['pymc','numpyro','jax','arviz',"
                   "'kquant_crypto.model_registry','kquant_crypto.hybrid_dev_fit'])"]
        result = subprocess.run(command, cwd=review.ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        tree = ast.parse(Path(review.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertFalse((node.module or "").startswith(("kquant_crypto", "pymc", "numpyro", "jax")))

    def test_acceptance_keeps_unverified_timing_partial(self):
        tasks = review.read_json(review.ROOT / "plan/hybrid_to_live_tasks.v1_2.json")["tasks"]
        result = review._acceptance(tasks)
        self.assertEqual(len(result["T14"]["acceptance"]), 4)
        self.assertEqual(result["T15"]["acceptance"][1]["coverage"], "PARTIAL")
        self.assertEqual(result["T15"]["status"], "PARTIAL_NO_G2_PASS")


if __name__ == "__main__":
    unittest.main()
