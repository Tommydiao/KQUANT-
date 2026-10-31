"""Profile the existing calculation lane using an isolated run's inputs."""
import argparse
from contextlib import closing
import cProfile
from datetime import datetime
import json
from pathlib import Path
import pstats
import sqlite3
from time import monotonic


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists() or args.out.absolute().drive.upper() != "C:":
        raise ValueError("FRESH_C_ISOLATED_PROFILE_REQUIRED")
    args.out.mkdir()
    from kquant.options_opening_trend_runtime import TrendLane
    from kquant import options_one_minute as common
    day = datetime.fromisoformat("2026-10-06").date()
    now = datetime.fromisoformat("2026-10-06T13:55:01+00:00")
    native = {}
    with closing(sqlite3.connect((args.inputs / "minute.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        for symbol, payload in db.execute("SELECT symbol,payload_json FROM one_minute_bars WHERE session='2026-10-06'"):
            native.setdefault(symbol, []).append(json.loads(payload))
    bindings = {}
    with closing(sqlite3.connect((args.inputs / "research.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        for symbol, payload in db.execute("""SELECT symbol,payload_json FROM two_hour_jobs
            WHERE slot='SESSION_PRICE_BINDING_V1' AND session='2026-10-06'"""):
            bindings[symbol] = json.loads(payload)
    reviews = json.loads((args.inputs / "TEST_ONLY_sources.json").read_text())
    class Hub:
        def publish(self, event):
            pass
    lane = TrendLane(args.inputs / "minute.sqlite3", Hub(), path=args.out / "TEST_ONLY.sqlite3",
        clock=lambda: now, source_root=args.inputs, source_reviews_path=args.inputs / "TEST_ONLY_sources.json")
    lane.warm_history(sorted(bindings), day)
    profile = cProfile.Profile()
    started = monotonic()
    count = 0
    try:
        profile.enable()
        for symbol, binding in bindings.items():
            raw = dict(binding["raw_quote"])
            raw["session_price_binding"] = binding
            rows, _, _ = lane._calculate(("opening_momentum", day.isoformat(), symbol, 5),
                (symbol, day, native.get(symbol, []), "TEST_ONLY_PROFILE", {"raw_quote": raw}),
                now, [], None, reviews)
            count += len(rows)
        profile.disable()
    finally:
        lane.close()
    with (args.out / "profile.txt").open("w", encoding="utf-8") as output:
        pstats.Stats(profile, stream=output).strip_dirs().sort_stats("cumulative").print_stats(45)
    (args.out / "summary.json").write_text(json.dumps({"test_only": True,
        "sampled_direction_rows": count, "seconds": monotonic() - started,
        "current_run_inputs": str(args.inputs), "production_writes": 0,
        "profile_not_a_performance_acceptance": True}, indent=2), encoding="utf-8")
    print(json.dumps({"sampled_direction_rows": count, "profile": str(args.out / "profile.txt")}))


if __name__ == "__main__":
    main()
