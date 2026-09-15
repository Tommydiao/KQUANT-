import pytest
from kquant_crypto.hybrid_entry_attribution import cost_bridge, compare_opportunities
from kquant_crypto.hybrid_entry_attribution import classify_opportunity
from kquant_crypto.hybrid_entry_attribution import rejection_occupancy


def trade():
    return dict(symbol='ETHUSDT',mode='UP_TREND',signal_time=1,quantity=2,
        entry_market_reference=100,exit_market_reference=110,entry_price=101,
        exit_price=109,fees=1,net_pnl=15,base_unit_net_risk=10)


def test_cost_bridge_counts_slippage_and_fee_once():
    result=cost_bridge(trade())
    assert result['gross_reference_pnl']==20
    assert result['net_pnl']==15
    assert result['net_base_r']==.75


def test_bad_bridge_fails():
    with pytest.raises(ValueError):cost_bridge(dict(trade(),net_pnl=14))


def test_composition_uses_signal_not_policy_trade_id():
    a=trade();b=dict(a,net_pnl=7);c=dict(a,signal_time=2,net_pnl=-2)
    result=compare_opportunities([a],[b,c])
    assert len(result['common'])==1
    assert result['common_cash_delta']==-8
    assert result['challenger_only_cash']==-2


def test_duplicate_opportunity_rejected():
    with pytest.raises(ValueError):compare_opportunities([trade(),trade()],[])


def test_unfilled_is_not_immature_or_zero_return():
    event=dict(symbol='ETHUSDT',time=1,kind='ENTRY_REJECTED',reason='already_exposed',event_id='1')
    result=classify_opportunity(trade(),{'net_r':None},[event],[])
    assert result['fill_status']=='NOT_FILLED'
    assert result['label_status']=='NOT_APPLICABLE_NO_TRADE'
    assert result['net_r'] is None


def test_reserved_without_trade_is_unresolved_not_mature():
    event=dict(symbol='ETHUSDT',time=1,kind='SIGNAL_RESERVED',event_id='1')
    result=classify_opportunity(trade(),None,[event],[])
    assert result['label_status']=='PENDING_AUDIT'


def test_unfilled_numeric_label_fails():
    event=dict(symbol='ETHUSDT',time=1,kind='ENTRY_REJECTED',event_id='1')
    with pytest.raises(ValueError):classify_opportunity(trade(),{'net_r':0},[event],[])


def test_missing_decision_fails():
    with pytest.raises(ValueError):classify_opportunity(trade(),None,[],[])


def test_rejection_links_prior_reservation_and_position():
    events=[dict(event_id='1',kind='SIGNAL_RESERVED',symbol='ETH',time=1,plan={'trade_id':'t'}),
            dict(event_id='2',kind='ENTRY_REJECTED',symbol='ETH',time=1,reason='already_exposed'),
            dict(event_id='3',kind='VIRTUAL_ENTRY',symbol='ETH',time=1,trade_id='t'),
            dict(event_id='4',kind='ENTRY_REJECTED',symbol='ETH',time=2,reason='already_exposed'),
            dict(event_id='5',kind='VIRTUAL_EXIT',symbol='ETH',time=3,trade_id='t')]
    result=rejection_occupancy(events)
    assert result['rejections'][0]['pending']['ETH']['trade_id']=='t'
    assert result['rejections'][1]['positions']['ETH']['trade_id']=='t'
    assert result['remaining_positions']=={}


def test_pause_must_precede_rejection_and_not_expire():
    events=[dict(event_id='1',kind='LOSS_STREAK_PAUSE',symbol='',time=1,until=3),
            dict(event_id='2',kind='ENTRY_REJECTED',symbol='ETH',time=2,reason='risk_pause')]
    assert rejection_occupancy(events)['rejections'][0]['prior_event_support']
    events[1]['time']=3
    with pytest.raises(ValueError):rejection_occupancy(events)


def test_rejection_without_occupancy_fails():
    with pytest.raises(ValueError):rejection_occupancy([dict(event_id='1',kind='ENTRY_REJECTED',symbol='ETH',time=1,reason='already_exposed')])


def test_replayed_event_id_fails():
    event=dict(event_id='1',kind='LOSS_STREAK_PAUSE',symbol='',time=1,until=3)
    with pytest.raises(ValueError):rejection_occupancy([event,event])
