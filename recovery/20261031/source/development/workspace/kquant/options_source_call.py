"""Bound waiting on one shared-transport call without replacing a stuck worker."""
from threading import Event, Lock, Thread
from time import monotonic


class SourceCallBusy(RuntimeError):
    pass


class SourceCallTimeout(TimeoutError):
    pass


class SourceCallGate:
    def __init__(self, timeout=2.0):
        if not 0 < timeout <= 2:
            raise ValueError('SOURCE_CALL_BUDGET_INVALID')
        self.timeout = timeout
        self._lock = Lock()
        self._thread = None
        self._closed = False
        self._started = None
        self._timed_out = False

    def call(self, callback):
        done, result = Event(), {}
        with self._lock:
            if self._closed or self._thread is not None and self._thread.is_alive():
                raise SourceCallBusy('SOURCE_CALL_STILL_IN_FLIGHT_OR_CLOSED')
            self._started, self._timed_out = monotonic(), False
            def run():
                try:
                    result['value'] = callback()
                except BaseException as exc:
                    result['error'] = exc
                finally:
                    done.set()
            self._thread = Thread(target=run, name='kquant-shared-source-call', daemon=True)
            self._thread.start()
        if not done.wait(self.timeout):
            with self._lock:
                self._timed_out = True
            raise SourceCallTimeout('SOURCE_CALL_WAIT_EXPIRED_NOT_CANCELLED')
        if 'error' in result:
            error = result['error']
            if not isinstance(error, Exception):
                raise RuntimeError('SOURCE_CALL_WORKER_ABORTED')
            raise error
        return result['value']

    def snapshot(self):
        with self._lock:
            alive = self._thread is not None and self._thread.is_alive()
            return {'in_flight': alive, 'wait_expired': self._timed_out,
                    'elapsed_seconds': monotonic() - self._started if self._started is not None else None,
                    'state': 'CLOSED' if self._closed else 'WAIT_EXPIRED_IN_FLIGHT' if alive and self._timed_out
                             else 'IN_FLIGHT' if alive else 'IDLE',
                    'transport_cancellation_proven': False}

    def close(self):
        with self._lock:
            self._closed = True
            thread = self._thread
        if thread is not None:
            thread.join(timeout=self.timeout)
        return self.snapshot()
