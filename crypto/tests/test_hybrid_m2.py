from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from kquant_crypto.candidate_policy import digest
from kquant_crypto.hybrid_dataset import clean_rows, proven_hours, load_development, file_hash, SYMBOLS
from kquant_crypto.hybrid_features import snapshot, FEATURE_SCHEMA
from kquant_crypto.hybrid_labels import from_opportunity, delayed_open_assessment
from kquant_crypto.strategy_dual_mode_v1 import Bar
from test_candidate_portfolio import warm_states, warmed, trigger


def row(stamp=0,duration=300,**changes):
    return {'start':stamp,'open':100.,'high':101.,'low':99.,'close':100.,'volume':1.,
            'available_at':stamp+duration,'availability_basis':'assumed_close_historical_replay',
            'received_at':'2026-09-05T00:00:00Z','provider_status':'historical',**changes}


@pytest.mark.parametrize('change',[{'close':float('nan')},{'start':1},{'available_at':200},
                                  {'provider_status':'stale'},{'low':-1}])
def test_invalid_rows_do_not_enter_features(change):
    bars,_,errors=clean_rows([row(**change)],300,3600)
    assert not bars and errors


def test_duplicates_are_collapsed_or_entire_timestamp_quarantined():
    bars,source,errors=clean_rows([row(),row()],300,3600)
    assert len(bars)==1 and errors[0]['reason']=='exact_duplicate_collapsed'
    bars,_,errors=clean_rows([row(),row(close=100.5)],300,3600)
    assert not bars and errors[0]['reason']=='invalid_or_conflicting_duplicate'
    assert source[0]['received_at']=='2026-09-05T00:00:00Z'


def test_hour_requires_all_children_and_volume_match():
    fives=[Bar(i*300,100,101,99,100,1) for i in range(12)]
    hour=Bar(0,100,101,99,100,12)
    assert proven_hours(fives,[hour])==([hour],[])
    assert proven_hours(fives[:-1],[hour])[1][0]['reason']=='missing_5m_child'
    assert proven_hours(fives,[Bar(0,100,101,99,100,13)])[1][0]['reason']=='hour_ohlcv_mismatch'


def fixture_manifest(tmp_path):
    files={}
    for symbol in SYMBOLS:
        files[symbol]={}
        for tf,duration in [('5m',300),('1h',3600)]:
            rows=[row(i,duration,volume=duration/300) for i in range(0,3*86400,duration)]
            path=tmp_path/(symbol+'_'+tf+'.parquet')
            pq.write_table(pa.Table.from_pylist(rows),path)
            files[symbol][tf]={'path':path.name,'sha256':file_hash(path),'rows':len(rows)}
    value={'schema_version':1,'symbols':list(SYMBOLS),'source':'binance:spot:market_specific_compacted_closed_klines',
           'window':{'start':3600,'warmup_start':0,'days':3,'end':3*86400+3600},'files':files}
    value['manifest_hash']=digest(value)
    path=tmp_path/'manifest.json'
    path.write_text(json.dumps(value),encoding='utf-8')
    return path


def test_future_rows_not_materialized_and_past_content_unchanged(tmp_path):
    path=fixture_manifest(tmp_path)
    first=load_development(path,cutoff=7200)
    assert len(first.bars['BTCUSDT']['5m'])==24
    manifest=json.loads(path.read_text())
    data_path=tmp_path/manifest['files']['BTCUSDT']['5m']['path']
    rows=pq.read_table(data_path).to_pylist()
    for r in rows:
        if r['start']>=7200:
            r['close']=float('nan')
    pq.write_table(pa.Table.from_pylist(rows),data_path)
    manifest['files']['BTCUSDT']['5m']['sha256']=file_hash(data_path)
    manifest.pop('manifest_hash')
    manifest['manifest_hash']=digest(manifest)
    path.write_text(json.dumps(manifest))
    second=load_development(path,cutoff=7200)
    assert first.content_hash==second.content_hash
    assert second.quarantine==[]
    assert first.provenance==second.provenance


def test_sealed_date_and_file_corruption_refused(tmp_path):
    path=fixture_manifest(tmp_path)
    with pytest.raises(ValueError,match='cutoff'):
        load_development(path,cutoff=3*86400)
    p=tmp_path/'BTCUSDT_5m.parquet'
    with p.open('ab') as stream:
        stream.write(b'corrupted')
    with pytest.raises(ValueError,match='hash'):
        load_development(path,cutoff=7200)


def test_observer_does_not_mutate_kernel_and_feature_times_are_independent(warm_states):
    p=warmed(warm_states)
    at=trigger(p)
    before=deepcopy(p.snapshot())
    result=snapshot(p,'ETHUSDT',available_at=at)
    assert before==p.snapshot()
    assert len(FEATURE_SCHEMA['order'])==8
    assert result['values']['box_position'] is None
    assert result['missing']['box_position']=='mode_not_applicable'
    assert result['factor_as_of']['er24_1h']<result['signal_time']
    assert result['factor_as_of']['atr14_5m_fraction']==result['signal_time']
    assert all(t<=result['available_at'] for t in result['factor_as_of'].values())
    with pytest.raises(ValueError,match='availability'):
        snapshot(p,'ETHUSDT',available_at=at-1)


def test_benchmark_stale_is_missing_not_zero(warm_states):
    p=warmed(warm_states)
    at=trigger(p,symbols=('ETHUSDT',))
    result=snapshot(p,'ETHUSDT',available_at=at)
    assert result['values']['relative_btc_1h'] is None
    assert result['missing']['relative_btc_1h']=='benchmark_not_aligned'


def opportunity():
    return {'economic_signal_id':'s','signal_time':300,'symbol':'BTCUSDT','mode':'UP_TREND','snapshot_hash':'f'}


def test_censored_unexecuted_and_terminal_outcomes_are_not_mature():
    missing=from_opportunity(opportunity(),None,cutoff=1200)
    assert missing['net_r'] is None and missing['status']=='unavailable'
    future={'exit_time':1500,'exit_reason':'stop'}
    censored=from_opportunity(opportunity(),future,cutoff=1200)
    assert censored['net_r'] is None and 'executed_trade' not in censored
    trade={k:1 for k in ('trade_id','entry_time','quantity','entry_price','exit_price','fees','net_pnl','risk_amount','unit_net_risk')}
    trade.update(exit_time=900,exit_reason='terminal_liquidation',net_r=.1)
    terminal=from_opportunity(opportunity(),trade,cutoff=1200)
    assert terminal['status']=='terminated' and terminal['source']=='termination_liquidation'
    trade.update(exit_reason='data_gap',path_unverifiable=True)
    assert from_opportunity(opportunity(),trade,cutoff=1200)['net_r'] is None


def test_delayed_open_never_uses_past_open_or_extends_expiry():
    assert delayed_open_assessment(300,completed_at=304,expires_at=330,next_open=300)['status']=='unavailable'
    assert delayed_open_assessment(300,completed_at=304,expires_at=330,next_open=600)['reason']=='no_post_commit_open_before_expiry'
    assert delayed_open_assessment(300,completed_at=304,expires_at=630,next_open=600)['status']=='timing_only'
    assert delayed_open_assessment(300,completed_at=331,expires_at=330,next_open=600)['reason']=='decision_expired'
    with pytest.raises(ValueError,match='Finite'):
        delayed_open_assessment(300,completed_at=float('nan'),expires_at=330,next_open=600)
