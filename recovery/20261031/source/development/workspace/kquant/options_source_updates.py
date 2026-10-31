"""Atomic source-owned updates, preserving method and owner-owned selections."""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import time

from .options_one_minute import digest


@contextmanager
def config_lock(path, timeout=5):
    lock = Path(str(path) + ".source-update.lock")
    deadline = time.monotonic() + timeout
    # Open without truncation. Exclusive creation can report access denied while
    # another Windows handle owns the first byte, even when the file exists.
    handle = lock.open("a+b", buffering=0)
    while True:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.monotonic() >= deadline:
                handle.close()
                raise TimeoutError("SOURCE_CONFIG_UPDATE_BUSY")
            time.sleep(.02)
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
        yield
    finally:
        handle.seek(0)
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def _identity(fact):
    if not isinstance(fact, dict):
        return digest(fact)
    return digest({k: v for k, v in fact.items() if k not in
                   {"reviewed_at", "valid_until", "source_path", "reviewer"}})


def merge_facts(path, updates):
    """Updates are explicit key paths; method/acceptance fields are never owned here."""
    forbidden = {"price_binding_method", "canonical_resolution_method", "acceptance", "approved_by"}
    if any(not keys or any(k in forbidden for k in keys) for keys, _ in updates):
        raise ValueError("SOURCE_UPDATE_CANNOT_CHANGE_METHOD_OR_ACCEPTANCE")
    path = Path(path)
    with config_lock(path):
        original = path.read_bytes() if path.exists() else b"{}"
        value = json.loads(original)
        changed = False
        for keys, candidate in updates:
            parent = value
            for key in keys[:-1]:
                parent = parent.setdefault(key, {})
            current = parent.get(keys[-1])
            if current is not None and _identity(current) != _identity(candidate):
                review = dict(state="REVIEW_REQUIRED", key_path=list(keys),
                              previous_hash=digest(current), candidate_hash=digest(candidate),
                              candidate=candidate)
                review_id = digest(review)
                notices = value.setdefault("source_update_reviews", {})
                if review_id not in notices:
                    notices[review_id] = review
                    changed = True
                continue
            if current is None:
                parent[keys[-1]] = candidate
                changed = True
        if not changed:
            return {"changed": False, "config_sha256": sha256(original).hexdigest()}
        raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(raw)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {"changed": True, "config_sha256": sha256(raw).hexdigest()}
