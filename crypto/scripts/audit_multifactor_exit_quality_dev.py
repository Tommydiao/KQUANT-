"""Recompute post-hoc exit marks from authorized data; no future signal changes."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dataset import load_development
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_exit_quality import exit_quality


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source, out = (ROOT/args.source).resolve(), (ROOT/args.output).resolve()
    parent = ROOT/'outputs/hybrid_delivery'
    if not source.is_relative_to(parent) or not out.is_relative_to(parent):
        raise ValueError('Independent research output required')
    report = json.loads((source/'report.json').read_text())
    if report['scope'] != 'DEV_ONLY' or report['execution_enabled']:
        raise ValueError('Research replay required')
    out.mkdir(exist_ok=False)
    write_json(out/'audit_contract.json', {'scope': 'DEV_ONLY', 'selection': False,
        'feature_eligible': False, 'basis': 'pre-exit closed-bar costed marks, no intrabar oracle',
        'source_report_hash': sha(source/'report.json'), 'code_hash': sha(Path(__file__)),
        'quality_code_hash': sha(ROOT/'kquant_crypto/hybrid_exit_quality.py')})
    data = load_development(ROOT/'outputs/dual_regime_v1/frozen/data_manifest.json')
    if data.content_hash != report['dataset_hash']:
        raise ValueError('Different authorized dataset')
    results = {}
    with (out/'trade_quality.jsonl').open('x', encoding='utf-8') as handle:
        for scenario, meta in report['scenarios'].items():
            file = source/scenario/'trades.jsonl'
            if sha(file) != meta['trade_hash']:
                raise ValueError('Trade hash mismatch')
            quality = []
            for line in file.read_text().splitlines():
                trade = json.loads(line)
                row = exit_quality(trade, data.bars[trade['symbol']]['5m'], data.cutoff)
                row.update(scenario=scenario, symbol=trade['symbol'], mode=trade['mode'], trade_id=trade['trade_id'])
                quality.append(row)
                handle.write(json.dumps(row, allow_nan=False)+'\n')
            by_mode = {}
            for mode in sorted({r['mode'] for r in quality}):
                rows = [r for r in quality if r['mode']==mode and r['status']=='AVAILABLE']
                peak = sum(r['observed_peak_net_r'] for r in rows)
                by_mode[mode] = {'resolved': len(rows),
                    'mean_giveback_r': sum(r['giveback_net_r'] for r in rows)/len(rows) if rows else None,
                    'weighted_peak_capture': sum(r['net_r'] for r in rows)/peak if peak else None,
                    'mean_holding_hours': sum(r['holding_hours'] for r in rows)/len(rows) if rows else None}
            results[scenario] = {'by_mode': by_mode, 'unavailable': sum(r['status']!='AVAILABLE' for r in quality)}
    write_json(out/'report.json', {'scope': 'DEV_ONLY', 'results': results,
        'trade_quality_hash': sha(out/'trade_quality.jsonl'), 'feature_eligible': False,
        'execution_enabled': False, 'performance': 'PERFORMANCE_UNPROVEN'})
    print(json.dumps(results))


if __name__ == '__main__':
    main()
