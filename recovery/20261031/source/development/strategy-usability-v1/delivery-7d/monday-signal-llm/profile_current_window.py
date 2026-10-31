"""Readonly original evidence, targeted tables in memory; no database file copy."""
import ast
from contextlib import closing
from datetime import datetime, timedelta
import json
import sqlite3
from time import perf_counter
from bootstrap import activate
HERE, BASE, ROOT = activate()
source=ROOT/'source/evidence/new-machine-20261008/status-reliability-hour-4549-20261017/TEST_ONLY-research.sqlite3'
tree=ast.parse((HERE.parent/'legacy-status-fix/benchmark_current_query.py').read_text())
namespace={}
for node in tree.body:
    if isinstance(node,ast.Assign) and any(isinstance(x,ast.Name) and x.id in ('fields','remove','old') for x in node.targets):
        exec(compile(ast.Module(body=[node],type_ignores=[]),'query-extraction','exec'),namespace)
sql=namespace['old']
report={'test_only':True,'source':str(source),'source_writes':0,'live_store_access':False,'samples':[]}
with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=.1)) as src, closing(sqlite3.connect(':memory:')) as db:
    src.execute('PRAGMA query_only=ON')
    src.execute('BEGIN')
    report['table_rows']={}
    for table in ('evaluations','revisions','qualified_claims'):
        db.execute(src.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone()[0])
        rows=src.execute('SELECT * FROM '+table).fetchall()
        report['table_rows'][table]=len(rows)
        if rows:
            db.executemany('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in rows[0])+')',rows)
        for ddl, in src.execute('SELECT sql FROM sqlite_master WHERE type=\'index\' AND tbl_name=? AND sql IS NOT NULL',(table,)):
            db.execute(ddl)
    src.rollback()
    samples=db.execute("SELECT DISTINCT policy_hash,session,evaluated_at FROM evaluations WHERE state='NUMERIC_PASS' ORDER BY evaluated_at DESC LIMIT 5").fetchall()
    saved=[]
    for label in ('before','indexed'):
        if label=='indexed':
            db.execute('CREATE INDEX trend_current_time ON evaluations(policy_hash,session,julianday(evaluated_at))')
        for index,(policy,session,stamp) in enumerate(samples):
            now=datetime.fromisoformat(stamp)+timedelta(seconds=10)
            params=(policy,session,(now-timedelta(seconds=300)).isoformat(),now.isoformat(),now.isoformat())
            measured=[]
            for repeat in range(5):
                steps=[0]
                def progress():
                    steps[0]+=100
                    return 0
                db.set_progress_handler(progress,100)
                started=perf_counter()
                rows=db.execute(sql,params).fetchall()
                query_ms=(perf_counter()-started)*1000
                db.set_progress_handler(None,0)
                started=perf_counter()
                decoded=[tuple(json.loads(v) if isinstance(v,str) else v for v in row) for row in rows]
                measured.append({'query_ms':query_ms,'json_ms':(perf_counter()-started)*1000,'vm_instructions_approx':steps[0]})
            canonical=sorted(json.dumps(x,sort_keys=True) for x in decoded)
            if label=='before':
                saved.append(canonical)
            else:
                assert canonical==saved[index], 'RESULT_SET_CHANGED'
            report['samples'].append({'mode':label,'stamp':stamp,'rows':len(rows),'measurements':measured,
                'explain_query_plan':[list(row) for row in db.execute('EXPLAIN QUERY PLAN '+sql,params)]})
report['result_equivalence']=True
report['limits']='Isolated memory SQL/JSON measurements, not TCP, live locks, or full-hour performance.'
output=HERE/'evidence/current-window-profile.json'
output.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'output':str(output),'rows':report['table_rows'],'samples':[{'mode':x['mode'],'rows':x['rows'],'max_query_ms':max(y['query_ms'] for y in x['measurements'])} for x in report['samples']]}))
