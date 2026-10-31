"""Bounded read-only delivery accounting; never initializes or repairs a store."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone, date
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import urllib.request

ROOT = Path(r'E:\kquant 1007\KQUANT-Resume-Latest')
BASE = ROOT / 'source/development/workspace'
HERE = Path(__file__).parent
sys.path.insert(0, str(BASE))
from kquant.market_clock import is_trading_day, session_bounds_utc

POLICIES = {'S0': '9fcbe3bf87f5509bfda4ef31e4cd7956dd2be2bfcc25a9a2472123a61111b261',
            'S1': 'fa6c0eda83925d68716ccc8fdce45ed1cbe78fc4f3f90ee47cec24c6641a0c43'}

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))

def save(path, value):
    with path.open('x', encoding='utf-8') as out:
        json.dump(value, out, indent=2, ensure_ascii=False)

def query(db, sql, parameters=()):
    end = time.monotonic() + 4
    db.set_progress_handler(lambda: int(time.monotonic() > end), 1000)
    return db.execute(sql, parameters).fetchall()

def summarize(rows, applicable, checkpoints):
    grouped = defaultdict(list)
    for row in rows:
        if row['symbol'] not in applicable or row['checkpoint'] not in checkpoints:
            continue
        grouped[row['symbol'], row['right'], row['checkpoint']].append(row)
    first, latest, timely, triggers = {}, {}, {}, set()
    reasons = Counter()
    for key, versions in grouped.items():
        versions.sort(key=lambda r: (r['evaluated_at'], r['evaluation_id']))
        first[key], latest[key] = versions[0], versions[-1]
        end = stamp(key[2]) + timedelta(seconds=300)
        valid = [r for r in versions if stamp(key[2]) <= stamp(r['evaluated_at']) < end]
        if valid:
            timely[key] = valid[-1]
        if any(r['state'] == 'NUMERIC_PASS' for r in valid):
            triggers.add(key)
        reasons.update(json.loads(versions[-1]['reasons'] or '[]'))
    def full(row):
        # S0 has no FULL label; explicit complete outcomes and actual factors are required.
        return bool(row and row['state'] in ('NO_TRIGGER', 'NUMERIC_PASS', 'EXPIRED')
                    and row['momentum'] is not None and row['q'] is not None
                    and row['factor_state'] not in ('PARTIAL', 'PARTIAL_PRICE_COMPONENTS'))
    complete_keys = {k for k, r in timely.items() if full(r)}
    expected = len(applicable) * len(checkpoints) * 2
    by_checkpoint = [{
        'checkpoint': point, 'expected': len(applicable) * 2,
        'recorded': sum(k[2] == point for k in grouped),
        'full_timely': sum(k[2] == point for k in complete_keys),
        'technical_triggers': sum(k[2] == point for k in triggers)} for point in checkpoints]
    complete_objects = [s for s in applicable if all((s, right, p) in complete_keys
        for right in ('CALL', 'PUT') for p in checkpoints)]
    return {'expected_direction_checkpoints': expected, 'recorded_direction_checkpoints': len(grouped),
        'missing_direction_checkpoints': expected-len(grouped),
        'first_full': sum(full(r) for r in first.values()),
        'latest_full_including_late': sum(full(r) for r in latest.values()),
        'full_timely': len(complete_keys), 'completion_ratio': len(complete_keys)/expected if expected else None,
        'complete_objects_all_checkpoints': len(complete_objects),
        'object_completion_ratio': len(complete_objects)/len(applicable) if applicable else None,
        'technical_trigger_positions': len(triggers),
        'unique_technical_events': len({k[:2] for k in triggers}),
        'latest_states': dict(Counter(r['state'] for r in latest.values())),
        'latest_reasons': dict(reasons), 'checkpoints': by_checkpoint}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    worker_path = ROOT / 'runtime/work/option_foundation/runtime/one-minute-worker.json'
    worker = read(worker_path)
    scope_path = HERE / 'denominator.json'
    if not scope_path.exists():
        raise ValueError('FROZEN_DENOMINATOR_MISSING_DO_NOT_RESET')
    scope = read(scope_path)
    if scope['constraint_sha256'] != sha(HERE/'constraint.json'):
        raise ValueError('IMMUTABLE_DELIVERY_CONSTRAINT_CHANGED')
    roles = read(ROOT/'runtime/config/new-epoch-store-paths.json')
    entry = read(BASE/'config/local_workspace_entry.json')
    services = read(ROOT/'runtime/work/option_foundation/runtime/services.json')
    result = {'captured_at': now.isoformat(), 'session': args.session,
        'constraint': read(HERE/'constraint.json'), 'scope_sha256': sha(scope_path),
        'scope_registered': len(scope['items']), 'scope_applicable': len(scope['applicable']),
        'scope_identity_unconfirmed': [x['symbol'] for x in scope['items'] if x['identity_status'] != 'verified'],
        'runtime': services, 'worker': {k:worker['worker'].get(k) for k in (
            'state','stage','loop_count','first_loop_at','last_cycle_at','thread_alive','runtime_health',
            'subscribed_symbols','last_bar_age_seconds','research_progress')},
        'live_entry_candidate': entry['candidate_id'], 'entry_sha256': sha(BASE/'config/local_workspace_entry.json'),
        'production_writes': 0, 'sdk_requests': 0, 'metrics': {}, 'errors': []}
    windows = []
    constraint = result['constraint']
    for offset in range(1, 8):
        day = stamp(constraint['t0_utc']).date() + timedelta(days=offset)
        if is_trading_day(day):
            start, close = session_bounds_utc(day)
            windows.append({'session': day.isoformat(), 'open_utc': start.isoformat(),
                'close_utc': close.isoformat(), 'checkpoints_utc': [(start+timedelta(minutes=m)).isoformat() for m in (5,10,15,20,25)]})
    result['remaining_project_calendar_windows'] = windows
    try:
        with urllib.request.urlopen('http://127.0.0.1:8001/api/health/live', timeout=2) as response:
            result['live_http'] = response.status
    except Exception as exc:
        result['live_http_error'] = type(exc).__name__
    if is_trading_day(date.fromisoformat(args.session)):
        start, close = session_bounds_utc(date.fromisoformat(args.session))
        points = [(start+timedelta(minutes=m)).isoformat() for m in (5,10,15,20,25)]
        path = Path(roles['stores']['opening_research'])
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.2)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            for variant, policy in POLICIES.items():
                try:
                    rows = query(db, '''SELECT evaluation_id,symbol,right_name AS "right",evaluated_at,state,
                        json_extract(payload_json,'$.calculation_bar_end') AS checkpoint,
                        json_extract(payload_json,'$.factor_evidence.state') AS factor_state,
                        json_extract(payload_json,'$.factor_evidence.momentum') AS momentum,
                        json_extract(payload_json,'$.factor_evidence.close_position') AS q,
                        json_extract(payload_json,'$.reasons') AS reasons
                        FROM evaluations WHERE policy_hash=? AND session=? LIMIT 20001''', (policy,args.session))
                    if len(rows)>20000:
                        raise ValueError('EVALUATION_READ_LIMIT')
                    result['metrics'][variant] = summarize([dict(r) for r in rows],scope['applicable'],points)
                    refs = query(db, '''SELECT COUNT(DISTINCT e.symbol || '|' || e.right_name) n
                        FROM revisions r JOIN evaluations e ON e.evaluation_id=r.evaluation_id
                        WHERE e.policy_hash=? AND e.session=?
                        AND julianday(r.checked_at)>=julianday(json_extract(e.payload_json,'$.calculation_bar_end'))
                        AND julianday(r.checked_at)<julianday(json_extract(e.payload_json,'$.deadline_at'))
                        AND json_extract(r.payload_json,'$.reference_contract.contract_id') IS NOT NULL
                        AND json_extract(r.payload_json,'$.reference_contract.expiry_date') IS NOT NULL
                        AND json_extract(r.payload_json,'$.reference_contract.strike') IS NOT NULL
                        AND json_extract(r.payload_json,'$.reference_contract.right') IS NOT NULL
                        AND json_extract(r.payload_json,'$.reference_contract.bid') IS NOT NULL
                        AND json_extract(r.payload_json,'$.reference_contract.ask') IS NOT NULL''', (policy,args.session))
                    result['metrics'][variant]['reference_contract_events'] = refs[0]['n']
                    result['metrics'][variant]['reference_contract_unit'] = 'UNIQUE_SYMBOL_DIRECTION_WITH_REQUIRED_FIELDS_BEFORE_ORIGINAL_DEADLINE'
                    result['metrics'][variant]['page_delivered'] = None
                    result['metrics'][variant]['page_delivery_reason'] = 'NO_PERSISTENT_RENDER_ACK_PROOF'
                except (sqlite3.Error, ValueError) as exc:
                    result['errors'].append({'variant':variant,'type':type(exc).__name__,'message':str(exc)[:160]})
                    result['metrics'][variant] = {'query_unconfirmed':True,'full_timely':None}
            try:
                result['journal_states'] = [dict(r) for r in query(db,
                    'SELECT state,reason,count(*) n FROM two_hour_jobs WHERE session=? GROUP BY state,reason', (args.session,))]
            except sqlite3.Error as exc:
                result['errors'].append({'journal': type(exc).__name__})
    else:
        result['market_state'] = 'NOT_A_TRADING_DAY'
    output = HERE / ('audit-'+now.strftime('%Y%m%dT%H%M%SZ')+'.json')
    save(output,result)
    print(json.dumps({'evidence':str(output),'metrics':result['metrics'],'errors':result['errors'],
        'calendar':windows,'journal':result.get('journal_states')},ensure_ascii=False))

if __name__ == '__main__':
    main()
