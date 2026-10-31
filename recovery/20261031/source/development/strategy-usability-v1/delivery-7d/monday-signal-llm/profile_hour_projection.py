"""Bounded full current-card read/profile against only the isolated hour store."""
from contextlib import closing
import cProfile
from datetime import timedelta
import io
import json
import pstats
import sqlite3
from time import perf_counter
from bootstrap import activate

HERE, BASE, ROOT = activate()
from kquant import options_one_minute as common
from kquant import options_opening_trend_store as store
from kquant.options_opening_momentum import load_policy

out=ROOT/'source/evidence/new-machine-20261008/monday-sol61-hour-dd0a-20261018'
path=out/'TEST_ONLY-research.sqlite3'
assert path.name.startswith('TEST_ONLY-') and (out/'TEST_ONLY.json').is_file()
common.ROOT=out
with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
    db.execute('PRAGMA query_only=ON')
    recent=db.execute('SELECT payload_json FROM evaluations ORDER BY rowid DESC LIMIT 32').fetchall()
    sample=next(value for row in recent if (value:=json.loads(row[0])).get('strategy_comparison'))
now=common.timestamp(sample['evaluated_at'])+timedelta(seconds=10)
report=dict(test_only=True, source=str(path), source_writes=0, live_store_access=False,
    source_policy_hash=sample['policy_hash'], expected_policy_hash=load_policy()['policy_hash'], samples=[])
assert report['source_policy_hash']==report['expected_policy_hash']
profile=cProfile.Profile()
for index in range(3):
    started=perf_counter()
    try:
        if index==2:
            profile.enable()
        value=store.current_cards(path=path,session=sample['session'],scope_hash=sample['scope_hash'],
            now=now,policy=load_policy())
        report['samples'].append(dict(elapsed_ms=(perf_counter()-started)*1000,
            evaluations_total=value['evaluations_total'], displayed=len(value['evaluations']),
            projection=value['current_projection'], profiled=index==2))
    except Exception as exc:
        report['samples'].append(dict(elapsed_ms=(perf_counter()-started)*1000,
            error_type=type(exc).__name__, profiled=index==2))
    finally:
        profile.disable()
stream=io.StringIO()
pstats.Stats(profile,stream=stream).sort_stats('cumulative').print_stats(35)
report['profile']=stream.getvalue()
report['limits']='Current frozen production function, bounded TEST_ONLY read samples. This is not attribution of the original wall-clock failures, market latency, or an acceptance pass.'
target=HERE/'evidence/hour-full-current-profile.json'
target.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
