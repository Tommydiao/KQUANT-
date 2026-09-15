import pytest

from kquant_crypto.hybrid_mc_event_contract import RiskEvent, freeze_events


def test_event_boundaries_and_nonfinite():
    event = RiskEvent('absolute', 'absolute_high_watermark_drawdown', .1)
    assert event.classify({'absolute_high_watermark_drawdown': .1})
    assert not event.classify({'absolute_high_watermark_drawdown': .099})
    for x in (None, float('nan'), True, -1):
        with pytest.raises(ValueError):
            event.classify({'absolute_high_watermark_drawdown': x})
    loss = RiskEvent('net_loss', 'terminal_net_change', 0)
    assert not loss.classify({'terminal_net_change': 0})
    assert loss.classify({'terminal_net_change': -.01})


def test_original_daily_line_cannot_be_overridden():
    with pytest.raises(ValueError):
        RiskEvent('day', 'daily_loss_line_breached', .1)
    event = RiskEvent('day', 'daily_loss_line_breached')
    with pytest.raises(ValueError):
        event.classify({'daily_loss_line_breached': None})


def test_family_budget_and_reproducibility():
    events = [RiskEvent('daily', 'daily_loss_line_breached'),
              RiskEvent('loss', 'terminal_net_change', 0)]
    kwargs = dict(policy_hash='a'*64, costs=(1, 2), input_exposure='EXPOSED_RESEARCH')
    with pytest.raises(ValueError):
        freeze_events(events, comparison_budget=8, **kwargs)
    result = freeze_events(events, comparison_budget=16, **kwargs)
    assert result == freeze_events(events, comparison_budget=16, **kwargs)
    assert result['admission'] == 'ABSTAIN'
    assert not result['G4_passed'] and not result['execution_enabled']
