from dataclasses import replace

import pytest

from kquant_crypto.hybrid_contracts import DecisionTimeline, RiskLines
from kquant_crypto.hybrid_identity import economic_signal_id, evaluation_id, entry_intent_id


def timeline():
    return DecisionTimeline(36000, 36001, 36001, 36002, 36003, 36004, 36004, 36301)


def test_delayed_decision_never_fills_past_open():
    t = timeline()
    assert not t.permits_fill(36000, 36005)
    assert not t.permits_fill(36004, 36004)
    assert t.permits_fill(36300, 36300)
    assert not t.permits_fill(36302, 36302)


def test_late_past_quote_and_future_receipt_rejected():
    t = timeline()
    assert not t.permits_fill(36002, 36006)
    assert not t.permits_fill(36006, 36005)
    assert t.permits_fill(36005, 36006)


@pytest.mark.parametrize('field,value', [
    ('evaluation_finished_at', 36001),
    ('decision_committed_at', 36002),
    ('earliest_fill_at', 36003),
    ('signal_expires_at', 36003),
    ('received_at', float('nan')),
    ('signal_time', float('inf')),
])
def test_invalid_timeline_rejected(field, value):
    with pytest.raises(ValueError):
        replace(timeline(), **{field: value})


def test_model_and_feature_availability_contract():
    t = timeline()
    t.validate_inputs(feature_available_at=(36001,), model_available_at=36001)
    with pytest.raises(ValueError):
        t.validate_inputs(feature_available_at=(36002,), model_available_at=36001)
    with pytest.raises(ValueError):
        t.validate_inputs(feature_available_at=(), model_available_at=36003)


def test_signal_identity_does_not_include_news_or_model():
    signal = economic_signal_id('base', 'policy', 'BTCUSDT', 'UP_TREND', 36000, 1)
    first = evaluation_id(signal, {'news': 'one', 'portfolio_version': 1})
    later = evaluation_id(signal, {'news': 'two', 'portfolio_version': 1})
    assert first != later
    assert entry_intent_id('run', 'T+B', signal) == entry_intent_id('run', 'T+B', signal)
    assert entry_intent_id('run', 'T', signal) != entry_intent_id('run', 'T+B', signal)
    assert evaluation_id(signal, {'a': 1, 'b': 2}) == evaluation_id(signal, {'b': 2, 'a': 1})


def test_daily_budget_not_reset_from_current_equity():
    risk = RiskLines(10000, 9910, 10200, .01)
    assert risk.daily_loss_line == 9900
    assert risk.remaining_daily_loss_budget == 10
    assert risk.daily_breached(9900)
    assert risk.hwm_drawdown(9910) > risk.incremental_drawdown(9910)


@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf')])
def test_invalid_risk_baselines_rejected(value):
    with pytest.raises(ValueError):
        RiskLines(value, 9910, 10200, .01)
