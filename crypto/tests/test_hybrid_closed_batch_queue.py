import pytest
from kquant_crypto.hybrid_closed_batch_queue import ClosedBatchQueue


def test_closed_bar_waits_for_actual_receipt_bound_without_backdating():
    queue = ClosedBatchQueue(['BTC', 'ETH', 'SOL'], 300)
    bar = {'start': 300, 'close': 100}
    for i, symbol in enumerate(['BTC', 'ETH', 'SOL']):
        assert queue.add(symbol, bar, 600.2 + i * .1)
    assert queue.ready(600.1, 600.5) is None
    ready = queue.ready(600.5, 600.8)
    assert ready['inputs_available_at_upper'] == pytest.approx(600.4)
    assert ready['five']['BTC']['start'] == 300
    queue.committed(300)
    assert not queue.add('BTC', bar, 601)


def test_missing_batch_expires_instead_of_late_signal():
    queue = ClosedBatchQueue(['BTC', 'ETH'], 300)
    queue.add('BTC', {'start': 300}, 600.1)
    assert queue.ready(600.2, 600.4) is None
    with pytest.raises(ValueError, match='30-second'):
        queue.ready(631, 631.2)
    with pytest.raises(ValueError, match='Conflicting'):
        queue.add('BTC', {'start': 300, 'close': 101}, 632)
