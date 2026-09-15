"""Bounded no-refit review; all new evidence stays in its dedicated directory."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kquant_crypto.hybrid_posterior_review import (  # noqa: E402
    OUTPUT, markdown_report, review_saved, sha, write_new,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.output.resolve() != OUTPUT.resolve():
        parser.error("only the owned posterior_review_20260906 output is authorized")
    interpreter = ROOT / "work/hybrid_dev_fit_fast_env/Scripts/python.exe"
    if Path(sys.executable).resolve() != interpreter.resolve():
        parser.error("use the existing isolated hybrid_dev_fit_fast_env interpreter")
    args.output.mkdir(parents=True, exist_ok=False)
    test_command = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests",
                    "-p", "test_hybrid_posterior_review.py", "-v"]
    write_new(args.output / "commands.json", {
        "review": [sys.executable, "-B", *sys.argv], "review_cwd": str(Path.cwd()),
        "tests": test_command, "tests_cwd": str(ROOT), "test_timeout_seconds": 120,
        "started_at_raw_host_utc": datetime.now(timezone.utc).isoformat(),
        "environment_modified": False, "packages_installed": False, "refit": False})
    started = time.perf_counter()
    exit_code = 1
    try:
        with (args.output / "review.log").open("x", encoding="utf-8") as log:
            with redirect_stdout(log), redirect_stderr(log):
                print("Start frozen posterior review. No fit/model/sampler imports.", flush=True)
                result = review_saved()
                write_new(args.output / "review.json", result)
                with (args.output / "report.md").open("x", encoding="utf-8") as report:
                    report.write(markdown_report(result))
                print("Review completed; frozen artifact hashes unchanged; G2 remains NOT PASSED.", flush=True)
        tests = subprocess.run(test_command, cwd=ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120)
        with (args.output / "tests.log").open("x", encoding="utf-8") as log:
            log.write(tests.stdout + tests.stderr)
        write_new(args.output / "tests_result.json", {"exit_code": tests.returncode,
                   "command": test_command, "elapsed_seconds_review_and_tests": time.perf_counter() - started})
        if tests.returncode:
            raise RuntimeError("focused tests failed; preserve evidence and do not mark complete")
        exit_code = 0
    except Exception:
        with (args.output / "failure.log").open("x", encoding="utf-8") as log:
            log.write(traceback.format_exc())
        raise
    finally:
        sources = [Path(__file__), ROOT / "kquant_crypto/hybrid_posterior_review.py",
                   ROOT / "tests/test_hybrid_posterior_review.py",
                   ROOT / "docs/HYBRID_TO_LIVE_MASTER_PLAN_V1_2.md",
                   ROOT / "plan/hybrid_to_live_tasks.v1_2.json"]
        write_new(args.output / "manifest.json", {
            "exit_code": exit_code, "elapsed_seconds": time.perf_counter() - started,
            "source_hashes": {str(p.relative_to(ROOT)): sha(p) for p in sources},
            "output_hashes": {p.name: sha(p) for p in args.output.iterdir() if p.is_file()},
            "python": sys.version, "executable": sys.executable, "executable_sha256": sha(sys.executable),
            "versions": {name: metadata.version(name) for name in ("arviz", "numpy", "scipy", "xarray", "h5netcdf")},
            "frozen_requirements_sha256": sha(ROOT / "outputs/hybrid_regime_v1/dev_fit_20260905_03/requirements.lock.txt"),
            "no_environment_changes": True, "no_refit": True})
    print(f"Review and focused tests complete: {args.output}; DEV_ONLY / ABSTAIN; G2 NOT PASSED")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
