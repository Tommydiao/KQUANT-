import pytest
from kquant_crypto.hybrid_opportunity_folds import build_folds, DAY


def rows():
    return [{'symbol':symbol,'as_of':day*DAY,'available_at':day*DAY,
             'label_available_at':(day+1)*DAY,'label_status':'MATURE',
             'fill_status':'NOT_APPLICABLE','exposure':'EXPOSED_RESEARCH','exclusion_reason':None,'y_log_percent':0.1}
            for day in range(60) for symbol in ('BTCUSDT','ETHUSDT','SOLUSDT')]


def test_nested_date_membership_and_purge():
    result = build_folds(rows(), 0, 60*DAY)
    for fold in result['folds']:
        members = fold['membership']
        outer = {tuple(k) for k in members['outer_train']}
        assert {tuple(k) for k in members['inner_train']} <= outer
        assert {tuple(k) for k in members['inner_validation']} <= outer
        assert all(t+DAY < fold['outer_start']-DAY for _,t in members['outer_train'])
        assert all(t+DAY < fold['outer_end'] for _,t in members['outer_diagnostic'])
        for values in members.values():
            dates = {t for _,t in values}
            assert len(values) == 3*len(dates)
    assert result['independent_oos'] is False


def test_holding_label_and_duplicate_not_silently_split():
    bad = rows()
    bad[0]['label_available_at'] += 300
    with pytest.raises(ValueError, match='Variable holding'):
        build_folds(bad,0,60*DAY)
    with pytest.raises(ValueError, match='Duplicate'):
        build_folds(rows()+rows()[:1],0,60*DAY)


def test_calendar_eligible_does_not_imply_exported_target():
    data=rows()
    data[0].update(y_log_percent=None,exclusion_reason='PURGED_EMBARGO')
    result=build_folds(data,0,60*DAY)
    for fold in result['folds']:
        assert ['BTCUSDT',0] not in fold['membership']['outer_train']
        assert any(r['reason']=='LABEL_VALUE_NOT_EXPORTED' for r in fold['exclusions'])
