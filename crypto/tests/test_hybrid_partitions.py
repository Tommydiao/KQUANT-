import pytest

from kquant_crypto.hybrid_partitions import assign_partitions, partition_policy


def label(identity,start,end,**changes):
    return {'economic_signal_id':identity,'information_start':start,'information_end':end,
            'status':'mature','source':'executed_virtual','dependence_group':'utc_day:'+str(start//86400),**changes}


def test_calendar_grouping_does_not_depend_on_asset_order():
    policy=partition_policy(0,10*86400)
    rows=[label(s,7*86400,7*86400+3600) for s in ('BTC','ETH','SOL')]
    a=assign_partitions(rows,policy)
    assert a==assign_partitions(list(reversed(rows)),policy)
    assert {r['partition'] for r in a}=={'validation'}
    assert all(r['population_eligible'] and not r['independent_oos'] for r in a)


def test_information_purge_and_post_boundary_embargo():
    policy=partition_policy(0,10*86400); cut=6*86400
    rows=[label('cross',cut-300,cut),label('embargo',cut+3600,cut+7200),
          label('allowed',cut+21600,cut+21900)]
    values={r['economic_signal_id']:r for r in assign_partitions(rows,policy)}
    assert values['cross']['exclusion_reason']=='purged_information_overlap'
    assert values['embargo']['exclusion_reason']=='embargo_after_boundary'
    assert values['allowed']['population_eligible']


def test_censored_and_counterfactual_cannot_enter_executed_training_population():
    policy=partition_policy(0,10*86400)
    rows=[label('censored',86400,90000,status='censored'),label('cf',86400,90000,source='counterfactual')]
    assert all(not r['population_eligible'] for r in assign_partitions(rows,policy))


def test_partition_mutation_fails_closed():
    policy=partition_policy(0,10*86400)
    duplicate=label('same',86400,90000)
    with pytest.raises(ValueError,match='Duplicate'):
        assign_partitions([duplicate,duplicate],policy)
    policy['embargo_seconds']=0
    with pytest.raises(ValueError,match='hash'):
        assign_partitions([],policy)
    with pytest.raises(ValueError,match='calendar'):
        partition_policy(1,10*86400)
