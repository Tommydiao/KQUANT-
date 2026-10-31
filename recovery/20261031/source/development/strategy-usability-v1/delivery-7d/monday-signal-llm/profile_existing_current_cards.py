"""Read-only profile of actual current_cards on a finished TEST_ONLY store."""
import argparse
from contextlib import contextmanager
import cProfile
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import pstats
import sqlite3
import sys
from time import monotonic


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = ROOT / "source/development/workspace"
EVIDENCE = ROOT / "source/evidence/new-machine-20261008"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--followup", action="store_true")
    args = parser.parse_args()
    if not args.run.replace("-", "").isalnum():
        raise ValueError("INVALID_RUN_NAME")
    run = (EVIDENCE / args.run).resolve(strict=True)
    if not run.is_relative_to(EVIDENCE.resolve()) or not (run / "TEST_ONLY.json").is_file():
        raise ValueError("EXPLICIT_TEST_ONLY_ROOT_REQUIRED")
    report = json.loads((run / "topology_report.json").read_text(encoding="utf-8"))
    if report.get("child_processes_alive"):
        raise ValueError("FINISHED_AND_REAPED_RUN_REQUIRED")
    binding = run / "TEST_ONLY-role-map.json"
    roles = json.loads(binding.read_text(encoding="utf-8"))["stores"]
    for value in roles.values():
        if not Path(value).resolve(strict=True).is_relative_to(run):
            raise ValueError("TEST_ROLE_OUTSIDE_ISOLATION")
    os.environ.update(KQUANT_RUNTIME_DATA_ROOT=str(run),
        KQUANT_RUNTIME_PATH_BINDING=str(binding),
        KQUANT_RUNTIME_PATH_BINDING_SHA256=sha256(binding.read_bytes()).hexdigest())
    sys.path.insert(0, str(BASE))
    from kquant import bounded_sqlite, options_opening_trend_store as store
    if args.followup:
        import importlib.util
        selected = HERE / "current-card-followup/patches/kquant/options_opening_trend_store.py"
        spec = importlib.util.spec_from_file_location("kquant._current_cards_profile_followup", selected)
        store = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = store
        spec.loader.exec_module(store)
    path = Path(roles["opening_research"])
    source = Path(store.__file__).resolve()
    if not (source.is_relative_to(BASE) or args.followup and source == selected.resolve()):
        raise ValueError("UNEXPECTED_RUNTIME_MODULE")
    original_read = bounded_sqlite.read_connection
    statements = []

    @contextmanager
    def traced_read(database, *, seconds=1.0):
        if not Path(database).resolve().is_relative_to(run):
            raise ValueError("READ_OUTSIDE_TEST_ONLY_ROOT")
        with original_read(database, seconds=seconds) as db:
            db.set_trace_callback(lambda sql: statements.append(sql) if len(statements) < 80 else None)
            yield db

    with original_read(path, seconds=.3) as db:
        sample = db.execute("""SELECT session,evaluated_at,
            json_extract(payload_json,'$.scope_hash'),
            json_extract(payload_json,'$.policy_snapshot')
            FROM evaluations
            WHERE json_extract(payload_json,'$.policy_id')='STRAT-OPENING-MOMENTUM-5M-V1'
            ORDER BY rowid DESC LIMIT 1""").fetchone()
        indexes = db.execute("SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name IN ('evaluations','revisions')").fetchall()
    if not sample:
        raise ValueError("NO_SAVED_TEST_INPUT")
    session, at, scope, policy_json = sample
    policy = json.loads(policy_json)
    bounded_sqlite.read_connection = traced_read
    profiler = cProfile.Profile()
    measurements = []
    try:
        for number in range(3):
            started = monotonic()
            profiler.enable()
            try:
                result = store.current_cards(path=path, session=session, scope_hash=scope,
                    now=datetime.fromisoformat(at), policy=policy)
                measurements.append(dict(sample=number, elapsed_seconds=monotonic()-started,
                    outcome="SUCCESS", evaluations_total=result["evaluations_total"],
                    returned_cards=len(result["evaluations"]), projection=result["current_projection"]))
            except Exception as exc:
                measurements.append(dict(sample=number, elapsed_seconds=monotonic()-started,
                    outcome="FAILED", error_type=type(exc).__name__,
                    sqlite_errorname=getattr(exc, "sqlite_errorname", None)))
            finally:
                profiler.disable()
    finally:
        bounded_sqlite.read_connection = original_read
    plans = []
    for sql in dict.fromkeys(statements):
        if not sql.lstrip().upper().startswith("SELECT"):
            continue
        try:
            with original_read(path, seconds=.3) as db:
                plan = db.execute("EXPLAIN QUERY PLAN " + sql).fetchall()
            plans.append(dict(sql_sha256=sha256(sql.encode()).hexdigest(), sql=sql, plan=plan))
        except (sqlite3.Error, TimeoutError) as exc:
            plans.append(dict(sql_sha256=sha256(sql.encode()).hexdigest(), error_type=type(exc).__name__))
    stats = pstats.Stats(profiler)
    functions = []
    for (filename, line, name), (primitive, calls, own, cumulative, _) in sorted(
            stats.stats.items(), key=lambda item: item[1][3], reverse=True)[:25]:
        functions.append(dict(file=filename, line=line, function=name, calls=calls,
            primitive_calls=primitive, own_seconds=own, cumulative_seconds=cumulative))
    evidence = dict(schema="KQUANT_CURRENT_CARDS_SAVED_INPUT_PROFILE_V1", test_only=True,
        observed_at=datetime.now(UTC).isoformat(), finished_run=str(run),
        source_file=str(source), source_sha256=sha256(source.read_bytes()).hexdigest(),
        query_budget_seconds=.3, sql_timeout_unchanged=True, role_paths=roles,
        session=session, replay_as_of=at, production_writes=0, database_copies=0,
        sdk_connections=0, model_calls=0, indexes=indexes, measurements=measurements,
        query_plans=plans, functions=functions,
        limits="Saved synthetic store, read-only actual function, instrumentation overhead included. Not a matching hour, production lock attribution, real market latency or a fixed failure.")
    output = args.output.resolve()
    if not output.is_relative_to((HERE / "evidence").resolve()):
        raise ValueError("OUTPUT_OUTSIDE_LOCAL_EVIDENCE")
    with output.open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, indent=2)
    print(json.dumps(dict(path=str(output), measurements=measurements,
        plans=[item.get("plan") for item in plans], functions=functions[:12]), indent=2))


if __name__ == "__main__":
    main()
