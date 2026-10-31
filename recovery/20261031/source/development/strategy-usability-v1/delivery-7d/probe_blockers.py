from capture_delivery import ROOT, HERE, POLICIES, read, save, query
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

roles=read(ROOT/'runtime/config/new-epoch-store-paths.json')['stores']
result={'at':datetime.now(timezone.utc).isoformat(),'production_writes':0,'sdk_calls':0,'triggers':[]}
with closing(sqlite3.connect(Path(roles['opening_research']).as_uri()+'?mode=ro',uri=True,timeout=.2)) as db:
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    rows=query(db,"""SELECT evaluation_id,symbol,right_name,evaluated_at,payload_json FROM evaluations
        WHERE policy_hash=? AND session=? AND state='NUMERIC_PASS' LIMIT 20""",(POLICIES['S1'],'2026-10-16'))
    for row in rows:
        value=json.loads(row['payload_json'])
        jobs=[dict(j) for j in query(db,'SELECT state,attempts,next_at,deadline_at,last_error,progress_json FROM qualification_jobs WHERE evaluation_id=?',(row['evaluation_id'],))]
        revisions=[dict(r) for r in query(db,'SELECT checked_at,state,payload_json FROM revisions WHERE evaluation_id=? ORDER BY revision_id LIMIT 30',(row['evaluation_id'],))]
        result['triggers'].append({'evaluation_id':row['evaluation_id'],'symbol':row['symbol'],'right':row['right_name'],
            'at':row['evaluated_at'],'checkpoint':value.get('calculation_bar_end'),'deadline':value.get('deadline_at'),
            'jobs':jobs,'revisions':revisions})
    samples=query(db,"""SELECT payload_json FROM evaluations WHERE policy_hash=? AND session=?
        AND state='INCOMPLETE' AND json_extract(payload_json,'$.reasons[0]')='INTRADAY_NATIVE_PRICE_BASIS_UNVERIFIED' LIMIT 1""",
        (POLICIES['S1'],'2026-10-16'))
    sample=json.loads(samples[0]['payload_json']) if samples else {}
    result['source_sample']={k:sample.get(k) for k in ('evaluation_id','symbol','evaluated_at','calculation_bar_end','input_checks')}
if sample:
    with closing(sqlite3.connect(Path(roles['minute']).as_uri()+'?mode=ro',uri=True,timeout=.2)) as db:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        result['minute_versions']=[dict(r) for r in query(db,"""SELECT evidence_id,open_at,received_at,
            json_extract(payload_json,'$.source') source,
            json_extract(payload_json,'$.sdk_evidence.interface') interface,
            json_extract(payload_json,'$.sdk_evidence.adjustment') adjustment,
            json_extract(payload_json,'$.source_recheck_required') recheck
            FROM one_minute_bars WHERE session=? AND symbol=? AND julianday(open_at)<julianday(?)
            ORDER BY received_at LIMIT 100""",('2026-10-16',sample['symbol'],sample['calculation_bar_end']))]
out=HERE/'blocker-probe-20261016.json'
save(out,result)
print(json.dumps({'path':str(out),'triggers':[{k:t[k] for k in ('symbol','right','checkpoint','at','deadline','jobs')} for t in result['triggers']],
    'source_sample_symbol':sample.get('symbol'),'source_versions':result.get('minute_versions',[])[:6]},ensure_ascii=False))
