"""Synthetic engineering fixtures, never historical performance evidence."""
from copy import deepcopy
from dataclasses import asdict
import json
import sqlite3

import pytest

from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.hybrid_observation import Observer, ObservationStore, legacy_state
from test_candidate_portfolio import warm_states, warmed, bar, SIGNAL_START, RULES, SYMBOLS


def seeded(warm_states):
    p = warmed(warm_states, execution='quotes')
    o = Observer(p.policy, RULES, {'portfolio':p.snapshot(),'opportunities':{},'watermarks':{}})
    current = bar(SIGNAL_START,365,open=350,high=380,low=340)
    event={'type':'closed_batch','received_at':SIGNAL_START+300.1,
           'five':{s:asdict(current) for s in SYMBOLS},'hourly':{}}
    o.apply(event)
    return o


def quote(o, delta=5, **changes):
    t=SIGNAL_START+300+delta
    event={'type':'quote','symbol':'BTCUSDT','source_time':t,'received_at':t+.01,
           'source_time_basis':'exchange_event_time','bid':364.9,'ask':365.1,
           'bid_size':10000.,'ask_size':10000.,'sequence':int(delta*100),
           'source':'synthetic_fixture','venue':'binance','market_type':'spot','provider_status':'live'}
    return event|changes


def btc(o):
    return next(r for r in o.opportunities.values() if r['symbol']=='BTCUSDT')


def test_unfilled_is_not_immature_or_zero_r():
    op={'economic_signal_id':'x','symbol':'BTCUSDT','mode':'UP_TREND','signal_time':100,
        'original_reasons':['already_exposed']}
    label={'status':'unavailable','reason':'not_executed_in_baseline','source':'executed_virtual',
           'label_hash':'old','net_r':None}
    projected=legacy_state(op,label)
    assert projected['fill_status']=='UNFILLED'
    assert projected['label_status']=='NOT_APPLICABLE_UNFILLED'
    assert projected['net_r'] is None and not projected['entry_attempted']
    assert label['status']=='unavailable'


def test_precommit_quote_cannot_fill(warm_states):
    o=seeded(warm_states)
    o.apply(quote(o,delta=2))
    assert not o.portfolio.positions
    assert o.audit[-1]['reason']=='quote_before_decision_commit'
    o.apply(quote(o))
    assert btc(o)['fill_status']=='FILLED' and btc(o)['label_status']=='PENDING'
    assert btc(o)['timeline']['evaluation_finished_at']==SIGNAL_START+304.1


@pytest.mark.parametrize('change,reason',[
    ({'source_time':None},'missing_proven_quote_fields'),
    ({'ask_size':None},'missing_proven_quote_fields'),
    ({'source_time_basis':'receipt_fallback'},'missing_proven_quote_fields'),
    ({'bid_size':.000001},'insufficient_quote_quantity'),
    ({'provider_status':'stale'},'invalid_or_stale_quote'),
    ({'market_type':'perpetual'},'invalid_or_stale_quote'),
])
def test_ineligible_quotes_retained_not_filled(warm_states,change,reason):
    o=seeded(warm_states);o.apply(quote(o,**change))
    assert not o.portfolio.positions
    assert o.audit[-1]['reason']==reason


def test_expiry_unfilled_not_zero_return(warm_states):
    o=seeded(warm_states)
    o.apply({'type':'clock','received_at':SIGNAL_START+331})
    assert btc(o)['fill_status']=='UNFILLED'
    assert btc(o)['net_r'] is None


def test_protection_matures_only_post_entry_quote_and_base_costs(warm_states):
    o=seeded(warm_states);o.apply(quote(o))
    position=deepcopy(o.portfolio.positions['BTCUSDT'])
    low=position['stop']-1
    o.apply(quote(o,delta=6,source_time=SIGNAL_START+304,bid=low,ask=low+.1))
    assert btc(o)['label_status']=='PENDING'
    o.apply(quote(o,delta=7,bid=low,ask=low+.1))
    row=btc(o); t=row['trade']
    assert row['label_status']=='MATURE' and row['outcome_reason']=='stop'
    assert row['label_available_at']==t['exit_time']
    assert t['entry_price']==pytest.approx(365.1*1.0002)
    assert t['exit_price']==pytest.approx(low*.9998)
    assert t['net_r']==pytest.approx(t['net_pnl']/(t['quantity']*t['unit_net_risk']))


@pytest.mark.parametrize('kind',['disconnect','observation_end'])
def test_missing_path_not_normal_exit(warm_states,kind):
    o=seeded(warm_states);o.apply(quote(o))
    o.apply({'type':kind,'received_at':SIGNAL_START+306})
    assert btc(o)['label_status']=='CENSORED' and btc(o)['net_r'] is None
    assert o.portfolio.positions
    stop=o.portfolio.positions['BTCUSDT']['stop']-1
    o.apply(quote(o,delta=7,bid=stop,ask=stop+.1))
    assert btc(o)['label_status']=='CENSORED' and btc(o)['net_r'] is None


def test_restart_dedup_transaction_failure_and_immutable_labels(tmp_path,warm_states):
    path=tmp_path/'hybrid_test.sqlite3'
    o=seeded(warm_states)
    store=ObservationStore(path,o.portfolio.policy,RULES)
    store.db.execute('INSERT INTO observer_checkpoint VALUES(1,?)',(json.dumps(o.state()),));store.db.commit()
    event=quote(o)
    with pytest.raises(sqlite3.OperationalError):store.process('quote1',event,fail_before_commit=True)
    assert store.db.execute('SELECT count(*) FROM observer_events').fetchone()[0]==0
    assert store.db.execute('SELECT count(*) FROM observer_labels').fetchone()[0]==0
    assert not store.process('quote1',event)['duplicate']
    first=store.db.execute('SELECT * FROM observer_labels').fetchall()
    store.close()
    store=ObservationStore(path,o.portfolio.policy,RULES)
    assert store.process('quote1',event)['duplicate']
    with pytest.raises(ValueError):store.process('quote1',event|{'bid':300})
    assert store.db.execute('SELECT * FROM observer_labels').fetchall()==first
    result=store.process('out_of_order',event|{'sequence':1})
    assert result['audit'][-1]['reason']=='out_of_order_quote'
    store.close()


def test_model_worker_failure_does_not_touch_quote_protection(tmp_path,warm_states):
    o=seeded(warm_states);o.apply(quote(o))
    with pytest.raises(RuntimeError):
        raise RuntimeError('synthetic math worker failed outside observer')
    stop=o.portfolio.positions['BTCUSDT']['stop']-1
    o.apply(quote(o,delta=7,bid=stop,ask=stop+.1))
    assert btc(o)['label_status']=='MATURE'


def test_never_open_original_database(tmp_path):
    with pytest.raises(ValueError):ObservationStore(tmp_path/'candidate_simulation.sqlite3',load_policy(),RULES)


def test_forming_batch_rejected(warm_states):
    o=seeded(warm_states)
    with pytest.raises(ValueError):o.apply({'type':'closed_batch','received_at':SIGNAL_START,
        'five':{'BTCUSDT':asdict(bar(SIGNAL_START+300,365))}})


def test_historical_correction_appends_not_overwrites(tmp_path):
    store=ObservationStore(tmp_path/'hybrid_legacy.sqlite3',load_policy(),RULES)
    op={'economic_signal_id':'x','symbol':'BTCUSDT','mode':'UP_TREND','signal_time':100,'original_reasons':['already_exposed']}
    label={'status':'unavailable','reason':'not_executed','source':'executed_virtual','label_hash':'old','net_r':None}
    row=legacy_state(op,label)
    assert store.import_legacy(row,'manifest1')
    assert not store.import_legacy(row,'manifest1')
    original=store.db.execute('SELECT * FROM legacy_label_revisions').fetchone()
    revised=row|{'outcome_reason':'audited_reason','legacy_label_hash':'new'}
    with pytest.raises(ValueError):store.import_legacy(revised,'manifest2')
    assert store.import_legacy(revised,'manifest2',parent_hash=original[2],correction_reason='source correction')
    assert store.db.execute('SELECT * FROM legacy_label_revisions ORDER BY version').fetchall()[0]==original
    with pytest.raises(ValueError):store.import_legacy(row|{'label_execution_policy_id':'QUOTE_AWARE'},'manifest1')
    assert store.db.execute('SELECT count(*) FROM observer_labels').fetchone()[0]==0
    store.close()


def test_slow_actual_commit_never_admits_earlier_quote(warm_states):
    o=seeded(warm_states)
    for item in o.opportunities.values():item['requires_commit_observation']=True
    o.apply(quote(o,delta=5))
    assert o.audit[-1]['reason']=='decision_commit_not_observed'
    o.apply({'type':'commit_observed','signal_time':SIGNAL_START+300,'received_at':SIGNAL_START+309})
    o.apply(quote(o,delta=10,source_time=SIGNAL_START+308))
    assert not o.portfolio.positions
    o.apply(quote(o,delta=11))
    assert btc(o)['fill_status']=='FILLED'


def test_clock_conflict_not_normal_network_latency(warm_states):
    o=seeded(warm_states)
    o.apply(quote(o,source_time=SIGNAL_START+625))
    assert o.audit[-1]['reason']=='source_time_after_receipt_clock_conflict'
    assert not o.portfolio.positions


def test_ticker_preserves_source_time_sizes_and_sampling():
    from kquant_crypto.hybrid_public_observer import normalize_ticker
    raw={'stream':'btcusdt@ticker','data':{'e':'24hrTicker','E':100000,'s':'BTCUSDT','b':'10','a':'11','B':'3','A':'4'}}
    row=normalize_ticker(raw,100.1)
    assert row['source_time']==100 and row['received_at']==100.1 and row['ask_size']==4
    assert row['sequence_basis']=='exchange_event_time_not_book_update_sequence'
    with pytest.raises(ValueError):normalize_ticker(raw|{'stream':'btcusdt@bookTicker'},100.1)
