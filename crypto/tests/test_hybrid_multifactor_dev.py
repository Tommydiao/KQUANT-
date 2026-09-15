from kquant_crypto.hybrid_multifactor_dev import snapshot
from kquant_crypto.strategy_dual_mode_v1 import Bar


def test_future_and_gap():
    rows = [Bar(i*3600,100+i,102+i,99+i,101+i,10+i) for i in range(26)]
    assert snapshot(rows,25*3600) == snapshot(rows[:25],25*3600)
    assert snapshot(rows[:24],25*3600)['status'] == 'MISSING_CONTIGUOUS_HISTORY'
    assert snapshot(rows[:25],25*3600)['values']['er24'] == 1.0
