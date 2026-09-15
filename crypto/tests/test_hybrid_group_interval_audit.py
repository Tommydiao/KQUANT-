import pytest
from kquant_crypto.hybrid_group_interval_audit import audit_group_partitions


def group(key,start,end):
    return dict(economic_key=[key],information_start=start,information_end=end,rows=3)


def test_long_group_and_connected_next_group_are_purged():
    result=audit_group_partitions([group('a',70,115),group('b',110,130),group('c',150,160)],[0,100,200,300])
    assert [r['interval_exclusion'] for r in result['rows']]==[
        'GROUP_LABEL_CROSSES_BOUNDARY','DEPENDENCY_COMPONENT_CROSSES_BOUNDARY',None]
    assert all(not r['training_enabled'] for r in result['rows'])


def test_touching_label_boundary_is_not_safe():
    r=audit_group_partitions([group('a',70,100)],[0,100,200,300])['rows'][0]
    assert r['interval_exclusion']=='GROUP_LABEL_CROSSES_BOUNDARY'


def test_cross_policy_duplicates_not_independent_groups():
    with pytest.raises(ValueError,match='merged'):
        audit_group_partitions([group('a',1,2),group('a',1,3)],[0,100,200,300])
