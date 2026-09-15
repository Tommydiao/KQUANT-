"""Immutable process-local observation bounds; never infer a window from quotes."""
import math


def planned_window(registered_at, duration, *, lead_seconds=2):
    if not all(type(x) in (int, float) and math.isfinite(x)
               for x in (registered_at, duration, lead_seconds)):
        raise ValueError('Finite monotonic registration required')
    if registered_at <= 0 or not 30 <= duration <= 259200 or lead_seconds <= 0:
        raise ValueError('Invalid observation window')
    start = registered_at + lead_seconds
    return {'version': 'MONOTONIC_WINDOW_V1', 'registered_monotonic': registered_at,
            'start_monotonic': start, 'end_monotonic': start + duration,
            'duration_seconds': duration, 'clock_basis': 'time.perf_counter',
            'scope': 'SINGLE_PROCESS_RUN_NOT_REBOOT_RESUMABLE',
            'denominator': 'FULL_PLANNED_WINDOW_INCLUDING_BOOTSTRAP_GAPS_AND_UNOBSERVED_TIME'}


def registration_wait(window, persisted_at):
    expected = planned_window(window['registered_monotonic'], window['duration_seconds'],
                              lead_seconds=window['start_monotonic'] - window['registered_monotonic'])
    if window != expected or type(persisted_at) not in (int, float) or not math.isfinite(persisted_at):
        raise ValueError('Observation window binding mismatch')
    if not window['registered_monotonic'] <= persisted_at < window['start_monotonic']:
        raise ValueError('Window must be persisted before observation starts')
    return window['start_monotonic'] - persisted_at


def connection_failure_detail(exc):
    # Keep protocol codes, not arbitrary remote text or connection URLs.
    result = {}
    for name in ('rcvd', 'sent'):
        code = getattr(getattr(exc, name, None), 'code', None)
        result[name + '_close_code'] = int(code) if isinstance(code, int) else None
    result['close_order_received_then_sent'] = getattr(exc, 'rcvd_then_sent', None)
    return result
