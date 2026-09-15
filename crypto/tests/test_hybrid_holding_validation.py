import pytest
from kquant_crypto.hybrid_holding_validation import audit_intervals, capital_time


def row(identity, start, end, symbol='BTCUSDT'):
    return {'trade_id': identity, 'signal_time': start, 'entry_time': start,
            'exit_time': end, 'symbol': symbol, 'mode': 'UP_TREND',
            'quantity': 2, 'entry_price': 10, 'entry_fee': .02, 'net_pnl': -1}


def test_long_hold_crosses_despite_old_six_hour_rule():
    result = audit_intervals([row('a', 86400-30000, 86400+600)], [86400])
    assert result['cuts'][0]['crossing_despite_signal_6h_before_boundary'] == 1
    assert result['holds_over_6h'] == 1
    assert result['future_fit_authorized'] is False


def test_intrabar_end_and_cross_asset_transitive_dependencies():
    result = audit_intervals([row('a', 0, 300), row('b', 600, 900, 'ETHUSDT'),
                              row('c', 1200, 1500, 'SOLUSDT')], [])
    assert len(result['dependency_groups']) == 1
    assert result['rows'][0]['information_end'] == 600


def test_duplicates_rejected_and_capital_time_not_trade_count():
    a = row('a', 0, 3600)
    with pytest.raises(ValueError, match='Duplicate'):
        audit_intervals([a, a], [])
    assert capital_time([a])['capital_hours'] == pytest.approx(20.02)
