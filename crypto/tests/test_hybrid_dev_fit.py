import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from unittest.mock import patch
from kquant_crypto.hybrid_dev_fit import ROOT, CONFIG, audit, base_r, index_rows, load_dev_artifact, fit, sha


class DevFitTests(unittest.TestCase):
    def test_unregistered_backend_rejected_before_output(self):
        with self.assertRaisesRegex(ValueError, 'unregistered numerical backend'):
            fit('nonexistent', sampler_backend='auto_select_best')

    def test_backend_change_does_not_change_statistical_configuration(self):
        policy = json.loads((ROOT / 'config/hybrid_dev_backend_v1.json').read_text())
        self.assertEqual(policy['fixed_model_config_sha256'], sha(CONFIG))
        self.assertFalse(policy['runtime_loading'])

    def test_module_import_keeps_sampler_dependencies_unloaded(self):
        result = subprocess.run([sys.executable, '-B', '-c',
            "import sys; import kquant_crypto.hybrid_dev_fit; assert 'pymc' not in sys.modules; assert 'arviz' not in sys.modules"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_audited_population(self):
        rows, report = audit(json.loads(CONFIG.read_text()))
        self.assertEqual(len(rows), 27)
        self.assertEqual(len(report['excluded_unavailable']), 23)
        self.assertEqual(report['original_splits'], {'train': 12, 'validation': 5, 'test': 10})

    def test_duplicates(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            index_rows([{'economic_signal_id': 'x'}] * 2)

    def test_non_dev_loader_fails_before_io(self):
        for purpose in ('production', 'PAPER', 'EVAL', '', None):
            with self.assertRaises(ValueError):
                load_dev_artifact('nonexistent', purpose=purpose)

    def test_other_data_refused(self):
        c = json.loads(CONFIG.read_text())
        c['dataset'] = 'heldout'
        with self.assertRaises(ValueError):
            audit(c)

    def test_hash_tampering_refused(self):
        with patch('kquant_crypto.hybrid_dev_fit.sha', return_value='tampered'):
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                audit(json.loads(CONFIG.read_text()))

    @unittest.skipUnless(importlib.util.find_spec('pymc') is not None, 'isolated PyMC environment required')
    def test_pymc_student_t_density_matches_scipy(self):
        import numpy as np
        import pymc as pm
        from scipy.stats import t
        values = np.array([-3., 0., 1., 5.])
        actual = pm.logp(pm.StudentT.dist(nu=7, mu=.4, sigma=.8), values).eval()
        np.testing.assert_allclose(actual, t.logpdf(values, df=7, loc=.4, scale=.8), rtol=1e-6)

    def test_prior_contract_is_fixed(self):
        c = json.loads(CONFIG.read_text())
        self.assertEqual(c['features'], ['er24_1h'])
        self.assertEqual(c['chains'], 4)
        self.assertEqual(c['seed'], 20260905)
        self.assertEqual(c['priors']['nu_minus_two_exponential_rate'], .1)

    @unittest.skipUnless(importlib.util.find_spec('numpyro') is not None, 'compiled isolated environment required')
    def test_numpyro_density_and_gradient_match_analytic_contract(self):
        import jax
        import numpy as np
        from numpyro.distributions import StudentT
        from scipy.stats import t
        jax.config.update('jax_enable_x64', True)
        values = np.array([-3., 0., 1., 5.])
        nu, mu, sigma = 7., .4, .8
        actual = jax.jit(lambda x: StudentT(nu, mu, sigma).log_prob(x))(values)
        np.testing.assert_allclose(actual, t.logpdf(values, nu, loc=mu, scale=sigma), rtol=1e-10)
        gradient = jax.grad(lambda m: StudentT(nu, m, sigma).log_prob(values).sum())(mu)
        expected = np.sum((nu+1)*(values-mu)/(nu*sigma*sigma+(values-mu)**2))
        self.assertAlmostEqual(float(gradient), float(expected), places=10)

    @unittest.skipUnless((ROOT / 'outputs/hybrid_regime_v1/dev_fit_20260905_03/artifact.json').exists(), 'fit not yet complete')
    @unittest.skipUnless(importlib.util.find_spec('arviz') is not None, 'isolated ArviZ environment required')
    def test_actual_posterior_artifact(self):
        import numpy as np
        out = ROOT / 'outputs/hybrid_regime_v1/dev_fit_20260905_03'
        trace = load_dev_artifact(out, purpose='DEV_ONLY')
        self.assertEqual(trace.posterior.sizes['chain'], 4)
        self.assertEqual(trace.posterior.sizes['draw'], 1500)
        self.assertTrue(bool((trace.posterior.nu > 2).all()))
        self.assertTrue(bool(np.isfinite(trace.posterior.mu).all()))
        rows = json.loads((out / 'row_provenance.json').read_text())
        transform = json.loads((out / 'transform.json').read_text())
        for i, row in enumerate(rows):
            mode = row['label']['mode']
            cell = row['label']['symbol'] + ':' + mode
            x = (row['feature']['values']['er24_1h'] - transform['mean'][0]) / transform['scale'][0]
            expected = trace.posterior.alpha.sel(mode=mode) + trace.posterior.u_symbolmode.sel(cell=cell) + trace.posterior.beta.sel(mode=mode, feature='er24_1h') * x
            np.testing.assert_allclose(trace.posterior.mu.isel(obs=i), expected, atol=1e-12)

    def test_analytical_cost_contract(self):
        entry, exit_price, risk, qty = 100 * 1.0005, 110, 0, 2
        risk = entry - 90 * .9995 + .001 * (entry + 90 * .9995)
        fees = .001 * qty * (entry + exit_price)
        pnl = qty * (exit_price - entry) - fees
        label = {'net_r': pnl / (qty * risk), 'executed_trade': {'quantity': qty, 'entry_price': entry,
            'exit_price': exit_price, 'fees': fees, 'net_pnl': pnl, 'risk_amount': qty * risk, 'unit_net_risk': risk}}
        opp = {'plan': {'entry_reference': 100, 'stop': 90, 'unit_net_risk': risk}}
        self.assertAlmostEqual(base_r(label, opp), -entry * 1.001 / risk)
        bad = copy.deepcopy(label)
        bad['net_r'] = 0
        with self.assertRaises(ValueError):
            base_r(bad, opp)


if __name__ == '__main__':
    unittest.main()
