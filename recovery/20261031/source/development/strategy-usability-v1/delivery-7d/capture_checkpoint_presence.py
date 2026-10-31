"""Bounded existing-ledger checkpoint presence; no SDK, initialization or replay."""
import argparse
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
import sqlite3
import sys
from time import monotonic

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = ROOT/'source/development/workspace'
sys.path.insert(0, str(BASE))
from kquant.market_clock import is_trading_day, session_bounds_utc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', required=True)
    parser.add_argument('--minute', type=int, required=True, choices=(5, 10, 15, 20, 25))
    args = parser.parse_args()
    day = date.fromisoformat(args.session)
    if not is_trading_day(day):
        raise ValueError('NO_TRADING_CHECKPOINT')
    point = session_bounds_utc(day)[0]+timedelta(minutes=args.minute)
    now = datetime.now(UTC)
    if now < point:
        raise ValueError('FUTURE_CHECKPOINT_NO_EVIDENCE_CREATED')
    role_map = json.loads((ROOT/'runtime/config/new-epoch-store-paths.json').read_text())
    path = Path(role_map['stores']['opening_research']).resolve(strict=True)
    if not path.is_relative_to((ROOT/'runtime').resolve()):
        raise ValueError('OUTSIDE_APPROVED_RUNTIME')
    result = dict(schema='KQUANT_EXISTING_CHECKPOINT_PRESENCE_V1',
        observed_at=now.isoformat(), session=args.session, checkpoint=point.isoformat(),
        observation_clock='SYSTEM_UTC_ONLY_NOT_VERIFIED_BOUND_MARKET_TIME',
        observed_late_seconds=(now-point).total_seconds(), database=str(path),
        production_writes=0, sdk_requests=0, tasks_created=0, history_replayed=False,
        query_confirmed=False, checkpoint_evaluation_rows=None, session_job_rows=None)
    result.update(evaluation_query_confirmed=False, job_query_confirmed=False)
    started = monotonic()
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.2)) as db:
            db.execute('PRAGMA query_only=ON')
            end = monotonic()+1
            db.set_progress_handler(lambda: int(monotonic() > end), 500)
            rows = db.execute('''SELECT policy_hash,state,count(*) FROM evaluations
                WHERE session=? AND julianday(json_extract(payload_json,'$.calculation_bar_end'))=julianday(?)
                GROUP BY policy_hash,state''', (args.session,point.isoformat())).fetchall()
            result.update(evaluation_query_confirmed=True,
                checkpoint_evaluation_rows=sum(row[2] for row in rows),
                evaluations=[dict(policy_hash=p,state=s,rows=n) for p,s,n in rows])
            jobs = db.execute('''SELECT json_extract(payload_json,'$.kind'),state,count(*) FROM two_hour_jobs
                WHERE session=? GROUP BY json_extract(payload_json,'$.kind'),state''', (args.session,)).fetchall()
            result.update(query_confirmed=True, job_query_confirmed=True,
                session_job_rows=sum(row[2] for row in jobs),
                session_jobs=[dict(kind=k,state=s,rows=n) for k,s,n in jobs])
    except (sqlite3.Error, ValueError) as exc:
        result.update(query_error_type=type(exc).__name__,
            sqlite_errorname=getattr(exc,'sqlite_errorname',None))
    result['query_elapsed_seconds'] = monotonic()-started
    result['inference_limits'] = ('Presence only; combine actual process/listener evidence. '
        'Session-wide job counts are not checkpoint-specific or completed mathematics. '
        'A failed query is unconfirmed, never zero. Never fill future points or market signals.')
    target = HERE/('checkpoint-presence-'+day.strftime('%Y%m%d')+'-'+point.strftime('%H%M')+'Z-'+now.strftime('%H%M%S')+'.json')
    with target.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2)
    print(json.dumps(dict(path=str(target),**result)))


if __name__ == '__main__':
    main()
