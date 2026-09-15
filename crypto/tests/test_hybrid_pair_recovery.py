import json
import pytest
from kquant_crypto.hybrid_mc_recovery import read_pair_prefix


def row():
    def outcome(net,filled):
        return dict(net_change=net,max_incremental_nav_drawdown=.01,
            booked_risk_ratio_exceeded=False,open_at_horizon=0,pending_at_horizon=0,
            exit_reasons={'stop':filled},target_plan_fills=filled,terminal_mark_only=True)
    return dict(path_id=0,sampling_hash='a'*64,results={'WITH_PLAN':outcome(-1,1),
        'WITHOUT_PLAN':outcome(0,0)},paired_net_change=-1,runtime_enabled=False,calibrated_risk=False)


def test_prefix_preserves_bytes_and_missing_is_empty(tmp_path):
    path=tmp_path/'paths.jsonl';assert read_pair_prefix(path,2)==([],b'')
    original=(json.dumps(row(),indent=None)+'\r\n').encode();path.write_bytes(original)
    rows,raw=read_pair_prefix(path,2)
    assert raw==original and rows==[row()]
    assert path.read_bytes()==original


@pytest.mark.parametrize('mutation',[
    lambda r:r.update(path_id=1),
    lambda r:r.update(runtime_enabled=True),
    lambda r:r.update(sampling_hash='z'*64),
    lambda r:r.update(paired_net_change=4),
    lambda r:r['results']['WITHOUT_PLAN'].update(target_plan_fills=1),
    lambda r:r['results']['WITH_PLAN'].update(net_change=float('nan')),
    lambda r:r['results']['WITH_PLAN'].update(open_at_horizon=-1),
])
def test_bad_prefix_rejected_without_rewrite(tmp_path,mutation):
    r=row();mutation(r);path=tmp_path/'paths.jsonl'
    raw=(json.dumps(r)+'\n').encode();path.write_bytes(raw)
    with pytest.raises(ValueError):read_pair_prefix(path,2)
    assert path.read_bytes()==raw


def test_truncated_duplicate_and_overfull_prefix_rejected(tmp_path):
    path=tmp_path/'paths.jsonl';line=json.dumps(row()).encode()
    for raw,maximum in ((line,2),(line+b'\n'+line+b'\n',2),(line+b'\n',0)):
        path.write_bytes(raw)
        with pytest.raises(ValueError):read_pair_prefix(path,maximum)
        assert path.read_bytes()==raw
