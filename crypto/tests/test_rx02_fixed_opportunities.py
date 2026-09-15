from scripts.replay_rx02_fixed_opportunities_dev import resolve
from kquant_crypto.strategy_dual_mode_v1 import Bar


def opportunity():
    return dict(economic_signal_id='s',symbol='ETH',mode='UP_TREND',signal_time=300,
        plan=dict(stop=90,target=120,unit_net_risk=10))


def test_no_previous_bar_fill_and_no_zero_imputation():
    r=resolve(opportunity(),'ORIGINAL',[Bar(0,100,110,95,101,1)],{},600)
    assert r['status']=='UNAVAILABLE' and r['net_r'] is None


def test_stop_first_on_entry_bar_and_base_denominator():
    r=resolve(opportunity(),'ORIGINAL',[Bar(300,100,130,80,101,1)],{},600)
    assert r['reason']=='stop'
    assert r['exit_reference']==90 and r['base_unit_risk']==10
    assert r['counterfactual'] and not r['training_enabled']


def test_gap_entry_stop_is_immediate_not_retroactively_rejected():
    r=resolve(opportunity(),'ORIGINAL',[Bar(300,80,100,70,90,1)],{},600)
    assert r['reason']=='entry_gap_stop'
    assert r['exit_time']==300 and r['entry_time']==300


def test_missing_future_path_censored_not_terminal_profit():
    bars=[Bar(300,100,105,95,101,1),Bar(900,101,110,95,105,1)]
    context={600:dict(mode_invalidated=False,hours=None,atr=1)}
    r=resolve(opportunity(),'ORIGINAL',bars,context,1200)
    assert r['status']=='CENSORED' and r['net_r'] is None
