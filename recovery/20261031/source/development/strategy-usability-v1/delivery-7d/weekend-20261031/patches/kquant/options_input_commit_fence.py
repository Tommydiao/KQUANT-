"""Process-local input publication fence; not a cross-process database lock."""
from contextlib import contextmanager
from threading import RLock, local


_lock = RLock()
_owner = local()


class InputCommitBusy(TimeoutError):
    pass


@contextmanager
def commit_fence():
    # All owners import this qualified module. Order: fence -> journal -> lane.
    if not _lock.acquire(timeout=.05):
        raise InputCommitBusy('INPUT_COMMIT_FENCE_BUSY')
    _owner.depth = getattr(_owner, 'depth', 0) + 1
    try:
        yield
    finally:
        _owner.depth -= 1
        _lock.release()


def require_fence():
    if not getattr(_owner, 'depth', 0):
        raise RuntimeError('INPUT_TRANSACTION_REQUIRES_OUTER_COMMIT_FENCE')
