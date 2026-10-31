from datetime import UTC, date, datetime
from types import SimpleNamespace
import pytest
from kquant import options_price_action_source as actions


def test_legacy_transport_cannot_fake_dated_request(tmp_path):
    context = SimpleNamespace(request=lambda *a, **k: pytest.fail('legacy request executed'))
    runner = SimpleNamespace(store=tmp_path/'sources', _context=lambda: context)
    now = datetime(2026,10,9,12,tzinfo=UTC)
    kwargs = dict(now=now, clock=lambda:now, scope=[{'symbol':'FCX','identity_status':'verified'}],
                  reviews={}, root=tmp_path)
    first = actions.refresh(runner, **kwargs)
    second = actions.refresh(runner, **kwargs)
    assert first['requests'] == second['requests'] == 0
    assert first['states'] == {'SOURCE_CAPABILITY_UNCONFIRMED': 1}


def test_actual_arguments_and_native_fields_are_preserved():
    sent = []
    class Dated:
        def corporate_actions(self, symbol, *, start_date, end_date):
            sent.append((symbol, start_date, end_date))
            return SimpleNamespace(items=[SimpleNamespace(id='1', date='20261009',
                act_type='Split', date_type='Effective', date_zone='ET')], has_more=True)
    raw, interface, query = actions.request_actions(SimpleNamespace(_context=lambda:Dated()),'FCX','2026-10-08','2026-10-09')
    assert sent == [('FCX.US',date(2026,10,8),date(2026,10,9))]
    now = datetime(2026,10,9,12,tzinfo=UTC)
    observation = actions.observe(raw,symbol='FCX',requested_at=now,received_at=now,
                                  target_session=date(2026,10,9),interface=interface,query=query)
    assert observation['raw_response']['has_more'] is True
    assert observation['raw_response']['items'][0]['date'] == '20261009'
    assert observation['complete'] is False


def test_symbol_only_sdk_does_not_receive_invented_dates():
    called = []
    context = SimpleNamespace(corporate_actions=lambda symbol: called.append(symbol))
    with pytest.raises(actions.ActionCapabilityUnavailable):
        actions.request_actions(SimpleNamespace(_context=lambda:context),'FCX','2026-10-08','2026-10-09')
    assert called == []
