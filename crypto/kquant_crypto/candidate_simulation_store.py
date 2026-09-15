"""Independent candidate ledger. No production store or execution dependencies.

Snapshots (including checkpoints) replace state; trades/events are append-only.
Reusing a trade/event ID with different content is an error. Equity timestamps
are upserted so a final liquidation can replace the same-time pre-close mark.
Use process_lock for a single writer across processes; expired leases must be
renewed before saving. Stop requests remain writable by a separate controller.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
import uuid


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


class CandidateStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._tokens = {}
        with self._connect() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables - {"candidate_runs", "candidate_records", "candidate_locks"}:
                raise ValueError("CandidateStore requires a dedicated candidate database")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS candidate_runs (
                    run_id TEXT PRIMARY KEY, metadata TEXT NOT NULL,
                    state TEXT NOT NULL, status TEXT NOT NULL,
                    stop_requested INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS candidate_records (
                    run_id TEXT NOT NULL REFERENCES candidate_runs(run_id),
                    kind TEXT NOT NULL, record_id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(run_id, kind, record_id));
                CREATE TABLE IF NOT EXISTS candidate_locks (
                    run_id TEXT PRIMARY KEY REFERENCES candidate_runs(run_id),
                    owner TEXT NOT NULL, expires_at REAL NOT NULL);
            """)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _require(db, run_id):
        row = db.execute("SELECT * FROM candidate_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return row

    def create_run(self, run_id, metadata):
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a nonempty string")
        metadata = dict(metadata)
        for key, value in {"evidence_scope": "candidate_simulation", "research_only": True,
                           "order_submission": False}.items():
            if key in metadata and metadata[key] != value:
                raise ValueError(f"Invalid candidate invariant: {key}")
            metadata[key] = value
        for name, source in (("config_hash", "config"), ("policy_hash", "policy"),
                             ("data_manifest_hash", "data_manifest")):
            if source in metadata:
                digest = _hash(metadata[source])
                # Policy hashes can intentionally exclude operational config fields.
                metadata[f"{source}_payload_hash"] = digest
                metadata.setdefault(name, digest)
            else:
                metadata.setdefault(name, None)
        encoded = _json(metadata)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT metadata FROM candidate_runs WHERE run_id=?", (run_id,)).fetchone()
            if old:
                if old[0] != encoded:
                    raise ValueError("run_id already bound to different metadata")
                return
            now = time.time()
            db.execute("INSERT INTO candidate_runs VALUES (?, ?, '{}', 'created', 0, ?, ?)",
                       (run_id, encoded, now, now))

    def save(self, run_id, state, events=(), trades=(), equity=()):
        state = dict(state)
        encoded_state = _json(state)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = self._require(db, run_id)
            lock = db.execute("SELECT * FROM candidate_locks WHERE run_id=?", (run_id,)).fetchone()
            token = self._tokens.get(run_id)
            if lock and lock["expires_at"] > time.time() and lock["owner"] != token:
                raise RuntimeError("run is locked by another writer")
            if token and (not lock or lock["owner"] != token or lock["expires_at"] <= time.time()):
                raise RuntimeError("writer lease expired; reacquire before saving")
            for kind, rows, key in (("events", events, "event_id"),
                                    ("trades", trades, "trade_id"), ("equity", equity, "time")):
                for item in rows:
                    item = dict(item)
                    if item.get("run_id", run_id) != run_id:
                        raise ValueError("record belongs to another run")
                    item["run_id"] = run_id
                    if kind == "events" and not item.get(key):
                        item[key] = _hash(item)
                    if key not in item or item[key] is None or item[key] == "":
                        raise ValueError(f"{kind} requires {key}")
                    if kind == "equity":
                        stamp = float(item[key])
                        if not math.isfinite(stamp):
                            raise ValueError("equity time must be finite epoch seconds")
                        item[key] = stamp
                    record_id, payload = str(item[key]), _json(item)
                    previous = db.execute(
                        "SELECT payload FROM candidate_records WHERE run_id=? AND kind=? AND record_id=?",
                        (run_id, kind, record_id)).fetchone()
                    if previous and previous[0] != payload and kind != "equity":
                        raise ValueError(f"conflicting {kind} ID: {record_id}")
                    if kind == "equity":
                        db.execute("INSERT INTO candidate_records VALUES (?, ?, ?, ?) "
                                   "ON CONFLICT(run_id, kind, record_id) DO UPDATE SET payload=excluded.payload",
                                   (run_id, kind, record_id, payload))
                    else:
                        db.execute("INSERT OR IGNORE INTO candidate_records VALUES (?, ?, ?, ?)",
                                   (run_id, kind, record_id, payload))
            db.execute("UPDATE candidate_runs SET state=?, status=?, updated_at=? WHERE run_id=?",
                       (encoded_state, str(state.get("status", old["status"])), time.time(), run_id))

    def load(self, run_id):
        """Return the full saved state, including arbitrary checkpoint fields."""
        with self._connect() as db:
            return json.loads(self._require(db, run_id)["state"])

    def list_runs(self):
        with self._connect() as db:
            return [self._run_dict(row) for row in db.execute(
                "SELECT * FROM candidate_runs ORDER BY created_at, run_id")]

    @staticmethod
    def _run_dict(row):
        result = dict(row)
        result["metadata"] = json.loads(result["metadata"])
        result["state"] = json.loads(result["state"])
        result["stop_requested"] = bool(result["stop_requested"])
        return result

    def request_stop(self, run_id):
        with self._connect() as db:
            self._require(db, run_id)
            db.execute("UPDATE candidate_runs SET stop_requested=1, updated_at=? WHERE run_id=?",
                       (time.time(), run_id))

    def should_stop(self, run_id):
        with self._connect() as db:
            return bool(self._require(db, run_id)["stop_requested"])

    def clear_stop(self, run_id):
        """Explicit resume only: caller must own a live writer lease for this run."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require(db, run_id)
            token = self._tokens.get(run_id)
            lock = db.execute("SELECT * FROM candidate_locks WHERE run_id=?", (run_id,)).fetchone()
            if not token or not lock or lock["owner"] != token or lock["expires_at"] <= time.time():
                raise RuntimeError("clear_stop requires an owned, unexpired writer lock")
            db.execute("UPDATE candidate_runs SET stop_requested=0, updated_at=? WHERE run_id=?",
                       (time.time(), run_id))

    def report_data(self, run_id):
        with self._connect() as db:
            db.execute("BEGIN")  # Snapshot and all ledger collections share one read view.
            result = self._run_dict(self._require(db, run_id))
            for kind in ("events", "trades", "equity"):
                result[kind] = [json.loads(row[0]) for row in db.execute(
                    "SELECT payload FROM candidate_records WHERE run_id=? AND kind=? ORDER BY rowid",
                    (run_id, kind))]
            result["equity"].sort(key=lambda row: float(row["time"]))
            result["checkpoints"] = result["state"].get("checkpoints", {})
            return result

    def acquire_lock(self, run_id, *, lease_seconds=60):
        if not math.isfinite(lease_seconds) or lease_seconds <= 0:
            raise ValueError("lease_seconds must be finite and positive")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require(db, run_id)
            now = time.time()
            old = db.execute("SELECT * FROM candidate_locks WHERE run_id=?", (run_id,)).fetchone()
            token = self._tokens.get(run_id)
            if old and old["expires_at"] > now and old["owner"] != token:
                raise RuntimeError("run is locked by another writer")
            token = token or uuid.uuid4().hex
            db.execute("INSERT OR REPLACE INTO candidate_locks VALUES (?, ?, ?)",
                       (run_id, token, now + lease_seconds))
        self._tokens[run_id] = token
        return token

    def release_lock(self, run_id):
        token = self._tokens.pop(run_id, None)
        with self._connect() as db:
            db.execute("DELETE FROM candidate_locks WHERE run_id=? AND owner=?", (run_id, token))

    @contextmanager
    def process_lock(self, run_id, *, lease_seconds=60):
        """Renew long jobs with acquire_lock; never steal an unexpired lease."""
        if run_id in self._tokens:
            raise RuntimeError("process_lock is not reentrant")
        self.acquire_lock(run_id, lease_seconds=lease_seconds)
        try:
            yield self
        finally:
            self.release_lock(run_id)
