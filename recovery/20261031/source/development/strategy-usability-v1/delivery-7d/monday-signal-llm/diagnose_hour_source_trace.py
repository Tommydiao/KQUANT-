"""Bounded source-loader and Windows trace-I/O checks; no business DB is opened."""
import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic, sleep

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
EVIDENCE = ROOT / "source/evidence/new-machine-20261008"


def clean_environment():
    return {key: value for key, value in os.environ.items()
            if not key.startswith("KQUANT_") and key != "PYTHONPATH"}


def writer(args):
    out = args.output.resolve()
    if not out.is_relative_to(EVIDENCE.resolve()) or not (out / "TEST_ONLY.json").is_file():
        raise ValueError("ISOLATED_TRACE_FIXTURE_REQUIRED")
    while monotonic() < args.start:
        sleep(.005)
    for number in range(100):
        row = dict(test_only=True, writer=args.worker, sequence=number,
                   padding="TEST_ONLY_" * 40)
        destination = out / ("shared.jsonl" if args.mode == "shared" else
                             f"unique-{args.worker}-{number}.json")
        with destination.open("a" if args.mode == "shared" else "x", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")


def exercise(out, mode):
    target = out / mode
    target.mkdir()
    (target / "TEST_ONLY.json").write_text('{"test_only":true}', encoding="utf-8")
    processes = []
    started = monotonic()
    try:
        start = monotonic() + 2
        for worker in range(12):
            command = [sys.executable, str(Path(__file__).resolve()), "--output", str(target),
                       "--worker", str(worker), "--mode", mode, "--start", str(start)]
            processes.append(subprocess.Popen(command, env=clean_environment(),
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True))
        for process in processes:
            _, error = process.communicate(timeout=20)
            if process.returncode:
                raise RuntimeError("TRACE_FIXTURE_CHILD_FAILED")
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
    paths = [target / "shared.jsonl"] if mode == "shared" else sorted(target.glob("unique-*.json"))
    keys, records, invalid = set(), 0, 0
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                keys.add((row["writer"], row["sequence"]))
                records += 1
            except (ValueError, KeyError, TypeError):
                invalid += 1
    return dict(expected=1200, unique_records=len(keys), records=records,
                missing=1200-len(keys), invalid_lines=invalid,
                duration_seconds=monotonic()-started, children_alive=[])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--projection", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", type=int)
    parser.add_argument("--mode", choices=("shared", "unique"))
    parser.add_argument("--start", type=float, default=0)
    args = parser.parse_args()
    if args.worker is not None:
        writer(args)
        return
    run = args.run.resolve(strict=True)
    if not run.is_relative_to(EVIDENCE.resolve()) or not (run / "TEST_ONLY.json").is_file():
        raise ValueError("EXACT_TEST_ONLY_RUN_REQUIRED")
    projection = args.projection.resolve(strict=True)
    if not projection.is_relative_to((HERE / "release").resolve()):
        raise ValueError("EXACT_CANDIDATE_REQUIRED")
    proof_path = run / "TEST_ONLY-status-child-modules.jsonl"
    before = sha256(proof_path.read_bytes()).hexdigest()
    binding = run / "TEST_ONLY-role-map.json"
    env = clean_environment()
    env.update(KQUANT_RUNTIME_DATA_ROOT=str(run), KQUANT_RUNTIME_PATH_BINDING=str(binding),
        KQUANT_RUNTIME_PATH_BINDING_SHA256=sha256(binding.read_bytes()).hexdigest(),
        KQUANT_TEST_LEGACY_OVERLAY=str(HERE), KQUANT_TEST_FROZEN_PROJECTION=str(projection),
        PYTHONPATH=str(HERE / "live-fact-child-tools")+os.pathsep+str(ROOT / "source/development/workspace"))
    code = """import json,sys
from importlib.machinery import PathFinder
from hashlib import sha256
from pathlib import Path
import kquant
spec=PathFinder.find_spec('kquant.options_opening_trend_store',kquant.__path__)
print(json.dumps(dict(store_preloaded='kquant.options_opening_trend_store' in sys.modules,
    guard_installed=any(type(x).__name__=='VerifiedStoreFinder' for x in sys.meta_path),
    selected_path=spec.origin,selected_sha256=sha256(Path(spec.origin).read_bytes()).hexdigest())))
"""
    completed = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                               text=True, timeout=10)
    if completed.returncode:
        raise RuntimeError("FROZEN_CHILD_SOURCE_INSPECTION_FAILED")
    loader = json.loads(completed.stdout)
    after = sha256(proof_path.read_bytes()).hexdigest()
    if before != after:
        raise ValueError("POST_RUN_SOURCE_LOG_CHANGED")
    out = EVIDENCE / ("source-trace-diagnostic-"+datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    out.mkdir()
    (out / "TEST_ONLY.json").write_text('{"test_only":true}', encoding="utf-8")
    result = dict(observed_at=datetime.now(UTC).isoformat(), test_only=True, loader=loader,
                  original_proof_unchanged=True, proof_sha256=before,
                  shared=exercise(out, "shared"), unique=exercise(out, "unique"),
                  production_writes=0, business_databases_opened=0, sdk_requests=0,
                  actual_hour_not_reclassified=True)
    destination = HERE / "evidence/source-trace-diagnostic-20261020.json"
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(dict(output=str(destination), **result)))


if __name__ == "__main__":
    main()
