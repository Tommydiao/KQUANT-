"""Small, allowlisted child-stage protocol and bounded pipe capture."""
from collections import deque
import json
import math
import subprocess
import sys
from threading import Thread
from time import perf_counter


PREFIX = b"STATUS_STAGE_V1 "
STAGES = ("spawn", "import", "query", "universe", "policy", "current_cards",
          "latest_status", "checkpoint_audit", "projection_delta", "qualification_stages",
          "clock", "encode", "ipc")
STDOUT_LIMIT = 16 * 1024 * 1024
STDERR_LIMIT = 4096
EVENT_LIMIT = 32
_child_started = None
_child_events = 0


def empty_transport(timeout=2.0):
    return {"schema": "STATUS_TRANSPORT_V1", "child_pid": None, "returncode": None,
        "deadline_ms": timeout * 1000, "process_ms": 0.0, "decode_ms": None, "cleanup_ms": 0.0,
        "child_reaped": None, "ipc_complete": None, "response_bytes": 0, "response_truncated": False,
        "stderr_bytes": 0, "stderr_truncated": False, "stderr_sanitized": "", "last_phase": "spawn",
        "first_stdout_ms": None, "first_stderr_ms": None,
        "last_phase_event": None,
        "stages_ms": {name: None for name in STAGES}}


def begin_child():
    global _child_started, _child_events
    _child_started, _child_events = perf_counter(), 0
    emit_stage("import", "start")
    return _child_started


def emit_stage(stage, event, *, elapsed_ms=None):
    global _child_events
    if _child_started is None or _child_events >= EVENT_LIMIT or stage not in STAGES:
        return
    if event not in {"start", "done", "failed"}:
        return
    value = {"stage": stage, "event": event,
             "at_ms": round((perf_counter() - _child_started) * 1000, 3)}
    if elapsed_ms is not None:
        value["elapsed_ms"] = round(elapsed_ms, 3)
    _child_events += 1
    try:
        sys.stderr.buffer.write(PREFIX + json.dumps(value, separators=(",", ":")).encode("ascii") + b"\n")
        sys.stderr.buffer.flush()
    except OSError:
        pass


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and 0 <= value <= 86400000 and math.isfinite(value))


def _event(line):
    if not line.startswith(PREFIX) or len(line) > 512:
        return None
    try:
        value = json.loads(line[len(PREFIX):])
        if (not isinstance(value, dict) or set(value) not in (
                {"stage", "event", "at_ms"}, {"stage", "event", "at_ms", "elapsed_ms"})
                or value["stage"] not in STAGES
                or value["event"] not in {"start", "done", "failed"}
                or not _number(value["at_ms"])
                or ("elapsed_ms" in value and not _number(value["elapsed_ms"]))):
            return None
        return value
    except (ValueError, TypeError):
        return None


class _Pipe:
    def __init__(self, stream, *, stderr=False):
        self.stream, self.stderr = stream, stderr
        self.data = bytearray()
        self.total = 0
        self.events = deque(maxlen=EVENT_LIMIT)
        self.line = bytearray()
        self.line_overflow = False
        self.finished = False
        self.first_byte_at = None
        self.thread = Thread(target=self._drain, name="status-pipe", daemon=True)

    def _lines(self, chunk):
        for part in chunk.splitlines(keepends=True):
            if not self.line_overflow:
                self.line.extend(part)
                if len(self.line) > 512:
                    self.line.clear()
                    self.line_overflow = True
            if part.endswith(b"\n"):
                if not self.line_overflow:
                    value = _event(bytes(self.line).rstrip(b"\r\n"))
                    if value is not None:
                        self.events.append(value)
                self.line.clear()
                self.line_overflow = False

    def _drain(self):
        try:
            while True:
                chunk = self.stream.read1(4096)
                if not chunk:
                    break
                if self.first_byte_at is None:
                    self.first_byte_at = perf_counter()
                self.total += len(chunk)
                if self.stderr:
                    self._lines(chunk)
                    self.data.extend(chunk)
                    del self.data[:-STDERR_LIMIT]
                elif len(self.data) < STDOUT_LIMIT:
                    self.data.extend(chunk[:STDOUT_LIMIT - len(self.data)])
        except OSError:
            pass
        finally:
            self.stream.close()
            self.finished = True


def capture(command, *, cwd, timeout, request_id=None):
    """Drain both pipes continuously; only this disposable child can be killed."""
    started = perf_counter()
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    spawned = perf_counter()
    stdout, stderr = _Pipe(process.stdout), _Pipe(process.stderr, stderr=True)
    stdout.thread.start()
    stderr.thread.start()
    expired = False
    reaped = True
    cleanup_at = None
    try:
        process.wait(timeout=max(0, timeout - (perf_counter() - started)))
    except subprocess.TimeoutExpired:
        expired = True
        cleanup_at = perf_counter()
        process.kill()
        try:
            process.wait(timeout=max(0, cleanup_at + 1 - perf_counter()))
        except subprocess.TimeoutExpired:
            reaped = False
    if cleanup_at is None:
        cleanup_at = perf_counter()
    drain_until = cleanup_at + (1 if expired else max(0, timeout - (cleanup_at - started)))
    for pipe in (stdout, stderr):
        pipe.thread.join(timeout=max(0, drain_until - perf_counter()))
    complete = stdout.finished and stderr.finished
    if not complete:
        expired = True
    events = list(stderr.events)
    # Raw stderr never enters the transport, exception text, or logs.
    safe_stderr = "\n".join(json.dumps(event, separators=(",", ":")) for event in events)
    phases = {name: None for name in STAGES}
    phases["spawn"] = round((spawned - started) * 1000, 3)
    for event in events:
        if "elapsed_ms" in event:
            phases[event["stage"]] = round((phases[event["stage"]] or 0) + event["elapsed_ms"], 3)
    telemetry = {"schema": "STATUS_TRANSPORT_V1", "child_pid": process.pid,
        "request_id": request_id,
        "returncode": process.returncode, "deadline_ms": timeout * 1000,
        "decode_ms": None,
        "process_ms": round((perf_counter() - started) * 1000, 3),
        "cleanup_ms": round((perf_counter() - cleanup_at) * 1000, 3),
        "child_reaped": reaped, "ipc_complete": complete,
        "response_bytes": stdout.total, "response_truncated": stdout.total > STDOUT_LIMIT,
        "stderr_bytes": stderr.total, "stderr_truncated": stderr.total > STDERR_LIMIT,
        "stderr_sanitized": safe_stderr[-STDERR_LIMIT:],
        "last_phase": events[-1]["stage"] if events else "spawn",
        "last_phase_event": events[-1]["event"] if events else None,
        "stages_ms": phases}
    for name, pipe in (('stdout',stdout),('stderr',stderr)):
        telemetry['first_'+name+'_ms']=(round((pipe.first_byte_at-started)*1000,3)
                                      if pipe.first_byte_at is not None else None)
    return bytes(stdout.data), telemetry, expired
