import pytest
from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.hybrid_mc_portfolio import ExistingExposurePortfolio, drawdowns
from kquant_crypto.strategy_dual_mode_v1 import Bar


def test_pending_reaches_original_entry_path_without_new_reservations(monkeypatch):
    p = ExistingExposurePortfolio(load_policy(candidate='A'), {}, exit_candidate='ORIGINAL')
    p.pending['BTCUSDT'] = {'existing': True}
    calls = []
    def enter(symbol, price, time):
        calls.append((symbol, price, time))
        p.pending.pop(symbol)
    monkeypatch.setattr(p, '_enter', enter)
    p.on_path_batch({'BTCUSDT': Bar(3600, 100, 102, 99, 101, 10)}, {}, 3900)
    assert calls == [('BTCUSDT', 100, 3600)]
    p._reserve('BTCUSDT', {'anything': 'not evaluated'}, 3900)
    assert p.pending == {}
    assert p.events[-1]['kind'] == 'MC_NEW_SIGNAL_SUPPRESSED'


def test_historical_drawdown_not_reset_at_start():
    result = drawdowns(9800, 9900, 10000)
    assert result['historical'] == pytest.approx(.02)
    assert result['incremental'] == pytest.approx(100 / 9900)
    assert drawdowns(10100, 9900, 10000)['historical'] == 0
