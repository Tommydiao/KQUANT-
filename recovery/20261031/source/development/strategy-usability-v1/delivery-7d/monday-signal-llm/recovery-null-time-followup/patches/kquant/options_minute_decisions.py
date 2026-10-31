"""Append-only, source-reviewed selection of one whole native minute version."""
from contextlib import closing
import json
import sqlite3

from . import options_one_minute as common
from .bounded_sqlite import read_connection
from .options_opening_trend_reference import ROOT, source_review
from .options_minute_admission import partition, POLICY_HASH
from .options_data_paths import connect_store
from .market_clock import session_bounds_utc
from datetime import date, timedelta

KIND = "CANONICAL_MINUTE_DECISION_V1"
WRITE_BOUND = 500
LOCAL_METHOD = {"version": "LOCAL_CLOSED_SNAPSHOT_V1", "period": "1m",
    "adjustment": "NoAdjust", "session": "regular", "selection": "LATEST_ELIGIBLE_POST_BOUNDARY_PULL",
    "interface": "QuoteContext.candlesticks", "clock_state": "VERIFIED_BOUND",
    "maximum_clock_uncertainty_ms": 1000, "clock_evidence_max_age_seconds": 900,
    "request_boundary": "bar_end_plus_measured_clock_uncertainty",
    "later_valid_contradiction": "REVIEW_AND_WITHDRAW", "combine_ohlc": False,
    "provider_permanently_final": False, "extend_deadline": False, "backfill_signal": False}


def _local_candidate(row, proof):
    try:
        native = row["sdk_evidence"]
        # Pushes can carry a valid clock but have no pull request timestamp.
        if (native.get("interface") != LOCAL_METHOD["interface"]
                or native.get("adjustment") != "NoAdjust"):
            return False
        clock = native["clock_evidence"]
        uncertainty = clock["uncertainty_ms"]
        requested = common.timestamp(native["request_started_at"])
        received = common.timestamp(row["received_at"])
        age = (requested - common.timestamp(clock["checked_at"])).total_seconds()
        return (proof.get("method") == LOCAL_METHOD
                and native.get("interface") == LOCAL_METHOD["interface"]
                and native.get("adjustment") == "NoAdjust"
                and clock.get("state") == "VERIFIED_BOUND" and bool(clock.get("source_hash"))
                and common.finite(uncertainty) and 0 <= uncertainty <= 1000
                and 0 <= age <= 900
                and common.timestamp(row["available_at"]) + timedelta(milliseconds=uncertainty) <= requested <= received)
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _semantic_version(row, proof):
    field = proof.get("revision_field")
    native = row.get("sdk_evidence", {}).get("fields", {}).get(field, {})
    value = native.get("value")
    return int(value) if field and str(value).isdigit() else None


def _method(proof, *, now, root):
    reviewed = source_review(proof, root=root, now=now)
    if reviewed and reviewed.get("interface") == "US_EQUITY_CANDLESTICK_1M":
        if reviewed.get("semantics") in {"FINAL_CORRECTION", "PROVIDER_CONFIRMED_BAR", "DOCUMENTED_PROVIDER_REVISION"}:
            return reviewed
    # A local snapshot-adoption method is an explicit contract, not a claim
    # that the provider has made a candle permanently final.
    try:
        if (proof.get("semantics") != "CLOSED_SNAPSHOT_ADOPTION" or proof.get("status") != "ACCEPTED"
                or proof.get("method") != LOCAL_METHOD):
            return None
        path = (root / proof["acceptance_path"]).resolve()
        if not path.is_relative_to(root.resolve()):
            return None
        raw = path.read_bytes()
        from hashlib import sha256
        original = json.loads(raw)
        if (sha256(raw).hexdigest() != proof["acceptance_sha256"]
                or original.get("approved_by") != "OWNER" or original.get("status") != "APPROVED"
                or original.get("method_hash") != common.digest(proof["method"])
                or not common.timestamp(original["approved_at"]) <= now < common.timestamp(original["valid_until"])):
            return None
        return proof
    except (AttributeError, OSError, KeyError, TypeError, ValueError):
        return None


def accepted(decision, rows, *, symbol, start, now, root=None):
    try:
        known = common.timestamp(decision["known_at"])
        if not (decision.get("state") == "RESOLVED_VALID"
                and decision.get("symbol") == symbol and decision.get("open_at") == start.isoformat()
                and known <= common.timestamp(decision["resolved_at"]) <= common.timestamp(decision["valid_from"]) <= now
                and decision.get("resolver_version") == KIND
                and decision.get("decision_hash") == common.digest(
                    {k: v for k, v in decision.items() if k != "decision_hash"})):
            return None
        proof = _method(decision.get("source_semantics"), root=root or ROOT, now=now)
        if not proof:
            return None
        opening, closing = session_bounds_utc(date.fromisoformat(decision["session"]))
        classified = partition(rows, symbol=symbol, opening=opening,
                               until=start + timedelta(minutes=1), now=known)
        by_id = classified["eligible"]
        selected = by_id.get(decision["selected_version_id"])
        if selected is None or common.timestamp(selected["received_at"]) > known:
            return None
        if set(by_id) != set(decision.get("eligible_version_ids", decision["source_version_ids"])):
            return None
        if decision.get("eligibility_policy_hash") is not None and (
                decision["eligibility_policy_hash"] != POLICY_HASH
                or set(classified["raw"]) != set(decision["observed_raw_ids"])
                or classified["rejected"] != decision["rejected_versions"]):
            return None
        values = tuple(selected[k] for k in ("open", "high", "low", "close"))
        if proof["semantics"] == "PROVIDER_CONFIRMED_BAR" and len({tuple(row[k] for k in ("open", "high", "low", "close")) for row in by_id.values()}) > 1:
            return None
        selected_sequence = _semantic_version(selected, proof)
        if proof["semantics"] == "CLOSED_SNAPSHOT_ADOPTION" and not _local_candidate(selected, proof):
            return None
        current = partition(rows, symbol=symbol, opening=opening,
                            until=start + timedelta(minutes=1), now=now)
        for row in current["eligible"].values():
            if common.timestamp(row["received_at"]) > known and tuple(row[k] for k in ("open", "high", "low", "close")) != values:
                sequence = _semantic_version(row, proof)
                if (proof["semantics"] == "DOCUMENTED_PROVIDER_REVISION" and selected_sequence is not None
                        and sequence is not None and sequence < selected_sequence):
                    continue
                return None
        return selected
    except (KeyError, TypeError, ValueError):
        return None


def resolve(path, rows, *, symbol, session, now, proof, root=ROOT):
    """Production producer, selecting a whole version under a proved method."""
    reviewed = _method(proof, now=now, root=root)
    if not reviewed:
        return []
    opening, closing = session_bounds_utc(date.fromisoformat(session))
    classified = partition(rows, symbol=symbol, opening=opening, until=closing, now=now)
    grouped = {}
    for row in rows:
        identity = common.digest(row)
        if identity in classified['raw']:
            grouped.setdefault(row['open_at'], []).append((identity, row))
    values = []
    previous = read(path, symbol=symbol, session=session, now=now)
    reviewed_identity = common.canonical(reviewed)
    previous_keys = {(d.get('selected_version_id'), frozenset(d.get('source_version_ids', [])),
                      tuple(d.get('observed_raw_ids') or []), common.canonical(d.get('source_semantics')))
                     for d in previous}
    for start, raw_pairs in grouped.items():
        eligible_pairs = [(identity, row) for identity, row in raw_pairs if identity in classified['eligible']]
        versions = [row for _, row in eligible_pairs]
        if not versions:
            continue
        selected = None
        if reviewed["semantics"] == "DOCUMENTED_PROVIDER_REVISION":
            ordered = [(_semantic_version(row, reviewed), row) for row in versions]
            if all(sequence is not None for sequence, _ in ordered):
                maximum = max(sequence for sequence, _ in ordered)
                best = [row for sequence, row in ordered if sequence == maximum]
                if len({tuple(row[k] for k in ("open", "high", "low", "close")) for row in best}) == 1:
                    selected = max(best, key=lambda r: common.timestamp(r["received_at"]))
        elif reviewed["semantics"] == "CLOSED_SNAPSHOT_ADOPTION":
            candidates = [row for row in versions if _local_candidate(row, reviewed)]
            if candidates:
                selected = max(candidates, key=lambda r: common.timestamp(r["received_at"]))
                selected_at = common.timestamp(selected["received_at"])
                selected_prices = tuple(selected[k] for k in ("open", "high", "low", "close"))
                # Re-running the producer cannot re-legitimize a superseded pull.
                # A later legal contradiction needs new post-boundary evidence.
                if any(common.timestamp(row["received_at"]) >= selected_at
                       and tuple(row[k] for k in ("open", "high", "low", "close")) != selected_prices
                       for row in versions):
                    selected = None
        elif reviewed["semantics"] == "PROVIDER_CONFIRMED_BAR":
            if len({tuple(row[k] for k in ("open", "high", "low", "close")) for row in versions}) == 1:
                selected = next((r for r in versions if r.get("sdk_evidence", {}).get("provider_confirmed") is True), None)
        if selected is None:
            continue
        selected_id = next(identity for identity, row in eligible_pairs if row is selected)
        version_ids = sorted(identity for identity, _ in eligible_pairs)
        raw_ids = sorted(identity for identity, _ in raw_pairs)
        unchanged = (selected_id, frozenset(version_ids), tuple(raw_ids), reviewed_identity)
        if unchanged in previous_keys:
            continue
        value = dict(state="RESOLVED_VALID", symbol=symbol, session=session, open_at=start,
            known_at=now.isoformat(), resolved_at=now.isoformat(), valid_from=now.isoformat(),
            selected_version_id=selected_id, source_version_ids=version_ids,
            observed_raw_ids=raw_ids, eligible_version_ids=version_ids,
            rejected_versions={identity: classified['rejected'][identity]
                for identity, _ in raw_pairs if identity in classified['rejected']},
            eligibility_policy_hash=POLICY_HASH, adoption_method_hash=common.digest(reviewed.get("method", reviewed)),
            source_semantics=reviewed, adoption_method=reviewed["semantics"], provider_permanently_final=False)
        values.append(value)
        previous_keys.add(unchanged)
    return append_many(path, values)


def append(path, decision):
    return append_many(path, [decision])[0]


def append_many(path, decisions):
    if len(decisions) > WRITE_BOUND:
        raise ValueError("CANONICAL_DECISION_WRITE_BOUND_EXCEEDED")
    if not decisions:
        return []
    values, records = [], []
    # Hash and serialize before one bounded atomic transaction, not one per minute.
    for decision in decisions:
        value = {**decision, "resolver_version": KIND}
        value["decision_hash"] = common.digest({k: v for k, v in value.items() if k != "decision_hash"})
        values.append(value)
        records.append((value["decision_hash"], value["session"], value["symbol"], value["open_at"],
            value["known_at"], value["known_at"], common.canonical({"kind": KIND, "decision": value})))
    with closing(connect_store(path, timeout=.05)) as db, db:
        db.executemany("""INSERT OR IGNORE INTO two_hour_jobs VALUES
            (?,?,?,?,?,?,'COMPLETED',NULL,NULL,0,NULL,NULL,?)""",
            records)
    return values


def read(path, *, symbol, session, now):
    with read_connection(path, seconds=.2) as db:
        rows = db.execute("""SELECT payload_json FROM two_hour_jobs WHERE session=? AND symbol=?
            AND queued_at<=? AND json_extract(payload_json,'$.kind')=? ORDER BY queued_at LIMIT 501""",
            (session, symbol, now.isoformat(), KIND)).fetchall()
    if len(rows) > 500:
        raise ValueError("CANONICAL_DECISION_READ_BOUND_EXCEEDED")
    return [json.loads(row[0])["decision"] for row in rows]
