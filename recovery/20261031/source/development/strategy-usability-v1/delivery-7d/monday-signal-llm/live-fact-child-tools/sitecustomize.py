"""Explicit TEST_ONLY child overlay, including disposable status query processes."""
from hashlib import sha256
import importlib.abc
from importlib.machinery import PathFinder
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parents[1]


class VerifiedStoreFinder(importlib.abc.MetaPathFinder):
    def __init__(self, expected, expected_hash, output, candidate):
        self.expected, self.expected_hash = expected, expected_hash
        self.output, self.candidate = output, candidate

    def find_spec(self, fullname, path=None, target=None):
        if fullname != "kquant.options_opening_trend_store":
            return None
        spec = PathFinder.find_spec(fullname, path)
        if not spec or not spec.origin:
            raise ImportError("TEST_ONLY_STORE_MODULE_MISSING")
        actual = Path(spec.origin).resolve()
        actual_hash = sha256(actual.read_bytes()).hexdigest()
        if actual != self.expected or actual_hash != self.expected_hash:
            raise ImportError("TEST_ONLY_STATUS_CHILD_SOURCE_MISMATCH")
        row = dict(test_only=True, pid=os.getpid(), candidate_id=self.candidate,
            module=fullname, actual_path=str(actual), sha256=actual_hash, matches=True,
            production_writes=0)
        with (self.output / "TEST_ONLY-status-child-modules.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row)+"\n")
        return spec


if os.environ.get("KQUANT_TEST_LEGACY_OVERLAY") == str(HERE):
    try:
        from bootstrap import activate, selected_projection
        output = Path(os.environ["KQUANT_RUNTIME_DATA_ROOT"]).resolve(strict=True)
        root = HERE.parents[4] / "source/evidence/new-machine-20261008"
        if not output.is_relative_to(root.resolve()) or not (output / "TEST_ONLY.json").is_file():
            raise ValueError("EXPLICIT_TEST_ONLY_CHILD_ROOT_REQUIRED")
        activate()
        projection = selected_projection()
        proof = next(row for row in projection["changes"] if row["target"] == "kquant/options_opening_trend_store.py")
        sys.meta_path.insert(0, VerifiedStoreFinder(Path(proof["payload"]).resolve(),
            proof["sha256"], output, projection["candidate_id"]))
    except Exception as exc:
        # Python otherwise prints a sitecustomize error and silently continues.
        raise SystemExit("TEST_ONLY_CHILD_BOOTSTRAP_FAILED:"+type(exc).__name__) from exc
