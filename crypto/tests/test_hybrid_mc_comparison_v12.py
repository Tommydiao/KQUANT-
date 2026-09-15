import pytest
from kquant_crypto.hybrid_mc_comparison_v12 import summarize_common_paths


def rows():
    return [{'path_id': p, 'alternative': a, 'events': {'daily_loss': a == 0}}
            for p in ('p1', 'p2') for a in (0, .25, .5, 1)]


def run(records, **kwargs):
    options = dict(path_ids=['p1', 'p2'], alternatives=(0, .25, .5, 1),
                   event_names=['daily_loss'], family_alpha=.05, comparison_budget=4)
    options.update(kwargs)
    return summarize_common_paths(records, **options)


def test_zero_quantity_does_not_hide_existing_risk():
    result = run(rows())
    assert result['comparisons'][0]['count'] == 2
    assert result['comparisons'][0]['upper'] == 1
    assert result['selected_alternative'] is None
    assert result['admission'] == 'ABSTAIN'


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'unknown', 'different_path'])
def test_failed_paths_never_discarded(change):
    records = rows()
    if change == 'missing':
        records.pop()
    elif change == 'duplicate':
        records.append(records[0])
    elif change == 'unknown':
        records[0]['events']['daily_loss'] = None
    else:
        records[0]['path_id'] = 'replacement'
    with pytest.raises(ValueError):
        run(records)


def test_budget_and_candidate_contract():
    with pytest.raises(ValueError):
        run(rows(), comparison_budget=3)
    with pytest.raises(ValueError):
        run(rows(), alternatives=(0, .5, 1))
    assert run(rows()) == run(list(reversed(rows())))


@pytest.mark.parametrize('bad', [True,False,1.0,None,''])
def test_invalid_path_identity_does_not_alias_integer(bad):
    with pytest.raises(ValueError,match='identity'):
        run([],path_ids=[bad])


def test_boolean_multiplier_does_not_alias_full_size():
    with pytest.raises(ValueError):
        run(rows(),alternatives=(0,.25,.5,True))
    records=rows()
    records[3]['alternative']=True
    with pytest.raises(ValueError,match='identity'):
        run(records)
