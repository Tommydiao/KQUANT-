"""Owned, bounded development math process; no ledger or execution authority."""
import multiprocessing as mp
import time
import math
import json
import threading
from copy import deepcopy

MAX_RESULT_BYTES = 65536


def _run(send, function, args):
    try:
        result = function(*args)
        payload = json.dumps({'status': 'COMPLETED', 'value': result}, allow_nan=False).encode()
        if len(payload) > MAX_RESULT_BYTES:
            payload = b'{"status":"ABSTAIN","reason":"RESULT_TOO_LARGE"}'
        send.send_bytes(payload)
    except BaseException:
        # Do not serialize exception text that could contain input secrets.
        send.send_bytes(b'{"status":"FAILED","reason":"MATH_WORKER_ERROR"}')
    finally:
        send.close()


class DevelopmentMathProcess:
    def __init__(self, function, args=(), *, timeout_seconds):
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError('Finite positive deadline required')
        context = mp.get_context('spawn')
        self.receive, send = context.Pipe(duplex=False)
        self.process = context.Process(target=_run, args=(send, function, args), daemon=True)
        self.deadline = time.monotonic() + timeout_seconds
        self.result = None
        self.received_result = None
        self.reader = threading.Thread(target=self._receive, daemon=True)
        try:
            self.process.start()
            send.close()
            self.reader.start()
        except BaseException:
            send.close()
            # Startup is outside the protection callback and owns only this child.
            if self.process.pid is not None:
                if self.process.is_alive():
                    self.process.terminate()
                self.process.join(timeout=2)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join(timeout=2)
            self.receive.close()
            raise

    def _receive(self):
        try:
            self.received_result = json.loads(self.receive.recv_bytes(MAX_RESULT_BYTES))
        except (EOFError, OSError, ValueError):
            self.received_result = {'status': 'ABSTAIN', 'reason': 'WORKER_EXIT_WITHOUT_VALID_RESULT'}

    def poll(self):
        if self.result is not None:
            return deepcopy(self.result)
        if time.monotonic() >= self.deadline:
            self.result = {'status': 'ABSTAIN', 'reason': 'DEADLINE_EXPIRED'}
        elif self.received_result is not None:
            self.result = dict(self.received_result)
        else:
            return {'status': 'PENDING', 'admission': 'ABSTAIN', 'execution_allowed': False}
        self.result.update(admission='ABSTAIN', execution_allowed=False)
        return deepcopy(self.result)

    def close(self):
        # Cleanup belongs off the protection callback, and only owns this child.
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=2)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=2)
        self.receive.close()
        self.reader.join(timeout=2)
