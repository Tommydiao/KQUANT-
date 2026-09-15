"""Bounded renewal wait, not a guarantee of process or OS shutdown latency."""
import asyncio
import math
import time
from contextlib import asynccontextmanager
from .hybrid_failure_frames import failure_frames


@asynccontextmanager
async def capture_before_cleanup(record, root):
    try:
        yield
    except Exception as exc:
        evidence = {'exception_type': type(exc).__name__,
                    'observed_monotonic': time.perf_counter(),
                    'observed_local_utc_epoch': time.time(),
                    'scope': 'BODY_EXCEPTION_BEFORE_ENCLOSING_CONTEXT_CLEANUP',
                    'source_locations': failure_frames(exc, root)}
        try:
            record(evidence)
        except Exception as recording_error:
            exc.add_note('Pre-cleanup recording failed: ' + type(recording_error).__name__)
        raise


async def cancel_renewal(task, timeout=5.0):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Positive finite cleanup timeout required')
    started = time.perf_counter()
    if task is None:
        return {'state': 'NOT_PRESENT', 'elapsed_seconds': 0.0}
    task.cancel()
    done, _ = await asyncio.wait({task}, timeout=timeout)
    result = {'state': 'FINISHED' if done else 'TIMED_OUT',
              'elapsed_seconds': time.perf_counter() - started,
              'timeout_seconds': timeout, 'process_exit_guaranteed': False}
    if done and not task.cancelled():
        error = task.exception()
        if error is not None:
            result['error_type'] = type(error).__name__
    return result
