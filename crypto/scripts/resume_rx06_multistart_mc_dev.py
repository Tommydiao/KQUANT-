"""Resume verified frozen MC prefixes into a new directory, never overwrite."""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.hybrid_conditioned_paths import conditioned_paths
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_mc_paths_v12 import DevPathSpec, audit_history
from kquant_crypto.hybrid_mc_recovery import read_prefix
from scripts.run_rx06_multistart_mc_dev import simulate


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--prior', required=True)
    p.add_argument('--starts', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    prior, starts, out = [(ROOT/v).resolve() for v in (a.prior, a.starts, a.output)]
    if any(not v.is_relative_to(ROOT/'outputs/hybrid_delivery') for v in (prior,starts,out)) or out.exists():
        raise ValueError('Independent source and new output required')
    registered = json.loads((prior/'preregistration.json').read_text())
    frozen = json.loads((starts/'preregistration.json').read_text())
    if registered['frozen'] != frozen or registered['requested_paths'] != 5000:
        raise ValueError('Frozen simulation contract mismatch')
    for name, expected in {**frozen['code_hashes'], **registered['code_hashes']}.items():
        source = (ROOT/name).resolve()
        if not source.is_relative_to(ROOT) or sha(source) != expected:
            raise ValueError('Simulation source changed: '+name)
    if sha(starts/'start_index.json') != registered['index_hash']:
        raise ValueError('Start index changed')
    config = frozen['config']
    policy = load_policy(candidate='A')
    rules_file = ROOT/'outputs/dual_regime_v1/exchange_rules.json'
    if policy['policy_hash'] != frozen['original_policy_hash'] or sha(rules_file) != frozen['rules_hash']:
        raise ValueError('Original policy/rules changed')
    rules = json.loads(rules_file.read_text())['rules']
    index = json.loads((starts/'start_index.json').read_text())
    prefixes = {}
    for item in index:
        name = f"paths_{item['as_of']}.jsonl"
        rows, raw = read_prefix(prior/name, config['policies'], 5000)
        prefixes[name] = dict(rows=rows, raw=raw, lines=raw.splitlines(keepends=True),
            sha256=hashlib.sha256(raw).hexdigest(), existed=(prior/name).exists())
    out.mkdir(exist_ok=False)
    write_json(out/'preregistration.json', registered)
    write_json(out/'recovery_manifest.json', dict(prior=str(prior),
        prior_preregistration_hash=sha(prior/'preregistration.json'),
        prefixes={name:dict(rows=len(v['rows']), sha256=v['sha256'], existed=v['existed']) for name,v in prefixes.items()},
        recovery_code_hash=sha(Path(__file__)), validator_hash=sha(ROOT/'kquant_crypto/hybrid_mc_recovery.py'),
        original_outputs_modified=False, provenance='Continuation of same frozen paths, not new experiment'))
    results = []
    for item in index:
        file = (starts/item['snapshot_file']).resolve()
        if not file.is_relative_to(starts) or sha(file) != item['snapshot_hash']:
            raise ValueError('Snapshot changed')
        snap = json.loads(file.read_text())
        spec = DevPathSpec(snap['history'][0]['start'], snap['as_of'], snap['as_of'],
            config['block_bars'], config['horizon_bars'], 5000, config['seed'],
            config['history_bars'], 5000*config['horizon_bars']*3,
            snap['source_dataset_hash'], 'EXPOSED_DEV_AUTHORIZED')
        audit = audit_history(snap['history'], spec)
        eligible = [i for i in audit['eligible_block_starts'] if snap['history'][i]['regime_before'] == snap['regime']]
        name = f"paths_{snap['as_of']}.jsonl"
        prefix = prefixes[name]
        if len(eligible) < config['minimum_conditioned_blocks']:
            if prefix['rows']: raise ValueError('Unexpected output on ineligible start')
            results.append(dict(as_of=snap['as_of'],status='UNAVAILABLE',reason='INSUFFICIENT_CONDITIONED_BLOCKS',eligible_blocks=len(eligible)))
            continue
        values = {c:[] for c in config['policies']}
        with (out/name).open('xb') as handle:
            for generated in conditioned_paths(snap['history'],snap['anchors'],spec,snap['regime']):
                n = generated['path_id']
                if n < len(prefix['rows']):
                    row = prefix['rows'][n]
                    if row['sampling_hash'] != generated['sampling_hash']:
                        raise ValueError('Saved prefix does not match deterministic sampling')
                else:
                    row = dict(path_id=n,sampling_hash=generated['sampling_hash'],
                        results=simulate(snap,generated,policy,rules,config['policies']))
                handle.write(prefix['lines'][n] if n < len(prefix['rows'])
                    else (json.dumps(row,allow_nan=False)+'\n').encode())
                for c,value in row['results'].items(): values[c].append(value)
                if (n+1)%100==0:
                    handle.flush()
                    print(json.dumps(dict(as_of=snap['as_of'],completed=n+1,reused_prefix=len(prefix['rows']))),flush=True)
        summary = {c:dict(net_change_quantiles=np.quantile([r['net_change'] for r in rows],[.1,.5,.9]).tolist(),
            max_historical_nav_drawdown=max(r['max_historical_nav_drawdown'] for r in rows),
            max_incremental_nav_drawdown=max(r['max_incremental_nav_drawdown'] for r in rows),
            open_at_horizon_paths=sum(r['open_at_horizon']>0 for r in rows)) for c,rows in values.items()}
        results.append(dict(as_of=snap['as_of'],status='COMPLETED',paths=5000,summary=summary,
            reused_paths=len(prefix['rows']),path_hash=sha(out/name),spec=asdict(spec)))
        write_json(out/'progress.json',dict(completed_starts=len(results),total_starts=len(index)))
    for name,v in prefixes.items():
        if v['existed'] and sha(prior/name) != v['sha256']:
            raise ValueError('Prior evidence changed during recovery')
    write_json(out/'report.json',dict(starts=results,requested_paths_per_start=5000,runtime_enabled=False,
        calibrated_risk=False,performance='PERFORMANCE_UNPROVEN',original_outputs_modified=False,
        limitation='Exposed original-risk starts; correlated windows, proxy prices and no new signals'))
    print(json.dumps(dict(statuses=dict(Counter(r['status'] for r in results)))))


if __name__ == '__main__': main()
