"""TEST_ONLY reviewed snapshot contracts. No production source or OWNER record."""
from copy import deepcopy
from datetime import UTC,date,datetime,timedelta
from hashlib import sha256
import json

import pytest

from kquant import options_one_minute as common
from kquant import options_price_action_source as actions
from test_r58_p10_safe_closeout import action_method

NOW=datetime(2026,10,2,13,35,tzinfo=UTC)


def fixture(tmp_path,items=None):
    proof=action_method(tmp_path,NOW)
    proof.update(source_kind='OFFICIAL_DOCUMENT',source_url='https://open.longbridge.com/docs/test-only-snapshot')
    claim=proof['claim']
    claim.update(assertion='COMPANY_ACTION_COMPLETE_SNAPSHOT_AND_PRICE_TYPES',
        interface='HttpClient:/v1/quote/company-act',range_semantics=actions.SNAPSHOT_METHOD['extent'],
        pagination_semantics='COMPLETE_SINGLE_RESPONSE')
    proof.update(interface=claim['interface'],claim_hash=common.digest(claim),test_only=True)
    receipt=dict(status='ACCEPTED',accepted_by='OWNER',method=actions.SNAPSHOT_METHOD,
        method_hash=common.digest(actions.SNAPSHOT_METHOD),accepted_at=NOW.isoformat(),
        valid_until=(NOW+timedelta(hours=1)).isoformat(),test_only=True)
    raw=json.dumps(receipt).encode()
    path=tmp_path/'TEST_ONLY-snapshot-method.json'
    path.write_bytes(raw)
    proof['snapshot_method_acceptance']={'path':path.name,'sha256':sha256(raw).hexdigest()}
    observation=actions.observe({'items':items or []},symbol='TEST',requested_at=NOW,
        received_at=NOW,target_session=date(2026,10,2),interface=claim['interface'],
        query={'symbol':'TEST.US','req_type':'1','version':'3'})
    return proof,observation


def row(day='20261002',kind='meeting',date_type='ex_date'):
    return dict(date=day,act_type=kind,date_type=date_type,date_zone='America/New_York',is_delay=False)


def test_complete_snapshot_filters_only_interpretable_economic_dates(tmp_path):
    proof,observation=fixture(tmp_path,[row('20260901','split'),row()])
    original=deepcopy(observation)
    fact=actions.coverage_fact(observation,method=proof,now=NOW,root=tmp_path)
    assert observation==original and 'start_date' not in observation['query']
    assert fact['complete'] and fact['price_scale_state']=='UNCHANGED'
    assert fact['range_evaluation']=='REVIEWED_COMPLETE_SNAPSHOT_LOCAL_FILTER'
    assert actions.valid_fact(fact,symbol='TEST',previous='2026-10-01',session='2026-10-02',now=NOW,root=tmp_path)


def test_price_changing_snapshot_is_never_comparable(tmp_path):
    proof,observation=fixture(tmp_path,[row(kind='split')])
    fact=actions.coverage_fact(observation,method=proof,now=NOW,root=tmp_path)
    assert fact['complete'] and fact['price_scale_state']=='CHANGED'
    assert not actions.valid_fact(fact,symbol='TEST',previous='2026-10-01',session='2026-10-02',now=NOW,root=tmp_path)


@pytest.mark.parametrize('defect',[
    'no_source','no_acceptance','bad_acceptance_hash','unknown_date_outside','unknown_type',
    'pagination','pagination_contract_missing','wrong_symbol','claimed_server_dates','future_session','mutated_raw'])
def test_snapshot_cannot_bypass_missing_proof_or_native_semantics(tmp_path,defect):
    proof,observation=fixture(tmp_path)
    if defect=='no_source':
        proof=None
    elif defect=='no_acceptance':
        proof.pop('snapshot_method_acceptance')
    elif defect=='bad_acceptance_hash':
        proof['snapshot_method_acceptance']['sha256']='bad'
    elif defect in {'unknown_date_outside','unknown_type'}:
        items=[row('20260901',date_type='payment_date')] if defect=='unknown_date_outside' else [row(kind='unknown')]
        proof,observation=fixture(tmp_path,items)
    elif defect=='pagination':
        observation['raw_response']['has_more']=True
        observation['raw_response_sha256']=common.digest(observation['raw_response'])
    elif defect=='pagination_contract_missing':
        proof['claim'].pop('pagination_semantics')
        proof['claim_hash']=common.digest(proof['claim'])
    elif defect=='wrong_symbol':
        observation['query']['symbol']='OTHER.US'
    elif defect=='claimed_server_dates':
        observation['query'].update(start_date='2026-10-01',end_date='2026-10-02')
    elif defect=='future_session':
        observation['requested_coverage_through']='2026-10-05'
    else:
        observation['raw_response']['items']=[row()]
    fact=actions.coverage_fact(observation,method=proof,now=NOW,root=tmp_path)
    assert not fact['complete'] and fact['price_scale_state']=='UNKNOWN'
    assert not fact['owner_approval']


@pytest.mark.parametrize('right,expected',[('CALL','NUMERIC_PASS'),('PUT','NO_TRIGGER')])
def test_snapshot_storage_binding_and_actual_s0_modules(tmp_path,monkeypatch,right,expected):
    from test_r58_p7_inputs import fact_inputs
    from kquant import options_price_facts as facts
    from kquant import options_price_reference as price_reference
    from kquant import options_opening_momentum as model
    from kquant import options_opening_momentum_journal as journal
    args,quote,reviews=fact_inputs(tmp_path,monkeypatch)
    proof,observation=fixture(tmp_path,[row('20260901','split'),row()])
    fact=actions.coverage_fact(observation,method=proof,now=args['now'],root=tmp_path)
    observation['coverage_fact']=fact
    observation['retry_after']=fact['valid_until']
    directory=tmp_path/'TEST_ONLY-action-producer'
    directory.mkdir()
    index=directory/'index.json'
    target=date(2026,10,2)
    item,claim=actions.claim_action(index,[{'symbol':'TEST','identity_status':'verified'}],
        target,common.digest(proof),NOW)
    assert actions.commit_action(index,'TEST',claim,observation,directory/'raw.json',tmp_path,
        target,1,args['now'])
    assert (tmp_path/'work/option_foundation/price-action-facts/TEST/2026-10-02.json').is_file()
    reviews.pop('instrument_price_actions')
    reviews['company_action_coverage_method']=proof
    db=tmp_path/'TEST_ONLY-binding.sqlite3'
    journal.initialize(db)
    quote['session_price_binding']=facts.persist_binding(db,facts.bind(quote,symbol='TEST',
        session=target.isoformat(),now=args['now'],reviews=reviews,root=tmp_path))
    assert quote['session_price_binding']['status']=='VERIFIED'
    monkeypatch.setattr(price_reference,'ROOT',tmp_path)
    args['reference']=price_reference.build(quote,symbol='TEST',session=target.isoformat(),
        now=args['now'],reviews=reviews,root=tmp_path)
    args['right']=right
    result=model.evaluate(**args)
    assert result['state']==expected and not result['qualified_signal']
