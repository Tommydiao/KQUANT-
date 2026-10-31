"""Bounded, disposable projection of immutable evaluations for status readers."""
from __future__ import annotations

import json
from pathlib import Path
from time import monotonic

from .bounded_sqlite import read_connection
from . import options_one_minute as common
from .options_opening_trend_coverage import reconcile


def bind_provider_reference_replay(strict_result, replay):
    """Separate, optional read binding; never enters reconcile/strict statistics."""
    from copy import deepcopy
    from .options_provider_reference_research import project_replay
    return {"strict_result": deepcopy(strict_result),
            "provider_reference_research": project_replay(strict_result, replay)}


def read_delta(path, *, session, policy_hash, after=0, limit=128):
    if after < 0 or not 1 <= limit <= 128:
        raise ValueError("INVALID_PROJECTION_BATCH")
    path = Path(path).resolve()
    stat = path.stat()
    identity = [str(path), stat.st_dev, stat.st_ino, session, policy_hash]
    with read_connection(path, seconds=.4) as db:
        deadline = monotonic() + .4
        # Count and batch must describe one read transaction despite concurrent appends.
        db.execute("BEGIN")
        identity.append(db.execute("PRAGMA schema_version").fetchone()[0])
        count, last = db.execute("""SELECT COUNT(*),COALESCE(MAX(rowid),0) FROM evaluations
            WHERE policy_hash=? AND session=?""", (policy_hash, session)).fetchone()
        if count > 12000:
            raise ValueError("CHECKPOINT_RECORD_BOUND_EXCEEDED")
        ids = db.execute("""SELECT rowid FROM evaluations WHERE policy_hash=? AND session=?
            AND rowid>? ORDER BY rowid LIMIT ?""", (policy_hash, session, after, limit)).fetchall()
        rows = []
        if monotonic() >= deadline:
            raise TimeoutError("PROJECTION_READ_BUDGET_EXCEEDED")
        keys = [row[0] for row in ids]
        records = db.execute(f"""SELECT rowid,evaluation_id,policy_hash,session,symbol,right_name,evaluated_at,state,
                json_extract(payload_json,'$.scope_hash','$.calculation_bar_end','$.reasons',
                    '$.calculation_input_received_at','$.computed_at'),json_extract(payload_json,'$.factor_evidence')
                FROM evaluations WHERE rowid IN ({','.join('?' for _ in keys)}) ORDER BY rowid""", keys).fetchall() if keys else []
        for rowid, *value in records:
            record = dict(zip(("evaluation_id", "policy_hash", "session", "symbol", "right", "evaluated_at", "state"), value[:7]))
            record.update(zip(("scope_hash", "calculation_bar_end", "reasons", "input_received_at", "computed_at"), json.loads(value[7])))
            record["reasons"] = record["reasons"] or []
            factor=json.loads(value[8]) if value[8] else None
            record['factor_evidence_sha256']=common.digest(factor) if factor is not None else None
            if isinstance(factor,dict):
                factor=dict(factor)
                for name,fields in (
                        ('reference',('symbol','session','previous_close','source_hash')),
                        ('auxiliary',('role','state','vwap','warnings'))):
                    if isinstance(factor.get(name),dict):
                        factor[name]={key:factor[name][key] for key in fields if key in factor[name]}
                        factor[name]['evidence_deferred']=True
            record['factor_evidence']=factor
            record['factor_evidence_format']='PROJECTED_FIELDS_WITH_ORIGINAL_HASH_V1'
            rows.append([rowid, record])
    current = path.stat()
    if (current.st_dev, current.st_ino) != (stat.st_dev, stat.st_ino):
        raise ValueError("PROJECTION_SOURCE_CHANGED")
    return {"identity": identity, "after": after, "source_count": count, "source_last": last, "rows": rows}


class ProjectionCache:
    """Process-local cache only. Restart/replacement rebuilds it; never a ledger."""

    def __init__(self):
        self.identity = None
        self.after = 0
        self.rows = {}

    def reset(self):
        self.identity, self.after, self.rows = None, 0, {}

    def apply(self, delta, *, registered, now, policy, scope_hash, observer_started_at=None):
        if self.identity != delta["identity"]:
            self.reset()
            self.identity = delta["identity"]
        if (delta["after"] != self.after or delta["source_count"] < len(self.rows)
                or delta["source_last"] < self.after):
            self.reset()
            return self.pending(delta, "PROJECTION_REBUILD_REQUIRED")
        for rowid, record in delta["rows"]:
            if rowid <= self.after or rowid > delta["source_last"]:
                self.reset()
                return self.pending(delta, "PROJECTION_SEQUENCE_INVALID")
            self.rows[rowid] = record
            self.after = rowid
        if len(self.rows) != delta["source_count"] or self.after != delta["source_last"]:
            if not delta["rows"]:
                self.reset()
            return self.pending(delta, "PROJECTION_CATCHING_UP")
        result = reconcile(registered, list(self.rows.values()), now=now, policy=policy, scope_hash=scope_hash,
            observer_started_at=observer_started_at)
        result["projection"] = {"state": "CURRENT", "records": len(self.rows), "source_last": self.after}
        return result

    def pending(self, delta, reason):
        return {"state": "UNAVAILABLE", "reason": reason, "checkpoints": [], "read_only": True,
                "qualified_signal_acceptance": False, "projection": {
                    "state": reason, "records": len(self.rows), "source_count": delta["source_count"]}}
