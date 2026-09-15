import json
import pytest
from kquant_crypto.hybrid_mc_recovery import read_prefix


def valid():
    return dict(path_id=0, sampling_hash='a'*64, results={'ORIGINAL': dict(net_change=-1,
        max_incremental_nav_drawdown=.01, max_historical_nav_drawdown=.02,
        terminal_mark_only=True, budget_exceeded=False)})


def test_prefix_bytes_preserved_and_missing_is_empty(tmp_path):
    path = tmp_path/'rows'
    assert read_prefix(path, ['ORIGINAL'], 5000) == ([], b'')
    payload = (json.dumps(valid())+'\n').encode()
    path.write_bytes(payload)
    rows, raw = read_prefix(path, ['ORIGINAL'], 5000)
    assert raw == payload and rows == [valid()]


@pytest.mark.parametrize('problem', ['partial', 'duplicate', 'nonfinite', 'drawdown'])
def test_invalid_prefix_is_never_silently_repaired(tmp_path, problem):
    row = valid()
    if problem == 'nonfinite': row['results']['ORIGINAL']['net_change'] = float('nan')
    if problem == 'drawdown': row['results']['ORIGINAL']['max_incremental_nav_drawdown'] = .05
    payload = json.dumps(row)+'\n'
    if problem == 'partial': payload = payload[:-1]
    if problem == 'duplicate': payload *= 2
    path = tmp_path/'rows'
    path.write_text(payload)
    with pytest.raises(ValueError): read_prefix(path, ['ORIGINAL'], 5000)
