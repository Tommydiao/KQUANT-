"""No provider calls: real outbox and worker, no contract prerequisite."""
from copy import deepcopy
from contextlib import closing
from datetime import timedelta
import json
import sqlite3
from test_weekend_sidecar import Harness,wait_for
from kquant import options_research_ai_worker as worker


def test_actual_worker_consumes_math_without_contract(tmp_path,monkeypatch):
    h=Harness(tmp_path,monkeypatch)
    with closing(sqlite3.connect(h.research)) as db,db:
        db.execute('UPDATE revisions SET payload_json=?',(json.dumps({'state':'PENDING','checked_at':h.now.isoformat()}),))
    h.start()
    try:
        wait_for(lambda:len(h.published)==1)
        assert len(h.calls)==1 and h.calls[0][0]['reference_contract'] is None
        assert h.published[0]['delivery_state']=='CURRENT_TECHNICAL_REVIEW'
        with closing(sqlite3.connect(h.copilot)) as db:
            result=json.loads(db.execute('SELECT payload_json FROM ai_assessments').fetchone()[0])['result']
        assert result['current_opportunity'] is False
        assert result['qualified_signal'] is False
    finally:
        h.close()


def test_auto_once_across_contract_refresh_generation_and_variants(tmp_path,monkeypatch):
    h=Harness(tmp_path,monkeypatch)
    e=worker.captured_event(h.events[0],{},versions=h.captured()['_ai_versions'],automatic=True)
    e['economic_opportunity_id']='TEST_ONLY_ECONOMIC'
    assert h.tasks.enqueue(e,now=h.now)=='QUEUED'
    refresh=deepcopy(e)
    refresh['reference_contract']={'contract_id':'TEST_ONLY_CONTRACT'}
    assert h.tasks.enqueue(refresh,now=h.now)=='ECONOMIC_EVENT_ALREADY_REVIEWED'
    refresh['runtime_inputs']['input_generation']=2
    assert h.tasks.enqueue(refresh,now=h.now)=='MANUAL_REVIEW_REQUIRED'
    refresh.update(event_id='TEST_ONLY_OTHER_VARIANT',evaluation_id='TEST_ONLY_OTHER_EVAL')
    assert h.tasks.enqueue(refresh,now=h.now)=='MANUAL_REVIEW_REQUIRED'
    with closing(sqlite3.connect(h.copilot)) as db:
        assert db.execute('SELECT count(*) FROM llm_work_queue').fetchone()[0]==1
        assert db.execute('SELECT state FROM llm_work_queue').fetchone()[0]=='REJECTED'
    refresh.pop('_ai_trigger_mode')
    assert h.tasks.enqueue(refresh,now=h.now)=='QUEUED'


def test_technical_result_does_not_renew_quotes_or_survive_revisions(tmp_path,monkeypatch):
    h=Harness(tmp_path,monkeypatch)
    e=worker.captured_event(h.events[0],{},automatic=True)
    current={**deepcopy(e),'reference_contract':{'contract_id':'TEST_ONLY_NEW'}}
    result=worker.deliver_review(h.outcome,e,current,now=h.now)
    assert result['delivery_state']=='CURRENT_TECHNICAL_REVIEW'
    assert not result['current_opportunity'] and not result['bbo_freshness_extended']
    current['runtime_inputs']['input_generation']=2
    assert worker.deliver_review(h.outcome,e,current,now=h.now)['delivery_state']=='INPUT_REVISED'
    assert worker.deliver_review(h.outcome,e,e,now=h.now+timedelta(seconds=300))['delivery_state']=='EXPIRED'
    assert worker.deliver_review(h.outcome,e,{**e,'withdrawn':True},now=h.now)['delivery_state']=='WITHDRAWN'
