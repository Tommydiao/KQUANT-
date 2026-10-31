"""Bounded read-only SQL profile of the running TEST_ONLY hour, not live stores."""
from contextlib import closing
from datetime import timedelta
import json
import sqlite3
from time import perf_counter
from bootstrap import activate

HERE, BASE, ROOT = activate()
from kquant import options_one_minute as common
from kquant.options_opening_trend_summary import DETAIL_FIELDS

out = ROOT/'source/evidence/new-machine-20261008/monday-sol61-hour-dd0a-20261018'
path = out/'TEST_ONLY-research.sqlite3'
assert path.name.startswith('TEST_ONLY-') and (out/'TEST_ONLY.json').is_file()
fields = tuple('$.'+name for name in sorted(DETAIL_FIELDS))
sql = f"""SELECT json_remove(e.payload_json,{','.join('?' for _ in fields)}),
    r.revision_id,r.payload_json,q.payload_json,child.revision_id,child.payload_json
    FROM evaluations e
    LEFT JOIN revisions r ON r.revision_id=(SELECT MAX(revision_id) FROM revisions WHERE evaluation_id=e.evaluation_id)
    LEFT JOIN qualified_claims q ON q.evaluation_id=e.evaluation_id
    LEFT JOIN revisions child ON child.revision_id=(SELECT MAX(revision_id) FROM revisions
        WHERE evaluation_id=json_extract(e.payload_json,'$.strategy_comparison.s1.evaluation_id'))
    WHERE e.policy_hash=? AND e.session=?
    AND julianday(e.evaluated_at)>=julianday(?) AND julianday(e.evaluated_at)<=julianday(?) AND (
    (e.state='NUMERIC_PASS' AND json_extract(e.payload_json,'$.deadline_at')>?) OR
    (json_extract(e.payload_json,'$.strategy_comparison.s1.state')='NUMERIC_PASS'
    AND json_extract(e.payload_json,'$.strategy_comparison.s1.deadline_at')>?)) LIMIT 223"""
report = dict(test_only=True, source=str(path), source_writes=0,
    performance_acceptance=False, lock_wait_seconds=None, samples=[])
with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.1)) as db:
    db.execute('PRAGMA query_only=ON')
    until = perf_counter()+5
    db.set_progress_handler(lambda: int(perf_counter()>until), 1000)
    db.execute('BEGIN')
    recent = db.execute("SELECT policy_hash,session,evaluated_at,payload_json FROM evaluations ORDER BY rowid DESC LIMIT 32").fetchall()
    sample = next((row[:3] for row in recent if json.loads(row[3]).get('strategy_comparison')), None)
    if not sample:
        raise ValueError('NO_NUMERIC_SAMPLE')
    policy, session, stamp = sample
    now = common.timestamp(stamp)+timedelta(seconds=10)
    params = (*fields, policy, session, (now-timedelta(seconds=300)).isoformat(), now.isoformat(), now.isoformat(), now.isoformat())
    report['policy_hash'] = policy
    report['session'] = session
    report['as_of'] = now.isoformat()
    report['plan'] = [list(row) for row in db.execute('EXPLAIN QUERY PLAN '+sql, params)]
    for _ in range(3):
        count = [0]
        until = perf_counter()+1
        def progress():
            count[0] += 100
            return int(perf_counter()>until)
        db.set_progress_handler(progress,100)
        started = perf_counter()
        rows = db.execute(sql, params).fetchall()
        sql_ms = (perf_counter()-started)*1000
        started = perf_counter()
        decoded = [tuple(json.loads(x) if isinstance(x,str) else x for x in row) for row in rows]
        report['samples'].append(dict(sql_ms=sql_ms, decode_ms=(perf_counter()-started)*1000,
            rows=len(rows), returned_bytes=sum(len(x.encode()) for row in rows for x in row if isinstance(x,str)),
            approximate_vm_instructions=count[0]))
    db.rollback()
report['limits'] = 'Read-only bounded samples during an isolated running hour; not a reproduction of the original request scheduling or a lock attribution.'
target = HERE/'evidence/hour-current-s0-readonly-profile.json'
target.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
