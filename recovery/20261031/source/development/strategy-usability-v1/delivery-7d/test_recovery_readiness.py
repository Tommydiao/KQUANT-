from datetime import datetime, timedelta, timezone
from contextlib import closing
import json
import sqlite3

from kquant import options_one_minute as common
from kquant.options_opening_trend_recovery import TrendRecoveryLane
from kquant.options_opening_momentum import load_policy

OPEN = datetime(2026,10,16,13,30,tzinfo=timezone.utc)
NOW = OPEN + timedelta(minutes=5,seconds=1)

def bar(i=0, pull=False):
    at = OPEN+timedelta(minutes=i)
    return {'symbol':'TEST','interval':'1m','open_at':at.isoformat(),
        'available_at':(at+timedelta(minutes=1)).isoformat(),'received_at':NOW.isoformat(),
        'request_started_at':(NOW-timedelta(seconds=.1)).isoformat(),
        'closed':True,'open':100,'high':102,'low':99,'close':101,'volume':10,'turnover':1000,
        'sdk_evidence':{'provider_symbol':'TEST.US','adjustment':'NoAdjust' if pull else 'NOT_PROVIDED',
            'interface':'QuoteContext.candlesticks' if pull else 'QuoteContext.set_on_candlestick'}}

def lane(tmp_path, calls):
    minute = tmp_path/'minute.sqlite3'
    with closing(sqlite3.connect(minute)) as db:
        db.execute('CREATE TABLE one_minute_bars(evidence_id TEXT PRIMARY KEY,session TEXT,symbol TEXT,open_at TEXT,received_at TEXT,payload_json TEXT)')
    def transport(symbol, at):
        calls.append((symbol,at))
        return {'status':'RECOVERED','bars':[bar(i,True) for i in range(5)]}
    value = TrendRecoveryLane(minute,transport,queue_path=tmp_path/'research.sqlite3',clock=lambda:NOW)
    return value

def test_complete_pushes_enqueue_and_cannot_short_circuit_pull(tmp_path):
    calls=[]
    value=lane(tmp_path,calls)
    try:
        pushes=[bar(i) for i in range(5)]
        common.save_bars(pushes,'2026-10-16',value.evidence_path)
        task=value.task('TEST',OPEN+timedelta(minutes=4),{common.timestamp(b['open_at']):b for b in pushes},load_policy(),'scope')
        assert len(task['missing_bars']) == 5
        assert task['deadline_at'] == '2026-10-16T13:40:00+00:00'
        job={'symbol':'TEST','session':'2026-10-16','deadline_at':task['deadline_at'],'payload':task}
        response=value._fetch(job)
        assert len(calls) == 1
        assert len(response['bars']) == 5
    finally:
        value.close()

def test_existing_qualified_pull_is_reused_without_provider_call(tmp_path):
    calls=[]
    value=lane(tmp_path,calls)
    try:
        pulls=[bar(i,True) for i in range(5)]
        common.save_bars(pulls,'2026-10-16',value.evidence_path)
        assert value.task('TEST',OPEN+timedelta(minutes=4),{common.timestamp(b['open_at']):b for b in pulls},load_policy(),'scope') is None
        job={'symbol':'TEST','session':'2026-10-16','deadline_at':(OPEN+timedelta(minutes=10)).isoformat(),
            'payload':{'missing_bars':[b['open_at'] for b in pulls]}}
        assert value._fetch(job)['status'] == 'RECOVERED'
        assert calls == []
    finally:
        value.close()

def test_durable_completion_does_not_mark_unverified_push_done(tmp_path):
    calls=[]
    value=lane(tmp_path,calls)
    try:
        task=value.task('TEST',OPEN+timedelta(minutes=4),{},load_policy(),'scope')
        selected,_=value._cycle({'job':task},None,'2026-10-16',load_policy(),'scope',False)
        assert selected
        # Transport returned unqualified but closed bars. Keep them as evidence, not success.
        value._cycle({},(selected,{'status':'RECOVERED','bars':[bar(i) for i in range(5)]}),
            '2026-10-16',load_policy(),'scope',False)
        with closing(sqlite3.connect(value.queue_path)) as db:
            state,deadline=db.execute('SELECT state,deadline_at FROM two_hour_jobs WHERE job_id=?',('job',)).fetchone()
        assert state == 'PENDING'
        assert deadline == task['deadline_at']
    finally:
        value.close()

def test_early_request_recheck_and_expiry_do_not_become_ready(tmp_path):
    calls=[]
    value=lane(tmp_path,calls)
    try:
        original=bar(0,True)
        assert value.bar_ready('TEST',OPEN,original)
        assert not value.bar_ready('TEST',OPEN,{**original,'request_started_at':OPEN.isoformat()})
        assert not value.bar_ready('TEST',OPEN,{**original,'source_recheck_required':True})
        assert not value.bar_ready('OTHER',OPEN,original)
        job={'symbol':'TEST','session':'2026-10-16','deadline_at':NOW.isoformat(),'payload':{}}
        assert value._fetch(job)['status'] == 'ORIGINAL_DEADLINE_EXCEEDED'
        assert calls == []
    finally:
        value.close()
