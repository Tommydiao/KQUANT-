"""Explicit epoch paths installed by the accepted recovery launcher, not a DB creator."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing

from .recovery_preflight import ROLES, checked_path


def resolve_stores(root: Path) -> dict[str, Path]:
    runtime_root = os.environ.get("KQUANT_RUNTIME_DATA_ROOT", "")
    if runtime_root:
        if not os.environ.get("KQUANT_RUNTIME_PATH_BINDING") or not os.environ.get("KQUANT_RUNTIME_PATH_BINDING_SHA256"):
            raise ValueError("EXACT_RUNTIME_PATH_BINDING_REQUIRED")
        # The launch gate installs this root together with the hash-bound five-store map.
        root = checked_path(runtime_root, [Path(runtime_root)])
    defaults = {"minute": root / "work/options_one_minute/one_minute.sqlite3",
                "opening_research": root / "work/options_one_minute/opening_trend_research.sqlite3",
                "main": root / "work/kquant_us.sqlite3",
                "full_watch": root / "work/options_full_watch/full_watch.sqlite3",
                "signal_copilot": root / "work/options_signal_copilot/signal_copilot.sqlite3"}
    value = os.environ.get("KQUANT_RUNTIME_PATH_BINDING", "")
    expected_hash = os.environ.get("KQUANT_RUNTIME_PATH_BINDING_SHA256", "")
    if not value and not expected_hash:
        return defaults
    if not value or len(expected_hash) != 64:
        raise ValueError("EXACT_RUNTIME_PATH_BINDING_REQUIRED")
    path = checked_path(value, [root])
    if path.stat().st_size > 64 * 1024:
        raise ValueError("RUNTIME_PATH_BINDING_EXCEEDS_LIMIT")
    with path.open("rb") as stream:
        content = stream.read(64 * 1024 + 1)
    if len(content) > 64 * 1024 or sha256(content).hexdigest() != expected_hash:
        raise ValueError("RUNTIME_PATH_BINDING_HASH_CHANGED")
    binding = json.loads(content.decode("utf-8-sig"))
    if (binding.get("schema") != "KQUANT_NEW_EPOCH_RUNTIME_PATHS_V1"
            or binding.get("runtime_root") != str(root)
            or not binding.get("epoch_id") or len(binding.get("data_scope_acceptance_sha256", "")) != 64):
        raise ValueError("RUNTIME_PATH_BINDING_MISMATCH")
    session = date.fromisoformat(binding["session"])
    minute = checked_path(binding["minute_path"], [root])
    opening = checked_path(binding["opening_research_path"], [root])
    expected = root / "work" / ("options_one_minute-epoch-" + session.strftime("%Y%m%d")) / "one_minute.sqlite3"
    if minute != expected or opening.parent == minute.parent:
        raise ValueError("NEW_EPOCH_AND_PRESERVED_RESEARCH_PATHS_REQUIRED")
    bound = {"minute": minute, "opening_research": opening}
    if "stores" in binding:
        stores = binding["stores"]
        if (not isinstance(stores, dict) or set(stores) != ROLES
                or stores.get("minute") != str(minute) or stores.get("opening_research") != str(opening)):
            raise ValueError("EXACT_ALL_STORE_BINDING_REQUIRED")
        bound = {role: checked_path(stores[role], [root]) for role in ROLES}
        if len(set(bound.values())) != len(ROLES):
            raise ValueError("DISTINCT_BUSINESS_STORE_PATHS_REQUIRED")
    for database in bound.values():
        if not database.is_file():
            raise ValueError("MISSING_DATABASE_NO_AUTOCREATE")
        for suffix in ("-wal", "-shm", "-journal"):
            checked_path(str(database) + suffix, [root])
    return {**defaults, **bound}


def connect_store(path: Path, **kwargs) -> sqlite3.Connection:
    if os.environ.get("KQUANT_RUNTIME_PATH_BINDING"):
        path = checked_path(str(path), [path.parent])
        return sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, **kwargs)
    return sqlite3.connect(path, **kwargs)


def queue_store(path=None) -> Path:
    """Resolve at construction time; validate an existing bound journal without DDL."""
    root = Path(__file__).resolve().parents[1]
    result = Path(path) if path is not None else resolve_stores(root)["full_watch"]
    if os.environ.get("KQUANT_RUNTIME_PATH_BINDING"):
        with closing(connect_store(result, timeout=.05)) as connection:
            connection.execute("SELECT job_id,slot,state,deadline_at,lease_owner,payload_json FROM two_hour_jobs LIMIT 0")
    return result
