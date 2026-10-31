"""Isolated real Supervisor/Worker assembly. Never reads production databases."""
from __future__ import annotations

import argparse
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))


def prepare(root):
    from kquant.db.migrations import apply_sqlite_migrations
    from kquant.stock_watchlist import ensure_stock_watchlist_seed
    from kquant.options_one_minute import initialize
    from kquant.options_opening_trend_store import initialize as opening_init
    from kquant.options_full_watch import initialize_full_watch_store
    from kquant.options_two_hour import initialize as queue_init
    from kquant.options_signal_copilot import initialize_copilot_store
    stores = dict(main=root / 'work/kquant_us.sqlite3',
                  minute=root / 'work/options_one_minute-epoch-20261008/one_minute.sqlite3',
                  opening_research=root / 'work/options_one_minute/opening_trend_research.sqlite3',
                  full_watch=root / 'work/options_full_watch/full_watch.sqlite3',
                  signal_copilot=root / 'work/options_signal_copilot/signal_copilot.sqlite3')
    for path in stores.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    apply_sqlite_migrations(stores['main'])
    ensure_stock_watchlist_seed(stores['main'])
    initialize(stores['minute'])
    opening_init(stores['opening_research'])
    initialize_full_watch_store(stores['full_watch'])
    queue_init(stores['full_watch'])
    initialize_copilot_store(stores['signal_copilot'])
    binding = dict(schema='KQUANT_NEW_EPOCH_RUNTIME_PATHS_V1', runtime_root=str(root),
        epoch_id='TEST_ONLY-P12', data_scope_acceptance_sha256='a' * 64, session='2026-10-08',
        minute_path=str(stores['minute']), opening_research_path=str(stores['opening_research']),
        stores={key: str(value) for key, value in stores.items()})
    target = root / 'binding.json'
    target.write_text(json.dumps(binding), encoding='utf-8')
    return target


def child(root, seconds, fault):
    binding = root / 'binding.json'
    os.environ.update(KQUANT_RUNTIME_DATA_ROOT=str(root), KQUANT_RUNTIME_PATH_BINDING=str(binding),
        KQUANT_RUNTIME_PATH_BINDING_SHA256=sha256(binding.read_bytes()).hexdigest(),
        KQUANT_OPTION_RADAR_ENABLED='true', KQUANT_OPTION_RADAR_MODE='foundation',
        KQUANT_OPTION_ONE_MINUTE_SHADOW_ENABLED='true', KQUANT_OPTION_TWO_HOUR_RESEARCH_ENABLED='false',
        KQUANT_OPTION_FORWARD_PAPER_ENABLED='false', KQUANT_BACKEND_RELEASE_ID='TEST_ONLY-P12-BOOTSTRAP',
        LOCALAPPDATA=str(root / 'private-test-config'))
    stores = {k: Path(v) for k, v in json.loads(binding.read_text())['stores'].items()}
    if fault == 'queue_schema':
        import sqlite3
        with closing(sqlite3.connect(stores['full_watch'])) as db, db:
            db.execute('DROP TABLE two_hour_jobs')
    from unittest.mock import patch
    from kquant import options_one_minute_runtime as runtime
    from kquant.options_radar_supervisor import OptionRadarSupervisor
    from scripts.test_clock_transport import LoopbackClockTransport
    from datetime import UTC, datetime, timedelta
    if fault == 'opening_file':
        stores['opening_research'].unlink()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (datetime(2026, 10, 11, 12, tzinfo=UTC) + timedelta(seconds=time.monotonic() - started)).astimezone(tz)

    class Transport:
        def event_queue(self, *args, **kwargs):
            return queue.Queue()

        def static_info(self, *args, **kwargs):
            return []

        def release_subscriptions(self, *args):
            pass

    class Hub:
        def publish(self, item):
            pass

    started = time.monotonic()
    snapshots = []
    errors = []
    # Only external quote/time boundaries are substituted; constructors/start/run are real.
    with patch.object(runtime, 'longbridge_runtime', return_value=Transport()), \
         patch.object(runtime, 'datetime', Clock), \
         patch('kquant.research_runtime_health.datetime', Clock), \
         patch('kquant.options_radar_supervisor.datetime', Clock), \
         patch('kquant.stock_signals.api_stock_quotes_batch', return_value={'items': [], 'test_only': True}), \
         LoopbackClockTransport():
        supervisor = OptionRadarSupervisor(stores['main'], Hub())
        try:
            supervisor.start()
            while time.monotonic() - started < seconds:
                status = supervisor.one_minute_worker_status()
                snapshots.append(status)
                if status.get('state') == 'FAILED_INIT':
                    break
                time.sleep(.2)
        except Exception as exc:
            errors.append(type(exc).__name__)
        finally:
            supervisor.stop()
        worker = supervisor._one_minute_worker
        final = supervisor.one_minute_worker_status()
        lanes = {name: str(getattr(getattr(worker, name, None), 'queue_path', ''))
                 for name in ('qualification_lane', 'recovery_lane')}
        opening = str(getattr(getattr(worker, 'trend_lane', None), 'path', ''))
    time.sleep(.2)
    alive = [t.name for t in threading.enumerate() if t is not threading.main_thread()]
    report = dict(test_only=True, actual_supervisor_start=True, actual_worker_init_run=True,
        clock_monitor_tick='REAL', clock_child='REAL_MODULE', clock_external_transport='TEST_ONLY_LOOPBACK_UDP',
        transport='EXPLICIT_TEST_DOUBLE', elapsed=time.monotonic()-started, fault=fault,
        stores={k: str(v) for k, v in stores.items()}, snapshots=snapshots, final=final,
        lanes=lanes, opening=opening, errors=errors, alive_threads=alive,
        databases=sorted(str(p) for p in root.rglob('*.sqlite3')),
        forbidden_sibling_exists=stores['minute'].with_name('opening_trend_research.sqlite3').exists())
    (root / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not fault:
        assert not errors, report
        assert any(s.get('research_ready') and s.get('state') == 'WAIT_MARKET' for s in snapshots), final
        assert final.get('loop_count', 0) >= 2, final
        assert opening == str(stores['opening_research']), opening
        assert set(lanes.values()) == {str(stores['full_watch'])}, lanes
        assert len(report['databases']) == 5, report['databases']
    else:
        assert final.get('state') == 'FAILED_INIT', final
        assert final.get('error_id'), final
        assert not final.get('research_ready'), final
    assert not report['forbidden_sibling_exists']
    assert not alive, alive
    print(json.dumps(dict(result='PASS', fault=fault, elapsed=report['elapsed'],
                         final_state=final['state'], loops=final.get('loop_count'), report=str(root/'report.json'))))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', type=Path)
    parser.add_argument('--seconds', type=float, default=12)
    parser.add_argument('--fault', choices=['queue_schema', 'opening_file'], default=None)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.child:
        child(args.child, args.seconds, args.fault)
        return
    if args.out is None or not args.out.name.startswith('TEST_ONLY-') or args.out.exists():
        raise ValueError('FRESH_EXPLICIT_TEST_ONLY_DIRECTORY_REQUIRED')
    for key in list(os.environ):
        if key.startswith('KQUANT_'):
            del os.environ[key]
    root = args.out.resolve()
    root.mkdir(parents=True)
    prepare(root)
    command = [sys.executable, __file__, '--child', str(root), '--seconds', str(args.seconds)]
    if args.fault:
        command += ['--fault', args.fault]
    result = subprocess.run(command, timeout=args.seconds+45, capture_output=True, text=True)
    (root/'child.stderr.log').write_text(result.stderr, encoding='utf-8')
    print(result.stdout)
    if result.returncode:
        print(result.stderr[-8000:])
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
