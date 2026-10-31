from datetime import date, timedelta
import pytest
import first_hour as window


def test_calendar_and_original_deadlines():
    value = window.schedule(date(2026, 10, 22))
    assert len(value['checkpoints']) == 11
    assert value['checkpoints'][0]['at'].isoformat() == '2026-10-22T13:35:00+00:00'
    assert value['checkpoints'][-1]['at'].isoformat() == '2026-10-22T14:25:00+00:00'
    assert value['cutoff'].isoformat() == '2026-10-22T14:30:00+00:00'
    assert all(p['deadline']-p['at'] == timedelta(seconds=300) for p in value['checkpoints'])
    assert window.schedule(date(2026, 10, 24))['state'] == 'MARKET_CLOSED'


def test_dst_uses_project_calendar():
    assert window.schedule(date(2026, 11, 2))['checkpoints'][0]['at'].hour == 14


def test_old_policy_unchanged_and_risk_preserved():
    parent = window.s0.load_policy()
    newer = window.policies()
    assert parent['checkpoint_minutes'] == [5, 10, 15, 20, 25]
    assert parent['entry_window_minutes'] == 30
    assert window.s0.load_policy() == parent
    for p in newer.values():
        assert p['contracts'] == parent['contracts']
        assert p['signal_deadline_seconds'] == 300
        assert p['qualified_publication_enabled'] is False
        assert p['policy_hash'] != parent['policy_hash']
    assert newer['S1']['require_previous_close_direction'] is False


@pytest.mark.parametrize('offset', window.OFFSETS)
def test_real_evaluators_all_eleven_points_missing_data(offset):
    opening, closing = window.session_bounds_utc(date(2026, 10, 22))
    end = opening + timedelta(minutes=offset)
    args = dict(symbol='NVDA', bars=[], history=[], reference={}, opening=opening,
                closing=closing, now=end+timedelta(seconds=1), checkpoint=end,
                scope_hash='TEST_ONLY')
    rows = window.evaluate(**args)
    assert len(rows) == 4
    assert all(r['state'] == 'INCOMPLETE' for r in rows)
    assert len({r['policy_hash'] for r in rows}) == 2
    with pytest.raises(ValueError, match='ORIGINAL_DEADLINE'):
        window.evaluate(**{**args, 'now': end+timedelta(seconds=300)})


def test_reconciliation_not_checkpoint():
    opening, closing = window.session_bounds_utc(date(2026, 10, 22))
    with pytest.raises(ValueError, match='INVALID_FIRST_HOUR'):
        window.evaluate(opening=opening, closing=closing,
                        now=opening+timedelta(minutes=60), checkpoint=opening+timedelta(minutes=60))
