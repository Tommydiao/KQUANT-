from kquant_crypto.hybrid_conditioned_paths import conditioned_paths
from kquant_crypto.hybrid_mc_paths_v12 import DevPathSpec,SYMBOLS


def test_common_paths_reproduce_and_keep_cross_asset_ratios():
    history=[]
    for i in range(40):
        history.append({'start':i*300,'regime_before':'UP_TREND','bars':{
            s:dict(start=i*300,open=100+i,high=102+i,low=99+i,close=101+i,
                   available_at=(i+1)*300,source_bar_id=f'{s}:{i}') for s in SYMBOLS}})
    spec=DevPathSpec(0,12000,12000,3,6,2,42,40,36,'hash','SYNTHETIC_DEV')
    a=list(conditioned_paths(history,{s:200 for s in SYMBOLS},spec,'UP_TREND'))
    b=list(conditioned_paths(history,{s:200 for s in SYMBOLS},spec,'UP_TREND'))
    assert a==b
    assert len(a)==2
    for path in a:
        for batch in path['batches']:
            assert len({bar.close for bar in batch.values()})==1
            assert all(bar.start>=12000 for bar in batch.values())
