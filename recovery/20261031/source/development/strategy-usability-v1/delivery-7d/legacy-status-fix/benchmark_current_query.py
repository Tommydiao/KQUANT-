"""Read-only comparison on TEST_ONLY topology evidence, never active stores."""
import json
from pathlib import Path
import sqlite3
import sys
from time import perf_counter

root = Path(sys.argv[1]).resolve()
assert root.name.startswith('status-reliability-')
path = root/'TEST_ONLY-research.sqlite3'
fields = ('policy_snapshot', 'factor_evidence', 'reference_evidence', 'input_checks',
          'event_coverage', 'contract_qualification', 'initial_eligibility')
remove = ','.join("'$."+name+"'" for name in sorted(fields))
old = f'''SELECT json_remove(e.payload_json,{remove}),
 r.revision_id,r.payload_json,q.payload_json,child.revision_id,child.payload_json
 FROM evaluations e
 LEFT JOIN revisions r ON r.revision_id=(SELECT MAX(revision_id) FROM revisions WHERE evaluation_id=e.evaluation_id)
 LEFT JOIN qualified_claims q ON q.evaluation_id=e.evaluation_id
 LEFT JOIN revisions child ON child.revision_id=(SELECT MAX(revision_id) FROM revisions
 WHERE evaluation_id=json_extract(e.payload_json,'$.strategy_comparison.s1.evaluation_id'))
 WHERE e.policy_hash=? AND e.session=? AND julianday(e.evaluated_at)>=julianday(?) AND (
 (e.state='NUMERIC_PASS' AND json_extract(e.payload_json,'$.deadline_at')>?) OR
 (json_extract(e.payload_json,'$.strategy_comparison.s1.state')='NUMERIC_PASS'
 AND json_extract(e.payload_json,'$.strategy_comparison.s1.deadline_at')>?)) LIMIT 223'''
new = f'''WITH live AS MATERIALIZED (
 SELECT evaluation_id,state,json_remove(payload_json,{remove}) AS payload_json FROM evaluations
 WHERE policy_hash=? AND session=? AND julianday(evaluated_at)>=julianday(?))
 SELECT e.payload_json,r.revision_id,r.payload_json,q.payload_json,child.revision_id,child.payload_json
 FROM live e
 LEFT JOIN revisions r ON r.revision_id=(SELECT MAX(revision_id) FROM revisions WHERE evaluation_id=e.evaluation_id)
 LEFT JOIN qualified_claims q ON q.evaluation_id=e.evaluation_id
 LEFT JOIN revisions child ON child.revision_id=(SELECT MAX(revision_id) FROM revisions
 WHERE evaluation_id=json_extract(e.payload_json,'$.strategy_comparison.s1.evaluation_id'))
 WHERE (e.state='NUMERIC_PASS' AND json_extract(e.payload_json,'$.deadline_at')>?) OR
 (json_extract(e.payload_json,'$.strategy_comparison.s1.state')='NUMERIC_PASS'
 AND json_extract(e.payload_json,'$.strategy_comparison.s1.deadline_at')>?) LIMIT 223'''
with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.1) as db:
    db.execute('PRAGMA query_only=ON')
    db.execute('BEGIN')
    samples = db.execute("SELECT DISTINCT policy_hash,session,evaluated_at FROM evaluations WHERE state='NUMERIC_PASS' LIMIT 6").fetchall()
    output = []
    for policy,session,stamp in samples:
        params = (policy,session,stamp,stamp,stamp)
        timings = {'old': [], 'new': []}
        for _ in range(3):
            results = {}
            for label,sql in [('old',old),('new',new)]:
                started = perf_counter()
                results[label] = db.execute(sql,params).fetchall()
                timings[label].append(perf_counter()-started)
            assert results['old'] == results['new'], 'RESULT_CHANGED'
        output.append(dict(policy=policy,session=session,stamp=stamp,rows=len(results['old']),seconds=timings))
    db.rollback()
print(json.dumps(dict(test_only=True,production_writes=0,results=output),indent=2))
