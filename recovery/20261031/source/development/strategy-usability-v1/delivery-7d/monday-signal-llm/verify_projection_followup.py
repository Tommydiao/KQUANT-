"""Exact-output comparison on one pinned TEST_ONLY database snapshot."""
from contextlib import closing, contextmanager
from copy import deepcopy
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from time import perf_counter
from unittest.mock import patch
from bootstrap import activate

HERE, BASE, ROOT=activate()
from kquant import bounded_sqlite, options_one_minute as common
from kquant import options_opening_trend_store as original
from kquant import options_opening_trend_summary as original_summary
from kquant import options_intraday_comparison as original_comparison
from kquant.options_opening_momentum import load_policy


def load(name):
    key='kquant._followup_'+name
    path=HERE/'projection-followup/patches/kquant'/('options_'+name+'.py')
    spec=importlib.util.spec_from_file_location(key,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[key]=module
    spec.loader.exec_module(module)
    return module


def deterministic(value):
    copy=deepcopy(value)
    for key in ('sql_seconds','json_projection_seconds','ai_summary_seconds'):
        copy.get('current_projection',{}).pop(key,None)
    return common.canonical(copy)


def main():
    out=ROOT/'source/evidence/new-machine-20261008/monday-sol61-hour-dd0a-20261018'
    path=out/'TEST_ONLY-research.sqlite3'
    assert (out/'TEST_ONLY.json').is_file()
    common.ROOT=out
    newer=load('opening_trend_store')
    summary=load('opening_trend_summary')
    comparison=load('intraday_comparison')
    report=dict(test_only=True, source_writes=0, production_writes=0,
        source=str(path), variant='UNFROZEN_THREE_MODULE_PROJECTION_FOLLOWUP', cases=[])
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        policy=load_policy()
        raw=db.execute('SELECT payload_json FROM evaluations WHERE policy_hash=? ORDER BY rowid DESC LIMIT 1',(policy['policy_hash'],)).fetchone()[0]
        sample=json.loads(raw)
        opening=common.timestamp(sample['calculation_bar_end']).replace(hour=13,minute=30,second=0,microsecond=0)
        scenarios=[(opening+timedelta(minutes=point,seconds=11),sample['scope_hash']) for point in (5,10,15,20,25)]
        scenarios.extend([(opening+timedelta(minutes=30,seconds=1),sample['scope_hash']),
            (opening+timedelta(minutes=25,seconds=11),'TEST_ONLY_WRONG_SCOPE')])
        @contextmanager
        def pinned_read(selected,*,seconds):
            if Path(selected)!=path:
                raise ValueError('PINNED_SOURCE_MISMATCH')
            until=perf_counter()+seconds
            db.set_progress_handler(lambda:int(perf_counter()>until),1000)
            try:
                yield db
            finally:
                db.set_progress_handler(None,0)
        with patch.object(bounded_sqlite,'read_connection',pinned_read):
            for now,scope in scenarios:
                kwargs=dict(path=path,session=sample['session'],scope_hash=scope,now=now,policy=policy)
                started=perf_counter()
                before=original.current_cards(**kwargs)
                old_ms=(perf_counter()-started)*1000
                with patch.object(original_summary,'compact_record',summary.compact_record), patch.object(original_comparison,'compact_comparison',comparison.compact_comparison):
                    started=perf_counter()
                    after=newer.current_cards(**kwargs)
                    new_ms=(perf_counter()-started)*1000
                assert deterministic(before)==deterministic(after),'RESULT_CHANGED:'+now.isoformat()
                report['cases'].append(dict(as_of=now.isoformat(),scope_matches=scope==sample['scope_hash'],
                    total=before['evaluations_total'],displayed=len(before['evaluations']),
                    before_ms=old_ms,after_ms=new_ms,equivalent=True))
        # The projection must not mutate shared immutable evidence while dropping
        # fields; compare randomized-shaped nested records, including absent/null.
        examples=[json.loads(row[0]) for row in db.execute('SELECT payload_json FROM evaluations ORDER BY rowid DESC LIMIT 100')]
        examples.extend([{'strategy_comparison':None},{'strategy_comparison':{}},{}])
        for value in examples:
            snapshot=deepcopy(value)
            expected=original_summary.compact_record(value)
            with patch.object(original_comparison,'compact_comparison',comparison.compact_comparison):
                observed=summary.compact_record(value)
            assert common.canonical(expected)==common.canonical(observed),'COMPACT_RESULT_CHANGED'
            assert value==snapshot,'SOURCE_MUTATED'
        report['immutable_record_cases']=len(examples)
        db.rollback()
    report.update(passed=True,acceptance=False,
        limits='Local pinned-snapshot equivalence and function timing only; frozen dd0a hour is unchanged and retains every failure. This is not a followup matching hour or market result.')
    target=HERE/'evidence/projection-followup-equivalence.json'
    target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
