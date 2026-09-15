"""Descriptive reclassification of exposed archived paths; no resampling."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_delivery import atomic_json, load, sha
from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.hybrid_mc_event_contract import RiskEvent, freeze_events
from kquant_crypto.hybrid_mc_comparison_v12 import summarize_common_paths


def read_archive(source, original, events):
    if sha(source / 'paths.jsonl.gz') != original['compressed_sha256']:
        raise ValueError('Archive integrity failed')
    records = {1: [], 2: []}
    chain = hashlib.sha256()
    ids = []
    expected_keys = {f'{a}:{c}' for a in (0,.25,.5,1) for c in (1,2)}
    with gzip.open(source / 'paths.jsonl.gz', 'rt', encoding='utf-8') as stream:
        for line in stream:
            chain.update(line.rstrip('\n').encode())
            row = json.loads(line)
            if type(row['path_id']) is not int or row['path_id'] != len(ids):
                raise ValueError('Ordered unique original path IDs required')
            if set(row['costs']) != expected_keys:
                raise ValueError('Incomplete or unexpected alternatives/costs')
            ids.append(row['path_id'])
            for cost in (1, 2):
                for a in (0, .25, .5, 1):
                    risk = row['costs'][f'{a}:{cost}']['risk']
                    records[cost].append({'path_id':row['path_id'], 'alternative':a,
                        'events': {e.event_id:e.classify(risk) for e in events}})
    if chain.hexdigest() != original['record_hash'] or len(ids) != original['completed']:
        raise ValueError('Record identity/count mismatch')
    if not ids:
        raise ValueError('Empty archive has no probability evidence')
    return records, ids, chain.hexdigest()


def run(output):
    out = (ROOT / output).resolve()
    if not out.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent output required')
    out.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'outputs/hybrid_delivery/mc_process_load_20260906_03/mc'
    source_policy = load(source / 'synthetic_initial_state.json')['policy_hash']
    if source_policy != load_policy(candidate='A')['policy_hash']:
        raise ValueError('Current and archived policy differ; explicit migration required')
    events = [RiskEvent('daily_loss', 'daily_loss_line_breached'),
              RiskEvent('terminal_loss', 'terminal_net_change', 0)]
    contract = freeze_events(events, policy_hash=source_policy,
                             costs=(1, 2), comparison_budget=16, input_exposure='EXPOSED_RESEARCH')
    atomic_json(out / 'preregistration.json', {'contract': contract, 'family_alpha': .05,
        'analysis_type': 'POSTHOC_EXPOSED_DESCRIPTIVE_NOT_CONFIRMATORY',
        'source_archive_sha256': sha(source / 'paths.jsonl.gz'),
        'source_state_sha256': sha(source / 'synthetic_initial_state.json'),
        'script_sha256': sha(Path(__file__)),
        'event_code_sha256': sha(ROOT / 'kquant_crypto/hybrid_mc_event_contract.py'),
        'no_resampling': True})
    original = load(source / 'report.json')
    records, ids, record_hash = read_archive(source, original, events)
    result = {'scope': 'DEV_ONLY_POSTHOC_ARCHIVE_REVIEW', 'record_hash':record_hash,
              'paths':len(ids), 'contract_hash':contract['contract_hash'],
              'G4_passed':False, 'execution_enabled':False, 'resampled':False,
              'cost_results':{str(c):summarize_common_paths(records[c], path_ids=ids,
                  alternatives=(0,.25,.5,1), event_names=['daily_loss','terminal_loss'],
                  family_alpha=.05, comparison_budget=16) for c in (1,2)}}
    atomic_json(out / 'report.json', result)
    print(json.dumps({'paths':len(ids),'G4_passed':False,'resampled':False}))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    run(p.parse_args().output)
