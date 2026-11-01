"""Phase-local read-only handles, never cached rows or cross-phase snapshots."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import sqlite3
from time import monotonic

_active = ContextVar('generation_read_handles', default=None)
_phase_checked = ContextVar('generation_read_phase_checked', default=False)
MAX_HANDLES = 2


def identity(path):
    value = path.stat()
    return value.st_dev, value.st_ino


@contextmanager
def read_scope(*, phase_checked=False):
    if _active.get() is not None:
        yield
        return
    entries = {}
    token = _active.set(entries)
    phase = _phase_checked.set(phase_checked)
    try:
        yield
        if phase_checked:
            # The caller must exit this scope before any durable result commit.
            for path, (_, expected, _) in entries.items():
                if identity(Path(path)) != expected:
                    raise ValueError('GENERATION_READ_FILE_IDENTITY_CHANGED')
    finally:
        _active.reset(token)
        _phase_checked.reset(phase)
        for connection, _, _ in entries.values():
            connection.set_progress_handler(None, 0)
            connection.close()


@contextmanager
def read_connection(path, *, seconds):
    entries = _active.get()
    if entries is None:
        from kquant.bounded_sqlite import read_connection as original
        with original(path, seconds=seconds) as connection:
            yield connection
        return
    from method_snapshot import resolve_path
    logical = Path(path).absolute()
    key = str(logical)
    if key not in entries:
        if len(entries) >= MAX_HANDLES:
            raise ValueError('GENERATION_READ_HANDLE_BOUND_EXCEEDED')
        before = identity(logical)
        connection = sqlite3.connect(resolve_path(logical).as_uri()+'?mode=ro', uri=True,
                                     timeout=min(seconds, .1))
        try:
            connection.execute('PRAGMA query_only=ON')
            if identity(logical) != before:
                raise ValueError('GENERATION_READ_FILE_IDENTITY_CHANGED')
        except BaseException:
            connection.close()
            raise
        entries[key] = [connection, before, False]
    entry = entries[key]
    connection, expected, busy = entry
    if busy or connection.in_transaction:
        raise ValueError('GENERATION_READ_REENTRANCY_OR_TRANSACTION')
    if not _phase_checked.get() and identity(logical) != expected:
        raise ValueError('GENERATION_READ_FILE_IDENTITY_CHANGED')
    # Each call retains its original budget; no long transaction spans writes.
    deadline = monotonic()+seconds
    entry[2] = True
    connection.set_progress_handler(lambda: monotonic() >= deadline, 1000)
    try:
        yield connection
        if not _phase_checked.get() and identity(logical) != expected:
            raise ValueError('GENERATION_READ_FILE_IDENTITY_CHANGED')
    except sqlite3.OperationalError as exc:
        if monotonic() >= deadline and 'interrupted' in str(exc).lower():
            raise TimeoutError('STATUS_QUERY_BUDGET_EXCEEDED') from exc
        raise
    finally:
        entry[2] = False
        connection.set_progress_handler(None, 0)
        if connection.in_transaction:
            connection.rollback()
