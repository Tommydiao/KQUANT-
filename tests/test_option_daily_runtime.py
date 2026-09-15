from datetime import UTC, datetime, timedelta
import json
import sys
from types import SimpleNamespace

import pytest

from kquant.option_event_coverage import CATEGORIES, import_coverage, option_event_context
from kquant.option_runtime import OptionProcessLock, checkpoint, record_task
from kquant.options_radar_supervisor import OptionRadarSupervisor
from kquant.realtime_instructions import AlertEventHub
from kquant.stock_store import connect
from kquant import options_radar as radar
from test_options_radar import _seed_plan

NOW = datetime(2026, 9, 14, 13, 40, tzinfo=UTC)


def coverage(category):
    return dict(symbol='*' if category == 'macro' else 'SPY', category=category,
        reviewer='fixture-only', source_url='https://example.test/calendar', source_hash='a' * 64,
        coverage_start=(NOW-timedelta(days=1)).isoformat(), coverage_end=(NOW+timedelta(days=10)).isoformat(),
        available_at=NOW.isoformat(), reviewed_at=NOW.isoformat(), valid_until=(NOW+timedelta(days=8)).isoformat(),
        review_status='reviewed', events=[], no_events_confirmed=True)


def test_calendar_is_option_only_pit_idempotent_and_expires(tmp_path):
    db = tmp_path/'stock.db'
    assert option_event_context(db, 'SPY', NOW.isoformat())['trade_eligible'] is False
    for category in CATEGORIES:
        first = import_coverage(db, coverage(category), now=NOW)
        assert first == import_coverage(db, coverage(category), now=NOW)
    assert option_event_context(db, 'SPY', NOW.isoformat())['trade_eligible'] is True
    assert option_event_context(db, 'SPY', (NOW-timedelta(seconds=1)).isoformat())['trade_eligible'] is False
    assert option_event_context(db, 'SPY', (NOW+timedelta(days=8)).isoformat())['trade_eligible'] is False
    assert option_event_context(db, 'QQQ', NOW.isoformat())['trade_eligible'] is False
    with connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM option_event_coverage').fetchone()[0] == 4


def test_calendar_unknown_is_not_no_events_and_new_revision_blocks(tmp_path):
    db = tmp_path/'stock.db'
    with pytest.raises(ValueError, match='confirm no events'):
        import_coverage(db, {**coverage('earnings'), 'no_events_confirmed':False}, now=NOW)
    with pytest.raises(ValueError, match='future-dated'):
        import_coverage(db, {**coverage('earnings'), 'reviewed_at':(NOW+timedelta(seconds=1)).isoformat()}, now=NOW)
    for category in CATEGORIES:
        import_coverage(db, coverage(category), now=NOW)
    item = coverage('earnings')
    item['events'] = [dict(name='test earnings', start_at=(NOW+timedelta(days=1)).isoformat(),
                           end_at=(NOW+timedelta(days=1)).isoformat(), blocks_entry=True)]
    import_coverage(db, item, now=NOW+timedelta(seconds=1))
    result = option_event_context(db, 'SPY', (NOW+timedelta(seconds=2)).isoformat())
    assert result['trade_eligible'] is False and len(result['blocking_events']) == 1


def test_process_lock_is_exclusive_and_releases(tmp_path):
    first, second = (OptionProcessLock(tmp_path/'stock.db', 'test') for _ in range(2))
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


def supervisor(tmp_path, monkeypatch):
    monkeypatch.setattr('kquant.options_radar_supervisor.market_schedule', lambda *a, **kw:
        dict(is_trading_day=True, regular_close_utc='2026-09-14T20:00:00+00:00'))
    return OptionRadarSupervisor(tmp_path/'stock.db', AlertEventHub())


def test_closed_session_never_backfills_a_premarket(tmp_path, monkeypatch):
    service = supervisor(tmp_path, monkeypatch)
    monkeypatch.setattr('kquant.options_radar_supervisor.run_premarket_radar', lambda *a, **kw: pytest.fail('unexpected scan'))
    assert service.cycle_once(NOW.replace(hour=20))['reason'] == 'market_closed_no_premarket_backfill'


def test_restart_keeps_completed_bucket_and_failed_report_does_not_block_tracking(tmp_path, monkeypatch):
    first = supervisor(tmp_path, monkeypatch)
    monkeypatch.setattr('kquant.options_radar_supervisor.latest_premarket_report', lambda *a, **kw: {'status':'not_run'})
    record_task(first.db_path, 'premarket:2026-09-14', 'premarket', '2026-09-14', 'failed', {'error_type':'TimeoutError'}, NOW)
    calls = []
    monkeypatch.setattr('kquant.options_radar_supervisor.refresh_intraday_radar', lambda *a, **kw: calls.append(1) or {'updated':0})
    first.cycle_once(NOW)
    second = supervisor(tmp_path, monkeypatch)
    second.cycle_once(NOW+timedelta(seconds=30))
    assert calls == [1]
    assert checkpoint(first.db_path, f'intraday:{NOW.isoformat()}')['status'] == 'completed'


def test_catchup_keeps_actual_decision_time(tmp_path, monkeypatch):
    service = supervisor(tmp_path, monkeypatch)
    monkeypatch.setattr('kquant.options_radar_supervisor.latest_premarket_report', lambda *a, **kw: {'status':'not_run'})
    seen = []
    monkeypatch.setattr('kquant.options_radar_supervisor.run_premarket_radar', lambda *a, **kw: seen.append(kw['now']) or {'run_id':'fixture', 'opportunities':[]})
    at = NOW.replace(hour=13, minute=0)
    service.cycle_once(at)
    assert seen == [at]
    task = checkpoint(service.db_path, 'premarket:2026-09-14')
    assert json.loads(task['detail_json'])['catch_up'] is True


def test_yesterday_is_not_current_but_active_watch_remains(tmp_path):
    db = tmp_path/'stock.db'
    plan = _seed_plan(db, NOW)
    assert radar.list_option_signals(db, now=NOW+timedelta(days=1))['count'] == 0
    radar.set_option_watch(db, plan)
    assert radar.list_option_signals(db, now=NOW+timedelta(days=1))['count'] == 1


def test_cross_day_manual_exit_is_not_a_fill_and_recovers_outbox(tmp_path, monkeypatch):
    db = tmp_path/'stock.db'
    plan = _seed_plan(db, NOW)
    radar.record_option_manual_outcome(db, dict(plan_id=plan, status='open', entry_time=NOW.isoformat(), entry_price=1, contracts=1))
    with connect(db) as conn:
        conn.execute("UPDATE option_plans SET exit_reminder_at=NULL")
        conn.commit()
    monkeypatch.setattr(radar, 'option_contract_snapshot', lambda *a, **kw: pytest.fail('deadline monitor must not wait on quotes'))
    original = radar._create_alert
    monkeypatch.setattr(radar, '_create_alert', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('crash')))
    with pytest.raises(RuntimeError):
        radar.monitor_option_plans(db, now=NOW+timedelta(days=1))
    monkeypatch.setattr(radar, '_create_alert', original)
    for _ in range(2):
        result = radar.monitor_option_plans(db, now=NOW+timedelta(days=1))
        assert result['fills_generated'] == 0
    assert radar.list_option_signals(db,now=NOW+timedelta(days=1))['count']==1
    with connect(db) as conn:
        assert conn.execute('SELECT state FROM option_plans').fetchone()[0] == 'EXIT_REVIEW'
        assert conn.execute('SELECT COUNT(*) FROM option_delivery_outbox').fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM option_state_events WHERE event_type='monitor_deadline'").fetchone()[0] == 1
        assert conn.execute('SELECT status FROM option_manual_outcomes').fetchone()[0] == 'open'
        assert conn.execute('SELECT COUNT(*) FROM option_outcomes').fetchone()[0] == 0


def test_outbox_does_not_send_in_scan_and_replayed_delivery_is_bounded(tmp_path, monkeypatch):
    db = tmp_path/'stock.db'
    _seed_plan(db, NOW)
    sent = []
    monkeypatch.setattr('kquant.web_push._in_quiet_hours', lambda *a: False)
    monkeypatch.setattr(radar, 'deliver_web_push', lambda *a, **kw: sent.append(kw) or {'status':'sent'})
    payload = radar.option_signal_detail(db, 'opp-1')
    radar._create_alert(db, payload)
    radar._create_alert(db, payload)
    assert sent == []
    radar.dispatch_option_alerts(db)
    radar.dispatch_option_alerts(db)
    assert len(sent) == 1


def test_push_dedup_survives_retry_and_max_attempts_are_lifetime(tmp_path, monkeypatch):
    from kquant import web_push as push
    db = tmp_path/'stock.db'
    for key in ('KQUANT_WEB_PUSH_PRIVATE_KEY', 'KQUANT_WEB_PUSH_PUBLIC_KEY'):
        monkeypatch.setenv(key, 'fixture-not-a-key')
    monkeypatch.setenv('KQUANT_WEB_PUSH_ENABLED','true')
    push.subscribe(db, {'endpoint':'https://example.test/push','keys':{'p256dh':'fixture','auth':'fixture'}})
    calls=[]
    class PushError(Exception): pass
    def fail(**kw):
        calls.append(kw)
        raise PushError()
    monkeypatch.setitem(sys.modules, 'pywebpush', SimpleNamespace(webpush=fail, WebPushException=PushError))
    for _ in range(2):
        push.deliver_web_push(db, alert_id='failed-alert', severity='RISK', payload={})
    assert len(calls) == 3
    monkeypatch.setitem(sys.modules, 'pywebpush', SimpleNamespace(webpush=lambda **kw:calls.append(kw), WebPushException=PushError))
    for _ in range(2):
        push.deliver_web_push(db, alert_id='success-alert', severity='RISK', payload={})
    assert len(calls) == 4


def test_quiet_hours_defer_both_transports_but_not_risk(tmp_path, monkeypatch):
    db=tmp_path/'stock.db'
    _seed_plan(db,NOW)
    monkeypatch.setattr('kquant.web_push._in_quiet_hours',lambda *a:True)
    monkeypatch.setenv('KQUANT_ENABLE_NOTIFICATIONS','true')
    sent=[]
    monkeypatch.setattr(radar,'deliver_web_push',lambda *a,**kw:sent.append('push') or {'status':'sent'})
    monkeypatch.setattr(radar,'dispatch_personal_notification',lambda *a,**kw:sent.append('telegram') or {'status':'sent'})
    payload=radar.option_signal_detail(db,'opp-1')
    radar._create_alert(db,payload)
    assert radar.dispatch_option_alerts(db)['results'][0]['status']=='deferred'
    assert sent==[]
    radar._create_alert(db,{**payload,'status':'EXIT_REVIEW','material_state_hash':'risk'})
    radar.dispatch_option_alerts(db)
    assert sent==['push','telegram']


def test_opening_confirmation_requires_exact_contiguous_closed_bars():
    start=NOW-timedelta(minutes=10)
    bars=[{'open_time':(start+timedelta(minutes=i)).isoformat(),'bar_state':'closed_candle'} for i in (0,5)]
    assert len(radar._closed_opening_bars({'candles':bars},start,NOW))==2
    assert radar._closed_opening_bars({'candles':[bars[0],dict(bars[1],open_time=NOW.isoformat())]},start,NOW+timedelta(minutes=5))==[]
    assert radar._closed_opening_bars({'candles':[bars[0],dict(bars[1],bar_state='forming')]},start,NOW)==[]


def test_missing_quote_receipt_is_never_fabricated(tmp_path):
    db=tmp_path/'stock.db'
    plan=_seed_plan(db,NOW)
    evidence=radar.persist_option_quote_evidence(db,plan,{'contract_symbol':'SPY-C','provider_status':'unavailable'},'entry')
    assert evidence['received_at'] is None
    assert evidence['execution_quality']=='UNAVAILABLE'
    assert evidence['strict_fill_eligible'] is False


def test_v14_upgrade_and_backup_keep_option_evidence(tmp_path, monkeypatch):
    import sqlite3
    from kquant.db import migrations
    db=tmp_path/'stock.db'
    registry=migrations._migrations
    with monkeypatch.context() as scope:
        scope.setattr(migrations,'_migrations',lambda:tuple(m for m in registry() if m.version<=14))
        scope.setattr(migrations,'LATEST_SCHEMA_VERSION',14)
        _seed_plan(db,NOW)
    backup=tmp_path/'backup.db'
    with sqlite3.connect(db) as source, sqlite3.connect(backup) as destination:
        before=source.execute('SELECT * FROM option_plans').fetchall()
        source.backup(destination)
    migrations.apply_sqlite_migrations(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT * FROM option_plans').fetchall()==before
        assert conn.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==15
    with sqlite3.connect(backup) as conn:
        assert conn.execute('SELECT * FROM option_plans').fetchall()==before
        assert conn.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==14
