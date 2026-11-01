"""One calculation's method checks, revalidated before results may escape."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json

_active = ContextVar('first_hour_method_snapshot', default=None)


class SourceSnapshotChanged(ValueError):
    pass


def _identity(value):
    if isinstance(value, bytes):
        from hashlib import sha256
        return ('source_bytes', len(value), sha256(value).hexdigest())
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def source_reader(reader):
    """Reuse verified bytes within a scope; expiry/authority checks stay live."""
    if getattr(reader, '_first_hour_scoped_reader', False):
        return reader
    def read(relative_path, digest, root):
        key = ('source-file', str(root.absolute()), str(relative_path), digest)
        return checked(key, lambda: reader(relative_path, digest, root))
    read._first_hour_scoped_reader = True
    return read


def checked(key, validate):
    entries = _active.get()
    if entries is None:
        return validate()
    if key not in entries:
        if len(entries) >= 128:
            raise SourceSnapshotChanged('METHOD_SNAPSHOT_BOUND_EXCEEDED')
        value = validate()
        entries[key] = (deepcopy(value), _identity(value), validate)
    return deepcopy(entries[key][0])


def observed_source_paths():
    """Exact files used by this bounded preparation, including their actual root."""
    from pathlib import Path
    keys = tuple(_active.get() or {})
    return tuple(resolve_path(Path(key[1]) / key[2]) for key in keys
                 if key[0] == 'source-file')


def resolve_path(path):
    """Deduplicate OS traversal only within a scope that rechecks before exit."""
    from pathlib import Path
    path = Path(path).absolute()
    return Path(checked(('resolved-path', str(path)), lambda: str(path.resolve())))


@contextmanager
def calculation_scope():
    if _active.get() is not None:
        yield
        return
    entries = {}
    token = _active.set(entries)
    try:
        yield
        # Re-read original bytes through the original validator, not file stats.
        # A changed/revoked source discards this calculation before persistence.
        for _, identity, validate in entries.values():
            if _identity(validate()) != identity:
                raise SourceSnapshotChanged('METHOD_CHANGED_DURING_CALCULATION')
    finally:
        _active.reset(token)
