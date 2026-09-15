"""Original protection parity with a stalled owned worker; synthetic bars only."""
from copy import deepcopy
import time

from kquant_crypto.hybrid_math_process import DevelopmentMathProcess
from test_candidate_portfolio import warm_states, warmed, enter_normal, batch, bar


def stalled_math():
    time.sleep(30)


def test_original_stop_is_processed_while_math_pending(warm_states):
    reference = warmed(warm_states)
    concurrent = warmed(warm_states)
    t = enter_normal(reference, symbols=('BTCUSDT',))
    assert enter_normal(concurrent, symbols=('BTCUSDT',)) == t
    position = deepcopy(reference.positions['BTCUSDT'])
    stop = position['stop']
    current = bar(t, stop-1, open=365, high=366, low=stop-2)
    batch(reference, current, symbols=('BTCUSDT',), allow=False)
    assert reference.trades and not reference.positions
    worker = DevelopmentMathProcess(stalled_math, timeout_seconds=10)
    try:
        assert worker.poll()['status'] == 'PENDING'
        batch(concurrent, current, symbols=('BTCUSDT',), allow=False)
        assert worker.poll()['status'] == 'PENDING'
        assert concurrent.trades == reference.trades
        assert concurrent.cash == reference.cash
        assert concurrent.positions == reference.positions
    finally:
        worker.close()
    assert not worker.process.is_alive()
