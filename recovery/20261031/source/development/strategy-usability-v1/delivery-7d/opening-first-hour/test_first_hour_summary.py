from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest
import first_hour_summary as candidate

PARENT = Path(__file__).resolve().parent.parent / 'monday-signal-llm/projection-followup/patches/kquant/options_opening_trend_summary.py'
spec = importlib.util.spec_from_file_location('summary_parent', PARENT)
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)


def payload(points=11):
    return dict(session='2026-10-22', unknown=None,
        registered_items=[{'symbol':f'TEST{i}', 'identity_status':'verified', 'hidden':{'source':'private fixture'}} for i in range(111)],
        checkpoint_coverage={'state':'PARTIAL_WINDOW','checkpoints':[
            {'bar_end':str(point), 'numeric_directions':190, 'items':[
                {'symbol':f'TEST{i}', 'state':'INCOMPLETE', 'reasons':['A','A','B'], 'nested':{'v':[1,2,3]}}
                for i in range(222)]} for point in range(points)]},
        evaluations=[{'evaluation_id':str(i), 'state':'NO_TRIGGER','deadline_at':'test-only',
                      'factor_evidence':{'not_copied':list(range(30))}} for i in range(10)],
        candidates=[],worker={'state':'NOT_RUN','nested':{'x':[1]}})


@pytest.mark.parametrize('points', [0,1,5,11])
@pytest.mark.parametrize('large', [False, True])
def test_exact_parent_output_and_no_shared_mutation(points, large):
    value = payload(points)
    if large:
        value['evaluations'][0]['large'] = 'X'*40000
        value['worker']['large'] = {'raw':'Y'*40000}
    before = deepcopy(value)
    actual = candidate.compact_status(value)
    assert actual == parent.compact_status(value)
    assert value == before
    actual['registered_items'][0]['symbol'] = 'CHANGED'
    actual['worker']['state'] = 'CHANGED'
    if actual['checkpoint_coverage']['checkpoints']:
        actual['checkpoint_coverage']['checkpoints'][0]['reason_counts']['A'] = 0
    assert value == before


@pytest.mark.parametrize('coverage', [None,{}, {'items':[]}, {'items':[{}], 'items_total':7},
    {'checkpoints':[{'bar_end':'x','reason_counts':{'old':2}}]}])
def test_legacy_coverage_shapes(coverage):
    value = {'checkpoint_coverage':coverage}
    assert candidate.compact_status(value) == parent.compact_status(value)


def test_discarded_detail_is_not_deepcopied():
    class MustNotCopy(dict):
        def __deepcopy__(self, memo):
            raise AssertionError('DISCARDED_DETAIL_WAS_COPIED')
    value = payload(1)
    value['checkpoint_coverage']['checkpoints'][0]['items'][0]['nested'] = MustNotCopy()
    assert candidate.compact_status(value)['checkpoint_coverage']['checkpoints'][0]['items_total'] == 222
