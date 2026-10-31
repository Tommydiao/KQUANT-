"""Bounded read-only as-of development replay. Never backfills production tasks."""
from collections import Counter
from contextlib import closing as close_connection
from datetime import UTC, datetime, date
import json
from pathlib import Path
import sqlite3
import time

from bootstrap import activate
DEV, BASE = activate()
ROOT = BASE.parents[2]
from kquant import options_one_minute as common
from kquant import options_intraday_comparison as model
from kquant import options_opening_momentum as s0
from kquant import options_minute_decisions as decisions
from kquant import options_opening_trend_store as store
from kquant.options_two_hour_data import universe
from kquant.options_research_diagnostics import path_label
from kquant.market_clock import session_bounds_utc

now = datetime.now(UTC)
session = now.astimezone(common.NY).date().isoformat()
research = ROOT / "runtime/work/options_one_minute/opening_trend_research.sqlite3"
minute = ROOT / "runtime/work/options_one_minute-epoch-20261008/one_minute.sqlite3"
scope = universe(ROOT / "runtime/work/kquant_us.sqlite3")
output = DEV / "evidence" / ("replay-" + session + "-" + now.strftime("%H%M%S"))
output.mkdir(parents=True, exist_ok=True)
manifest = dict(protocol="KQ-S0-S1-RESEARCH-20261015-V1", created_at=now.isoformat(), sessions=[session],
    source_grade="REAL_RECORDED_ASOF_DEVELOPMENT", development_sessions=[session], holdout_sessions=[],
    holdout_reason="ONE_EXPOSED_SESSION_NO_UNSEEN_HOLDOUT", scope=scope,
    evaluation_selection="EARLIEST_PERSISTED_PER_SYMBOL_CHECKPOINT", later_revisions_evaluated=False,
    session_complete=now >= session_bounds_utc(date.fromisoformat(session))[1],
    baseline_hash=s0.load_policy()["policy_hash"], challenger_hash=model.load_policy()["policy_hash"],
    primary_delay_seconds=60, sensitivity_delay_seconds=[30, 120], horizon_minutes=60,
    production_writes=0, new_sdk_calls=0, parameter_search=False, registered_before_outcomes=True)
manifest_path = output / "replay_manifest.json"
if manifest_path.exists():
    raise RuntimeError("IMMUTABLE_REPLAY_ALREADY_EXISTS")
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

def connect(path):
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=.2)
    db.execute("PRAGMA query_only=ON")
    return db

def bounded(db):
    end = time.monotonic() + 3
    db.set_progress_handler(lambda: int(time.monotonic() > end), 1000)

originals, errors, source_decisions = {}, [], {}
with close_connection(connect(research)) as db:
    bounded(db)
    observed_decisions = db.execute("""SELECT symbol,payload_json FROM two_hour_jobs WHERE session=?
        AND json_extract(payload_json,'$.kind')=? LIMIT 5001""", (session, decisions.KIND)).fetchall()
    if len(observed_decisions) > 5000:
        raise RuntimeError("DECISION_READ_BOUND_EXCEEDED")
    for symbol, raw in observed_decisions:
        source_decisions.setdefault(symbol, []).append(json.loads(raw)["decision"])
    bounded(db)
    ids = db.execute("""SELECT MIN(rowid) FROM evaluations WHERE policy_hash=? AND session=?
        GROUP BY symbol,json_extract(payload_json,'$.calculation_bar_end') LIMIT 501""",
        (s0.load_policy()["policy_hash"], session)).fetchall()
    if len(ids) > 500:
        raise RuntimeError("REPLAY_POSITION_LIMIT")
    for (identity,) in ids:
        bounded(db)
        row = json.loads(db.execute("SELECT payload_json FROM evaluations WHERE rowid=?", (identity,)).fetchone()[0])
        from kquant.options_research_availability import attach
        attach(db, [row])
        originals[row["symbol"], row.get("calculation_bar_end")] = row

rows_out, examples, first_events = [], [], set()
opening, closing = session_bounds_utc(date.fromisoformat(session))
with close_connection(connect(minute)) as db:
    for instrument in scope["items"]:
        symbol = instrument["symbol"]
        bars = []
        if instrument["identity_status"] == "verified":
            bounded(db)
            try:
                records = db.execute("""SELECT payload_json FROM one_minute_bars
                    WHERE session=? AND symbol=? ORDER BY received_at LIMIT 5001""", (session, symbol)).fetchall()
                if len(records) > 5000:
                    raise ValueError("BAR_VERSION_BOUND_EXCEEDED")
                bars = [json.loads(r[0]) for r in records]
            except (sqlite3.Error, ValueError) as exc:
                errors.append(dict(symbol=symbol, kind=type(exc).__name__))
        from datetime import timedelta
        for slot in s0.load_policy()["checkpoint_minutes"]:
            checkpoint = opening + timedelta(minutes=slot)
            original = originals.get((symbol, checkpoint.isoformat()))
            if instrument["identity_status"] != "verified" or not original:
                for right in ("CALL", "PUT"):
                    rows_out.append(dict(symbol=symbol, right=right, checkpoint=checkpoint.isoformat(),
                        state="IDENTITY_UNRESOLVED" if instrument["identity_status"] != "verified" else "NO_RECORDED_EVALUATION",
                        outcome=None))
                continue
            asof = common.timestamp(original["evaluated_at"])
            try:
                adjudications = [item for item in source_decisions.get(symbol, []) if common.timestamp(item["known_at"]) <= asof]
                replay = model.evaluate_comparison_pair(symbol=symbol, bars=bars, history={},
                    reference=original.get("reference_evidence", original.get("factor_evidence", {}).get("reference", {})),
                    opening=opening, closing=closing, now=asof, checkpoint=checkpoint,
                    scope_hash=original["scope_hash"], source_decisions=adjudications)
                for row in replay:
                    pair = row["strategy_comparison"]
                    row["research_replay"] = {"source_evaluation_id": original["evaluation_id"],
                        "source_grade": manifest["source_grade"], "source_payload_hash": common.digest(original),
                        "bars_hash": common.digest([b for b in bars if common.timestamp(b["received_at"]) <= asof]),
                        "live_s1_was_available": False}
                    variants = {}
                    for variant, event in (("S0", row), ("S1", pair["s1"])):
                        key = variant, symbol, row["right"], session
                        if event["state"] == "NUMERIC_PASS" and key not in first_events:
                            first_events.add(key)
                            ready = original.get("research_ready_at")
                            variants[variant] = {str(delay): (path_label(event, bars,
                                ready_at=ready, as_of=now, delay_seconds=delay) if ready else {
                                    "state": "READY_COMMIT_TIME_UNAVAILABLE", "y60_pct": None,
                                    "delay_seconds": delay, "computed_at_is_not_commit": True}) for delay in (60, 30, 120)}
                    pair["outcome"] = variants.get("S1", {}).get("60", {"state": "NOT_A_FIRST_TECHNICAL_EVENT", "y60_pct": None})
                    summary = dict(symbol=symbol, right=row["right"], checkpoint=checkpoint.isoformat(),
                        s0_state=row["state"], s1_state=pair["s1"]["state"], cohort=pair["cohort"],
                        reasons=pair["s1"]["reasons"], comparison=model.compact_comparison(pair),
                        outcomes=variants, provenance=row["research_replay"])
                    rows_out.append(summary)
                    if (len(examples) < 6 or (pair["s1"].get("factor_evidence", {}).get("state") == "FULL_INTRADAY_RESEARCH"
                            and not any(x["symbol"] == symbol and x["right"] == row["right"] for x in examples))):
                        if len(examples) < 30:
                            examples.append(row)
            except (sqlite3.Error, ValueError, KeyError, OSError) as exc:
                errors.append(dict(symbol=symbol, checkpoint=checkpoint.isoformat(), kind=type(exc).__name__))
                for right in ("CALL", "PUT"):
                    rows_out.append(dict(symbol=symbol, right=right, checkpoint=checkpoint.isoformat(), state="REPLAY_ERROR"))

summary = dict(manifest_sha256=common.digest(manifest), recorded_positions=len(originals),
    direction_positions=len(rows_out), expected_direction_positions=len(scope["items"]) * 5 * 2,
    cohorts=dict(Counter(r.get("cohort", r.get("state")) for r in rows_out)),
    s1_states=dict(Counter(r.get("s1_state", r.get("state")) for r in rows_out)),
    blockers=dict(Counter(reason for r in rows_out for reason in r.get("reasons", []))),
    first_events=len(first_events), errors=errors, strict_s0_mutated=False,
    conclusion="DESCRIPTIVE_DEVELOPMENT_ONLY_NO_ALPHA_OR_OPTION_PNL_CLAIM")
(output / "positions.json").write_text(json.dumps(rows_out, ensure_ascii=False), encoding="utf-8")
(output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
testdb = output / "isolated-research.sqlite3"
store.initialize(testdb)
from kquant import options_opening_momentum_journal as journal
journal.initialize(testdb)
store.persist(examples, testdb)
(output / "page_examples.json").write_text(json.dumps([store.detail(row["evaluation_id"], testdb) for row in examples], ensure_ascii=False), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False))
