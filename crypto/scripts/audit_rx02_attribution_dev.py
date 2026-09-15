"""Read immutable existing replays; write independent RX02 partial evidence."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_entry_attribution import cost_bridge, compare_opportunities, summarize_bridge


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(source, paired, output):
    for path in (source, paired, output):
        if not path.is_relative_to(ROOT/'outputs/hybrid_delivery'):
            raise ValueError('Independent research paths required')
    if output.exists():
        raise ValueError('Do not overwrite prior evidence')
    report = json.loads((source/'report.json').read_text())
    pair_report = json.loads((paired/'report.json').read_text())
    if report['execution_enabled'] or pair_report['baseline_matches'] != 27:
        raise ValueError('Frozen research baseline required')
    if report['dataset_hash'] != pair_report['dataset_hash']:
        raise ValueError('Dataset mismatch')
    inputs = {str(path.relative_to(ROOT)): sha(path) for path in (source/'report.json', paired/'report.json', paired/'trades.jsonl')}
    if sha(paired/'trades.jsonl') != pair_report['trades_hash']:
        raise ValueError('Paired trade hash mismatch')
    trades = {}
    for name, meta in report['scenarios'].items():
        path = source/name/'trades.jsonl'
        if sha(path) != meta['trade_hash']:
            raise ValueError('Portfolio trade hash mismatch')
        inputs[str(path.relative_to(ROOT))] = sha(path)
        trades[name] = [json.loads(line) for line in path.read_text().splitlines()]
    pairs = [json.loads(line) for line in (paired/'trades.jsonl').read_text().splitlines()]
    pair_base = {row['trade_id']: row for row in pairs if row['candidate']=='ORIGINAL'}
    paired_delta = {}
    for candidate in ('T1', 'T2'):
        selected = [row for row in pairs if row['candidate']==candidate]
        if len(selected) != 27 or {r['trade_id'] for r in selected} != set(pair_base):
            raise ValueError('Different fixed entry population')
        valid = [r for r in selected if r['net_r'] is not None and pair_base[r['trade_id']]['net_r'] is not None]
        paired_delta[candidate] = dict(total=len(selected), resolved=len(valid),
            mean_paired_net_r_delta=sum(r['net_r']-pair_base[r['trade_id']]['net_r'] for r in valid)/len(valid) if valid else None,
            scope='A27 actual original entries; counterfactual exit labels; excludes 23 unfilled opportunities')
    result = dict(scope='DEV_ONLY_EXPOSED_RESEARCH', execution_enabled=False, status='RX02_PARTIAL',
        generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), inputs=inputs,
        code_hashes={str(p.relative_to(ROOT)):sha(p) for p in (Path(__file__),ROOT/'kquant_crypto/hybrid_entry_attribution.py')},
        bridges={name:summarize_bridge(rows) for name,rows in trades.items()},
        portfolio_composition={name:compare_opportunities(trades['ORIGINAL_1'],trades[name]) for name in ('T1_1','T2_1')},
        paired_exit_effect=paired_delta,
        remaining=['Full 50 opportunity funnel and explicitly marked unfilled counterfactuals',
                   'Legal-window MFE/MAE first-touch timing and target-vs-other-exit audit',
                   'Matched entry reference preregistration, not authorized model activation'],
        independent_oos=False, performance='PERFORMANCE_UNPROVEN')
    output.mkdir(parents=True, exist_ok=False)
    with (output/'trade_bridges.jsonl').open('x', encoding='utf-8') as stream:
        for name, rows in trades.items():
            for row in rows:
                stream.write(json.dumps(dict(scenario=name, economic_key=opportunity_key_json(row),
                    trade_id=row['trade_id'], exit_reason=row['exit_reason'],
                    entry_time=row['entry_time'], exit_time=row['exit_time'], **cost_bridge(row)),allow_nan=False)+'\n')
    result['trade_bridges_hash']=sha(output/'trade_bridges.jsonl')
    result['inputs_unchanged']=all(sha(ROOT/name)==value for name,value in inputs.items())
    (output/'report.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(result,allow_nan=False))


def opportunity_key_json(row):
    return [row['symbol'],row['mode'],row['signal_time']]


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('source','paired','output'):p.add_argument('--'+key,required=True)
    a=p.parse_args()
    run(*[(ROOT/getattr(a,key)).resolve() for key in ('source','paired','output')])
