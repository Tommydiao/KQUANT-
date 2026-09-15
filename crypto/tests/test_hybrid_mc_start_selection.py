import pytest
from kquant_crypto.hybrid_mc_start_selection import select_starts


def row(t=1788220800, **kwargs):
    return dict(as_of=t, regime='RANGE', nav=9900, historical_peak=10000,
                history_end=t, history_bars=2017, history_contiguous=True,
                original_positions=1, original_pending=0, **kwargs)


def test_first_month_regime_only_and_no_future_outcome_selection():
    a, b = row(), row(1788224400)
    a['future_return'] = -100
    b['future_return'] = 100
    assert select_starts([a, b])['selected'][0]['as_of'] == a['as_of']
    assert len(select_starts([a, b])['selected']) == 1


def test_pending_is_existing_exposure_and_history_must_be_past():
    a = row()
    a.update(original_positions=0, original_pending=1)
    assert len(select_starts([a])['selected']) == 1
    a['history_end'] += 300
    with pytest.raises(ValueError, match='Future'):
        select_starts([a])


def test_missing_history_not_eligible_and_peak_not_reset():
    a = row()
    a['history_contiguous'] = False
    assert select_starts([a])['rejected'][0]['reason'] == 'INCOMPLETE_PAST_HISTORY'
    a = row()
    a['historical_peak'] = 9800
    with pytest.raises(ValueError, match='peak'):
        select_starts([a])


def test_reordering_and_duplicates_rejected():
    with pytest.raises(ValueError, match='chronological'):
        select_starts([row(), row()])
