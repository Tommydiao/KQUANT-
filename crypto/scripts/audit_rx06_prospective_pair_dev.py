"""Terminal paired-run provenance/count/numeric audit; no risk admission."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_mc_recovery import read_pair_prefix
from kquant_crypto.hybrid_mc_paths_v12 import DevPathSpec, audit_history


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quantile(values, p):
    data = sorted(values)
    if not data or not 0 <= p <= 1:
        raise ValueError('Invalid quantile input')
    index = (len(data)-1)*p
    lo, hi = math.floor(index), math.ceil(index)
    return data[lo]+(data[hi]-data[lo])*(index-lo)


def numeric_audit(rows, summary, count):
    if len(rows) != count or summary['paths'] != count:
        raise ValueError('Completed path count mismatch')
    mean = math.fsum(row['paired_net_change'] for row in rows)/count
    if not math.isclose(mean, summary['mean_paired_net_change'], rel_tol=1e-10, abs_tol=1e-9):
        raise ValueError('Paired mean mismatch')
    report = {}
    for name in ('WITH_PLAN','WITHOUT_PLAN'):
        fills = sum(row['results'][name]['target_plan_fills'] for row in rows)
        opened = sum(row['results'][name]['open_at_horizon'] > 0 for row in rows)
        if fills != summary['target_plan_fills'].get(name,0) or opened != summary['horizon_open_paths'].get(name,0):
            raise ValueError('Paired event summary mismatch')
        values = [row['results'][name] for row in rows]
        report[name] = dict(target_fills=fills, horizon_open_paths=opened,
            booked_risk_flag_paths=sum(v['booked_risk_ratio_exceeded'] for v in values),
            net_change_quantiles={str(p): quantile([v['net_change'] for v in values],p) for p in (.1,.5,.9)},
            incremental_nav_drawdown_p90=quantile([v['max_incremental_nav_drawdown'] for v in values],.9))
    return dict(paths=count, mean_paired_net_change=mean, results=report,
                interpretation='Conditional terminal mark differences, not realized returns or calibrated probabilities')


def availability(record, frozen, config):
    paths = [(record['context']['file'], record['context']['hash']),
             (record['snapshot_file'], record['snapshot_hash'])]
    for name, expected in paths:
        path = (frozen/name).resolve()
        if not path.is_relative_to(frozen) or sha(path) != expected:
            raise ValueError('Frozen context/state hash mismatch')
    context = json.loads((frozen/record['context']['file']).read_text())
    history = context['history']
    as_of = record['signal_time']
    if context['as_of'] != as_of or context['history_contiguous'] is not True:
        raise ValueError('History cutoff mismatch')
    spec = DevPathSpec(history[0]['start'], as_of, as_of, config['block_bars'],
        config['horizon_bars'], 1, config['seed'], config['history_bars'],
        config['horizon_bars']*3, context['source_dataset_hash'], 'EXPOSED_DEV_AUTHORIZED')
    checked = audit_history(history,spec)
    blocks = sum(history[j]['regime_before'] == context['regime'] for j in checked['eligible_block_starts'])
    eligible = len(history) == config['history_bars'] and blocks >= config['minimum_conditioned_blocks']
    return dict(eligible=eligible, history_bars=len(history), conditioned_blocks=blocks,
                required_blocks=config['minimum_conditioned_blocks'], regime=context['regime'],
                history_content_hash=checked['history_content_hash'], available_as_of=as_of)


def audit(source, out):
    if not (source/'report.json').exists():
        raise ValueError('Terminal report missing; never audit an incomplete run as complete')
    if out.exists():
        raise FileExistsError(out)
    prereg = json.loads((source/'preregistration.json').read_text())
    report = json.loads((source/'report.json').read_text())
    if report['phase'] != prereg['phase'] or report['execution_enabled'] is not False or report['calibrated_risk'] is not False:
        raise ValueError('Phase or permission mismatch')
    for name, expected in prereg['source_hashes'].items():
        path = (ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or sha(path) != expected:
            raise ValueError('Frozen source hash mismatch: '+name)
    if sha(ROOT/'scripts/run_rx06_prospective_pair_dev.py') != prereg['code_hash']:
        raise ValueError('Runner hash mismatch')
    index_path = ROOT/'outputs/hybrid_delivery/rx06_prospective_states_20260912_01/state_index.json'
    if str(index_path.relative_to(ROOT)) not in prereg['source_hashes']:
        raise ValueError('Missing frozen population identity')
    population = json.loads(index_path.read_text())
    if len(population) != len(report['records']):
        raise ValueError('Population count mismatch')
    counts, expected_files, results, hashes = Counter(), set(), [], {}
    for i, (original, outcome) in enumerate(zip(population, report['records'])):
        identity = {k: original[k] for k in ('economic_signal_id','policy','symbol','mode','signal_time')}
        if any(outcome[k] != v for k,v in identity.items()):
            raise ValueError('Population identity/order mismatch')
        status = outcome['status']
        counts[status] += 1
        if not original['admitted']:
            if status != 'ORIGINAL_REJECTION' or outcome['reason'] != original['reason']:
                raise ValueError('Original rejection changed')
            continue
        data_check = availability(original,index_path.parent,prereg['config'])
        if status == 'UNAVAILABLE':
            if outcome['reason'] != 'INSUFFICIENT_HISTORY_OR_CONDITIONED_BLOCKS':
                raise ValueError('Unknown unavailable reason')
            if data_check['eligible'] or outcome['blocks'] != data_check['conditioned_blocks']:
                raise ValueError('Unavailable classification/count mismatch')
            results.append(dict(**identity,status=status,availability_recomputed=True,availability=data_check))
            continue
        if not data_check['eligible']:
            raise ValueError('Completed run used ineligible history')
        if status != 'COMPLETED' or outcome['path_file'] != f'pair_{i:03d}.jsonl':
            raise ValueError('Invalid completed path identity')
        file = source/outcome['path_file']
        expected_files.add(file.name)
        hashes[file.name] = sha(file)
        if hashes[file.name] != outcome['path_hash']:
            raise ValueError('Output path hash mismatch')
        rows, _ = read_pair_prefix(file, prereg['paths_per_record'])
        results.append(dict(**identity,status=status,availability=data_check,
                            **numeric_audit(rows,outcome,prereg['paths_per_record'])))
    if {p.name for p in source.glob('pair_*.jsonl')} != expected_files:
        raise ValueError('Unexpected/missing paths for rejected or unavailable records')
    if dict(counts) != report['status_counts']:
        raise ValueError('Status count mismatch')
    if any(sha(source/name) != value for name,value in hashes.items()):
        raise ValueError('Output changed during audit')
    result = dict(status='TERMINAL_NUMERIC_AUDIT_PASS', phase=prereg['phase'], counts=dict(counts),
        audited_paired_paths=counts['COMPLETED']*prereg['paths_per_record'], records=results,
        source_report_hash=sha(source/'report.json'), path_hashes=hashes,
        mathematical_generator_recomputed=False, original_protection_replayed=False,
        unavailable_history_recomputed=True, execution_enabled=False, calibrated_risk=False,
        performance='PERFORMANCE_UNPROVEN',
        limitation='Audits stored paired arithmetic and provenance only; not independent path simulation, market calibration, strategy selection or OOS')
    out.mkdir(parents=True, exist_ok=False)
    (out/'report.json').write_text(json.dumps(result, indent=2, allow_nan=False),encoding='utf-8')
    return {k:v for k,v in result.items() if k not in ('records','path_hashes')}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source',required=True)
    p.add_argument('--output',required=True)
    a = p.parse_args()
    print(json.dumps(audit(Path(a.source).resolve(),Path(a.output).resolve())),flush=True)
