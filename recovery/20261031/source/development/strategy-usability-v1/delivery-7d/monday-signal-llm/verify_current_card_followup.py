"""Compare real saved TEST_ONLY card reads; never update the test or production DB."""
import argparse
from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
from time import monotonic
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = ROOT / "source/development/workspace"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.run.replace("-", "").isalnum():
        raise ValueError("INVALID_RUN_NAME")
    evidence = ROOT / "source/evidence/new-machine-20261008"
    run = (evidence / args.run).resolve(strict=True)
    if not run.is_relative_to(evidence.resolve()) or not (run / "TEST_ONLY.json").is_file():
        raise ValueError("TEST_ONLY_ISOLATION_REQUIRED")
    topology = json.loads((run / "topology_report.json").read_text(encoding="utf-8"))
    if topology.get("child_processes_alive"):
        raise ValueError("FINISHED_ISOLATION_REQUIRED")
    binding = run / "TEST_ONLY-role-map.json"
    roles = json.loads(binding.read_text(encoding="utf-8"))["stores"]
    if not all(Path(value).resolve(strict=True).is_relative_to(run) for value in roles.values()):
        raise ValueError("ROLE_OUTSIDE_ISOLATION")
    os.environ.update(KQUANT_RUNTIME_DATA_ROOT=str(run), KQUANT_RUNTIME_PATH_BINDING=str(binding),
        KQUANT_RUNTIME_PATH_BINDING_SHA256=sha256(binding.read_bytes()).hexdigest())
    sys.path.insert(0, str(BASE))
    from kquant import bounded_sqlite, options_opening_trend_store as original
    from kquant.market_clock import session_bounds_utc
    target = HERE / "current-card-followup/patches/kquant/options_opening_trend_store.py"
    spec = importlib.util.spec_from_file_location("kquant._current_card_equivalence", target)
    followup = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = followup
    spec.loader.exec_module(followup)
    path = Path(roles["opening_research"])
    with bounded_sqlite.read_connection(path, seconds=.3) as db:
        row = db.execute("""SELECT session,json_extract(payload_json,'$.scope_hash'),
            json_extract(payload_json,'$.policy_snapshot') FROM evaluations
            WHERE json_extract(payload_json,'$.policy_id')='STRAT-OPENING-MOMENTUM-5M-V1'
            ORDER BY rowid DESC LIMIT 1""").fetchone()
    session, scope, policy_json = row
    policy = json.loads(policy_json)
    opening, _ = session_bounds_utc(datetime.fromisoformat(session).date())
    attempts = []
    budget_calls = []
    actual_read = bounded_sqlite.read_connection

    def recorded_read(database, *, seconds=1.0):
        if not Path(database).resolve().is_relative_to(run):
            raise ValueError("READ_ESCAPED_TEST_ONLY_ROLE")
        budget_calls.append(dict(database=Path(database).name, seconds=seconds))
        return actual_read(database, seconds=seconds)

    def normalized(value):
        result = deepcopy(value)
        projection = result["current_projection"]
        for key in ("sql_seconds", "json_projection_seconds", "ai_summary_seconds",
                    "sql_returned_rows", "eligible_rows", "materialization"):
            projection.pop(key, None)
        return result

    cases = [(f"checkpoint-{minute}", opening+timedelta(minutes=minute, seconds=1), scope)
             for minute in (5, 10, 15, 20, 25)]
    cases += [("before-first", opening+timedelta(minutes=4), scope),
              ("original-expiry", opening+timedelta(minutes=30, seconds=1), scope),
              ("wrong-scope", opening+timedelta(minutes=25, seconds=1), "TEST_ONLY_OTHER_SCOPE")]
    with patch.object(bounded_sqlite, "read_connection", side_effect=recorded_read):
        for name, now, requested_scope in cases:
            kwargs = dict(path=path, session=session, scope_hash=requested_scope, now=now, policy=policy)
            before = monotonic()
            first = original.current_cards(**kwargs)
            first_seconds = monotonic()-before
            before = monotonic()
            second = followup.current_cards(**kwargs)
            second_seconds = monotonic()-before
            assert normalized(first) == normalized(second), name
            assert second["candidates"] == [], name
            assert second["current_projection"]["sql_returned_rows"] <= 8, name
            attempts.append(dict(case=name, equivalent=True, old_seconds=first_seconds,
                new_seconds=second_seconds, total=second["evaluations_total"],
                displayed=len(second["evaluations"]),
                full_rows_before=first["current_projection"]["sql_returned_rows"],
                full_rows_after=second["current_projection"]["sql_returned_rows"],
                watermark=second["current_projection"]["source_watermark"]))
        from kquant import options_opening_trend_approval
        now = opening+timedelta(minutes=25, seconds=1)
        kwargs = dict(path=path, session=session, scope_hash=scope, now=now, policy=policy)
        approval = original.current_cards(**kwargs)["approvals"]
        # Explicit test permission only: never persist or treat it as OWNER acceptance.
        with patch.object(options_opening_trend_approval, "status", return_value={
                **approval, "qualified_signal_pipeline_enabled": True, "test_only": True}):
            first, second = original.current_cards(**kwargs), followup.current_cards(**kwargs)
            assert normalized(first) == normalized(second), "QUALIFIED_CHANNEL_REGRESSION"
            assert second["current_projection"]["materialization"] == "QUALIFIED_CHANNEL_UNCHANGED"
            attempts.append(dict(case="test-only-qualified-channel-equivalence", equivalent=True,
                total=second["evaluations_total"], owner_approval_created=False))
    assert all(item["seconds"] == .3 for item in budget_calls), "READ_BUDGET_CHANGED"
    result = dict(schema="KQUANT_CURRENT_CARD_MATERIALIZATION_EQUIVALENCE_V1", test_only=True,
        observed_at=datetime.now(UTC).isoformat(), finished_run=str(run),
        original_sha256=sha256(Path(original.__file__).read_bytes()).hexdigest(),
        followup_sha256=sha256(target.read_bytes()).hexdigest(), attempts=attempts,
        read_budgets_unchanged=True, production_writes=0, database_copies=0, sdk_connections=0,
        model_requests=0, actual_market_latency=False, matched_hour=False,
        limits="Saved synthetic full store including actual revisions. Permission branch uses explicit in-memory TEST_ONLY override, never an OWNER acceptance.")
    output = args.output.resolve()
    if not output.is_relative_to((HERE / "evidence").resolve()):
        raise ValueError("OUTPUT_OUTSIDE_EVIDENCE")
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(dict(path=str(output), attempts=attempts), indent=2))


if __name__ == "__main__":
    main()
