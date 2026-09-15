"""Bounded public-observation recovery, with separate immutable run segments."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.candidate_forward import _process_lock
from kquant_crypto.hybrid_delivery import atomic_json, load, sha


def retry_allowed(exit_code, report):
    return (exit_code != 0 and report.get('state') == 'FAILED'
            and report.get('execution_enabled') is False
            and report.get('failure', {}).get('type') in ('ConnectionClosedError', 'ConnectError'))


def child_environment():
    keys = {'PATH', 'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'TEMP', 'TMP',
            'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'NUMBER_OF_PROCESSORS',
            'PROCESSOR_ARCHITECTURE', 'COMSPEC'}
    return {k: v for k, v in os.environ.items() if k.upper() in keys}


def write_status(path, state):
    for attempt in range(5):
        try:
            atomic_json(path, state)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(.05 * 2 ** attempt)


def stop_owned_child(child, segment):
    marker_written = False
    try:
        if segment.is_dir():
            (segment / 'STOP').touch(exist_ok=True)
            marker_written = True
    except OSError:
        pass
    forced = False
    try:
        child.wait(timeout=45)
    except subprocess.TimeoutExpired:
        child.terminate()
        child.wait(timeout=15)
        forced = True
    return {'stop_marker_written': marker_written, 'forced_owned_child_termination': forced,
            'exit_code': child.returncode}


def execute(out, seconds, max_segments):
    if not 30 <= seconds <= 259200 or not 1 <= max_segments <= 12:
        raise ValueError('Bounded duration and segment budget required')
    out = Path(out).resolve()
    if not out.is_relative_to(ROOT / 'outputs/hybrid_regime_v1'):
        raise ValueError('Independent observation series required')
    runner = ROOT / 'scripts/run_hybrid_continuous_observer.py'
    runner_hash = sha(runner)
    lock_path = ROOT / 'work/hybrid_delivery/public_observation_series.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _process_lock(lock_path):
        out.mkdir(parents=True, exist_ok=False)
        registered = time.perf_counter()
        start, end = registered + 2, registered + 2 + seconds
        contract = {'scope': 'BOUNDED_PUBLIC_OBSERVATION_SERIES', 'execution_enabled': False,
                    'registered_monotonic': registered, 'start_monotonic': start, 'end_monotonic': end,
                    'max_segments': max_segments, 'duration_seconds': seconds,
                    'runner_sha256': runner_hash, 'manager_sha256': sha(Path(__file__)),
                    'retry': 'Only terminal ConnectionClosedError/ConnectError on unchanged public endpoints; new ledger and warmup each time',
                    'continuity': 'SEGMENTS_NEVER_COUNT_AS_UNINTERRUPTED_72H',
                    'max_series_bytes': 2 * 1024**3, 'python': sys.executable}
        atomic_json(out / 'preregistration.json', contract)
        if time.perf_counter() >= start:
            raise ValueError('Series registration missed start; no child launched')
        time.sleep(start - time.perf_counter())
        attempts = []
        state = {'state': 'STARTING', 'execution_enabled': False, 'G3_passed': False,
                 'uninterrupted_72h_passed': False, 'attempts': attempts}

        def publish(name, **fields):
            state.update(state=name, elapsed_seconds=time.perf_counter() - start, **fields)
            write_status(out / 'status.json', state)

        for number in range(1, max_segments + 1):
            remaining = int(end - time.perf_counter())
            if (out / 'STOP').exists() or remaining < 30:
                publish('STOPPED' if (out / 'STOP').exists() else 'BUDGET_ENDED')
                break
            if sha(runner) != runner_hash:
                publish('BLOCKED_SOURCE_CHANGED')
                break
            if sum(p.stat().st_size for p in out.rglob('*') if p.is_file()) >= 2 * 1024**3:
                publish('BLOCKED_STORAGE_BUDGET')
                break
            segment = out / f'segment_{number:03d}'
            attempt = {'segment': str(segment.relative_to(ROOT)), 'started_monotonic': time.perf_counter()}
            attempts.append(attempt)
            with (out / f'segment_{number:03d}.stdout.log').open('xb') as stdout, \
                    (out / f'segment_{number:03d}.stderr.log').open('xb') as stderr:
                command = [sys.executable, str(runner), '--output', str(segment), '--seconds', str(remaining)]
                child = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr,
                                         env=child_environment())
                attempt['pid'] = child.pid
                stop_at = None
                while child.poll() is None:
                    now = time.perf_counter()
                    should_stop = (out / 'STOP').exists() or now >= end
                    if should_stop:
                        if stop_at is None:
                            stop_at = now
                        # The child owns directory creation, even during bootstrap.
                        if segment.is_dir():
                            (segment / 'STOP').touch(exist_ok=True)
                    if stop_at is not None and now - stop_at > 45:
                        child.terminate()
                        child.wait(timeout=15)
                        attempt['forced_owned_child_termination'] = True
                        publish('BLOCKED_CHILD_STOP_TIMEOUT', active_pid=None)
                        break
                    try:
                        publish('STOPPING' if stop_at is not None else 'RUNNING', active_pid=child.pid)
                    except OSError as exc:
                        attempt.update(stop_owned_child(child, segment))
                        state.update(state='BLOCKED_STATUS_IO', active_pid=None,
                                     publication_error_type=type(exc).__name__)
                        # New terminal file does not replace a possibly locked heartbeat.
                        try:
                            atomic_json(out / 'manager_failure.json', state)
                        except OSError:
                            state['failure_file_write_failed'] = True
                        print(json.dumps(state), flush=True)
                        return 1
                    time.sleep(2)
                attempt['exit_code'] = child.returncode
                attempt['ended_monotonic'] = time.perf_counter()
            if attempt.get('forced_owned_child_termination'):
                break
            report_path = segment / 'report.json'
            report = load(report_path) if report_path.exists() else {}
            attempt['report_sha256'] = sha(report_path) if report_path.exists() else None
            attempt['terminal_state'] = report.get('state', 'NO_TERMINAL_REPORT')
            if (out / 'STOP').exists() or time.perf_counter() >= end:
                terminal_ok = child.returncode == 0 and report.get('state') in ('STOPPED', 'COMPLETED')
                publish(('STOPPED' if (out / 'STOP').exists() else 'BUDGET_ENDED') if terminal_ok
                        else 'BUDGET_OR_STOP_WITH_CHILD_FAILURE', active_pid=None)
                break
            if not retry_allowed(child.returncode, report):
                publish('SEGMENT_COMPLETED' if child.returncode == 0 and report.get('state') == 'COMPLETED'
                        else 'BLOCKED_NONRETRYABLE_FAILURE', active_pid=None)
                break
            delay = min(300, 15 * 2 ** (number - 1))
            attempt['backoff_seconds'] = delay
            publish('BACKOFF', active_pid=None)
            until = min(end, time.perf_counter() + delay)
            while time.perf_counter() < until and not (out / 'STOP').exists():
                time.sleep(min(2, until - time.perf_counter()))
        else:
            publish('SEGMENT_BUDGET_EXHAUSTED', active_pid=None)
        atomic_json(out / 'report.json', state)
        return 0 if state['state'] in ('STOPPED', 'BUDGET_ENDED', 'SEGMENT_COMPLETED') else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--seconds', type=int, default=259200)
    parser.add_argument('--max-segments', type=int, default=12)
    args = parser.parse_args()
    return execute(ROOT / args.output, args.seconds, args.max_segments)


if __name__ == '__main__':
    sys.exit(main())
