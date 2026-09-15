"""Read frozen development outputs and baseline DB; never loads held-out prices."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, UTC
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_observation import legacy_state, ObservationStore
from kquant_crypto.candidate_policy import load_policy


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default='outputs/hybrid_regime_v1/m2_development_20260905_04')
    parser.add_argument('--output', required=True)
    parser.add_argument('--import-independent-ledger', action='store_true')
    parser.add_argument('--ledger-database', default='work/hybrid_m2_legacy_audit_v2.sqlite3')
    args = parser.parse_args()
    source = ROOT / args.source
    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=False)
    report = json.loads((source/'report.json').read_text())
    verified = {name: sha(source/name) == expected for name, expected in report['artifacts'].items()}
    if not all(verified.values()):
        raise ValueError('Frozen M2 artifact hash mismatch')
    opportunities = rows(source/'opportunities.jsonl')
    labels = {r['economic_signal_id']: r for r in rows(source/'labels.jsonl')}
    partitions = {r['economic_signal_id']: r for r in rows(source/'partitions.jsonl')}
    projected = []
    for op in opportunities:
        row = legacy_state(op, labels[op['economic_signal_id']])
        row['utc_date'] = datetime.fromtimestamp(row['signal_time'], UTC).date().isoformat()
        row['partition'] = partitions[row['economic_signal_id']]
        projected.append(row)
    write(out/'opportunity_status_audit.json', projected)
    unfilled = [r for r in projected if r['fill_status'] == 'UNFILLED']
    write(out/'unfilled_details.json', unfilled)
    groups = defaultdict(list)
    for row in projected:
        groups[(row['symbol'], row['mode'], row['utc_date'], row['label_execution_policy_id'], row['label_source'])].append(row)
    grouped = []
    for keys, group in sorted(groups.items()):
        grouped.append(dict(zip(('symbol','mode','utc_date','execution_policy','label_source'), keys)) | {
            'raw_opportunities':len(group), 'entry_attempted':sum(r['entry_attempted'] for r in group),
            'virtual_fills':sum(r['fill_status']=='FILLED' for r in group),
            'mature':sum(r['label_status']=='MATURE' for r in group),
            'unfilled':sum(r['fill_status']=='UNFILLED' for r in group),
            'pending_results':sum(r['label_status']=='PENDING' for r in group),
            'censored':sum(r['label_status']=='CENSORED' for r in group),
            'counterfactual':0,
        })
    with (out/'counts_by_symbol_mode_date_policy_source.csv').open('w', newline='', encoding='utf-8') as f:
        writer=csv.DictWriter(f, fieldnames=list(grouped[0])); writer.writeheader(); writer.writerows(grouped)
    db=sqlite3.connect((ROOT/'work/candidate_simulation.sqlite3').as_uri()+'?mode=ro', uri=True)
    db.execute('PRAGMA query_only=ON')
    rejected=[json.loads(r[0]) for r in db.execute("SELECT payload FROM candidate_records WHERE run_id='dev_A_base_v4' AND kind='events' AND json_extract(payload,'$.kind')='ENTRY_REJECTED'")]
    original_evidence=[]
    for row in unfilled:
        matches=[r for r in rejected if r['symbol']==row['symbol'] and r['time']==row['signal_time']]
        if not matches or not any(r.get('reason') in row['reasons'] for r in matches):
            raise ValueError('Unfilled reason lacks original event evidence')
        original_evidence.append({'economic_signal_id':row['economic_signal_id'],'original_events':matches})
    write(out/'unfilled_original_event_evidence.json',original_evidence)
    baselines={}
    for run in ('dev_A_base_v4','dev_B_base_v4'):
        metadata=json.loads(db.execute('SELECT metadata FROM candidate_runs WHERE run_id=?',(run,)).fetchone()[0])
        source_checks={name:sha(ROOT/'kquant_crypto'/name)==expected for name,expected in metadata['source_hashes'].items()}
        if not all(source_checks.values()):raise ValueError('Original baseline source changed')
        trades=[json.loads(r[0]) for r in db.execute("SELECT payload FROM candidate_records WHERE run_id=? AND kind='trades'",(run,))]
        if not trades:
            raise ValueError('Missing baseline trades')
        baselines[run]={'metadata':metadata, 'trade_count':len(trades),'source_hash_checks':source_checks,
            'first_entry':min(t['entry_time'] for t in trades), 'last_exit':max(t['exit_time'] for t in trades),
            'by_symbol_mode':dict(Counter(t['symbol']+':'+t['mode'] for t in trades)),
            'cost_scenarios':sorted(set((t['fee_bps'],t['execution_cost_bps']) for t in trades)),
            'trades_content_hash':hashlib.sha256(json.dumps(sorted(trades,key=lambda t:t['trade_id']),sort_keys=True).encode()).hexdigest()}
        write(out/(run+'_trades.json'),trades)
    db.close()
    imports={}
    if args.import_independent_ledger:
        rules=json.loads((ROOT/'outputs/dual_regime_v1/exchange_rules.json').read_text())['rules']
        store=ObservationStore(ROOT/args.ledger_database,load_policy(candidate='A'),rules)
        changed=sum(store.import_legacy(row,sha(source/'report.json')) for row in projected)
        imports={'new_revisions':changed,'unchanged':len(projected)-changed,
                 'total_revisions':store.db.execute('SELECT count(*) FROM legacy_label_revisions').fetchone()[0]}
        store.close()
    counts={p:{'raw':0,'deduplicated':0,'mature_before_purge':0,'after_purge':0,'after_embargo':0} for p in ('train','validation','test')}
    for row in projected:
        p=row['partition']; c=counts[p['partition']]; c['raw']+=1; c['deduplicated']+=1
        if row['label_status']=='MATURE':
            c['mature_before_purge']+=1
            if p['exclusion_reason']!='purged_information_overlap': c['after_purge']+=1
            if p['population_eligible']: c['after_embargo']+=1
    result={'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'built_at':datetime.now(UTC).isoformat(),'python':sys.executable,'artifact_hash_verification':verified,
        'source_report_hash':sha(source/'report.json'),'authorized_cutoff':report['authorized_cutoff'],
        'exposure':'EXPOSED_DEVELOPMENT','heldout_prices_read':False,'baseline_runs':baselines,
        'comparison':'212 = A 27 + B 185 separate experiments; M2 is A-only 50 technical opportunities, not 212 fills',
        'raw_opportunities':len(projected),'entry_attempted':sum(r['entry_attempted'] for r in projected),
        'filled':len(projected)-len(unfilled),'mature':sum(r['label_status']=='MATURE' for r in projected),
        'unfilled':len(unfilled),'unfilled_reasons':dict(Counter(reason for r in unfilled for reason in r['reasons'])),
        'pending_results':0,'censored':0,'counterfactual':0,'partitions':counts,
        'legacy_independent_ledger':imports,'model_training_enabled':False,'mathematical_filtering_enabled':False}
    write(out/'audit_report.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('baseline_runs','artifact_hash_verification')},indent=2))


if __name__=='__main__':
    main()
