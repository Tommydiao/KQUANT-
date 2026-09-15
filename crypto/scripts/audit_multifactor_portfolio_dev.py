"""Saved-replay validation audit; no new simulation, fitting or winner selection."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.candidate_metrics import summarize
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_holding_validation import audit_intervals, capital_time


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source, out = (ROOT / args.source).resolve(), (ROOT / args.output).resolve()
    parent = ROOT / 'outputs/hybrid_delivery'
    if not source.is_relative_to(parent) or not out.is_relative_to(parent):
        raise ValueError('Independent research paths required')
    report = json.loads((source / 'report.json').read_text())
    if report['scope'] != 'DEV_ONLY' or report['execution_enabled'] or not report['original_wrapper_parity']:
        raise ValueError('Audited original parity and DEV_ONLY required')
    out.mkdir(exist_ok=False)
    write_json(out / 'audit_contract.json', {
        'version': 'holding_validation_audit_v1', 'source_report_hash': sha(source / 'report.json'),
        'scope': 'EXPOSED_RESEARCH', 'selection': False, 'fit': False,
        'bootstrap': 'existing synchronized UTC entry-date seven-day blocks, 2000 samples',
        'calendar': 'three retrospective development thirds, NOT an untouched test',
        'embargo': 'not frozen for unbounded structural holding; interval purge audit only',
        'code_hash': sha(Path(__file__)),
        'metrics_hash': sha(ROOT / 'kquant_crypto/candidate_metrics.py'),
        'interval_code_hash': sha(ROOT / 'kquant_crypto/hybrid_holding_validation.py')})
    scenarios = {}
    for name, recorded in report['scenarios'].items():
        folder = source / name
        for file, key in [('trades.jsonl', 'trade_hash'), ('equity.jsonl', 'equity_hash')]:
            if sha(folder / file) != recorded[key]:
                raise ValueError('Source changed: ' + name + '/' + file)
        trades, equity = read_rows(folder / 'trades.jsonl'), read_rows(folder / 'equity.jsonl')
        # Warmup equity cannot inflate the research calendar or bootstrap window.
        manifest = json.loads((ROOT / 'outputs/dual_regime_v1/frozen/data_manifest.json').read_text())
        start = manifest['window']['start']
        end = start + int(manifest['window']['days'] * .7) * 86400
        if any(t['signal_time'] < start or t['exit_time'] > end for t in trades):
            raise ValueError('Trade outside authorized DEV interval')
        equity = [e for e in equity if start <= e['time'] <= end]
        days = (end - start) // 86400
        bounds = [start + (days * i // 3) * 86400 for i in (1, 2)]
        metrics = summarize(trades, equity)
        metrics['gates']['checks']['max_drawdown_r']['status'] = 'UNRESOLVED_DEFINITION'
        metrics['gates']['checks']['max_drawdown_r']['note'] = 'Existing 10R denominator dispute retained; not a pass'
        stress_name = name.rsplit('_', 1)[0] + '_2'
        scenarios[name] = {'metrics': metrics, 'holding_intervals': audit_intervals(trades, bounds),
                           'capital_time': capital_time(trades),
                           'full_stress_scenario': stress_name if name.endswith('_1') and stress_name in report['scenarios'] else None,
                           'embargo_validated': False, 'independent_oos': False}
        # Existing statistics include a fixed-trade stress only for BASE rows.
        scenarios[name]['bootstrap_caveat'] = 'Calendar length does not prove independent labels or stable market performance'
    write_json(out / 'report.json', {'scenarios': scenarios, 'scope': 'DEV_ONLY',
        'performance': 'PERFORMANCE_UNPROVEN',
        'descriptive_targets': {name: row['metrics']['performance_status'] for name, row in scenarios.items()},
        'execution_enabled': False, 'winner_selection': False,
        'remaining': ['unexposed evaluation permission', 'new holding embargo freeze',
                      '10R definition', 'trend capture and giveback audit', 'predictive calibration']})
    print(json.dumps({name: {'trades': r['metrics']['sample_count'],
                           'mean_r': r['metrics']['expectancy_r'], 'payoff': r['metrics']['payoff'],
                           'bootstrap': r['metrics']['bootstrap']['interval_95'],
                           'longest_hold_hours': r['holding_intervals']['max_holding_hours'],
                           'dependency_groups': len(r['holding_intervals']['dependency_groups'])}
                      for name, r in scenarios.items()}))


if __name__ == '__main__':
    main()
