"""Bounded observer status publication; not a retry of quotes or transactions."""
from pathlib import Path
import time

from .hybrid_delivery import atomic_json


def publish_status(path, value, *, write=atomic_json, sleep=time.sleep):
    for attempt in range(5):
        try:
            write(path, value)
            return
        except PermissionError:
            if attempt == 4:
                raise
            sleep(.05 * 2**attempt)


def io_failure_detail(exc, root):
    detail = {'error_type': type(exc).__name__, 'errno': exc.errno,
              'winerror': getattr(exc, 'winerror', None)}
    root = Path(root).resolve()
    for key in ('filename', 'filename2'):
        value = getattr(exc, key, None)
        if value:
            path = Path(value).resolve()
            detail[key] = str(path.relative_to(root)) if path.is_relative_to(root) else 'OUTSIDE_RUN_REDACTED'
    return detail
