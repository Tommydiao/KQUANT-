from kquant_crypto.hybrid_factor_contract import factor_records


def test_missing_value_and_provenance_are_explicit():
    row = dict(symbol='BTCUSDT',dataset_hash='abc',source='bars',as_of=100,
               available_at=100,availability_basis='assumed_close_historical_replay',
               status='AVAILABLE',values={'relative_volume24':None},
               cross_section={'status':'UNAVAILABLE_PEER_CONTRACT','values':{}})
    result = factor_records(row)
    assert len(result['factors']) == 10
    assert all(r['value'] is None and r['status']=='MISSING' for r in result['factors'])
    assert all(r['as_of']==100 and r['source']=='bars' for r in result['factors'])
    assert factor_records(row)['factor_snapshot_hash']==result['factor_snapshot_hash']
    row['as_of']=101
    assert factor_records(row)['factor_snapshot_hash']!=result['factor_snapshot_hash']
