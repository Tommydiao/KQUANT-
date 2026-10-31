"""Isolated price fixtures, actual store -> projection -> compact; no publication."""
import pytest

from kquant import options_opening_momentum as model
from kquant import options_one_minute as common
from kquant import options_opening_trend_store as store
from kquant.options_opening_trend_projection import ProjectionCache,read_delta
from kquant.options_opening_trend_summary import compact_status
from test_options_opening_momentum import inputs


@pytest.mark.parametrize('kind,expected,numeric',[
    ('pass','FULL',1),('no_trigger','FULL',1),('partial','PARTIAL_PRICE_COMPONENTS',0)])
def test_factor_survives_actual_incremental_status_path(tmp_path,kind,expected,numeric):
    args=inputs()
    if kind=='no_trigger':
        args['reference']['previous_close']=110
    elif kind=='partial':
        args['reference']['price_comparable']=False
    result=model.evaluate(**args)
    path=tmp_path/'TEST_ONLY-research.sqlite3'
    store.initialize(path)
    store.persist([result],path)
    delta=read_delta(path,session=result['session'],policy_hash=result['policy_hash'])
    saved=delta['rows'][0][1]
    assert saved['factor_evidence_sha256']==common.digest(result['factor_evidence'])
    for name in ('price','previous_close','momentum','close_position','checks'):
        assert saved['factor_evidence'][name]==result['factor_evidence'][name]
    assert saved['factor_evidence']['reference']['evidence_deferred']
    assert 'factor_evidence_present' not in saved
    coverage=ProjectionCache().apply(delta,registered=[{'symbol':'TEST','identity_status':'verified'}],
        now=args['now'],policy=model.load_policy(),scope_hash='scope')
    summary=compact_status({'checkpoint_coverage':coverage})
    point=summary['checkpoint_coverage']['checkpoints'][0]
    assert point['numeric_directions']==numeric
    assert point['factor_grades'][expected]==1
    assert 'items' not in point and point['items_total']==2
