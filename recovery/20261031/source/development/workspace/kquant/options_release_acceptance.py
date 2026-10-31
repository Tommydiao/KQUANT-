"""Exact release acceptance is independent of strategy and source fact approval."""
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

from . import options_one_minute as common

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=32)
def _checked_frontend(files):
    return all(hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected
               for name, _, _, expected in files)


def verify(record, *, root=ROOT, environment=None):
    environment = os.environ if environment is None else environment
    try:
        if (not isinstance(record, dict) or record.get("status") != "APPROVED"
                or record.get("approved_by") != "OWNER" or record.get("test_only") and root == ROOT):
            return {"status": "BLOCKED", "reason": "EXACT_RELEASE_ACCEPTANCE_REQUIRED"}
        path = Path(environment["KQUANT_RUNTIME_MANIFEST"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("RUNTIME_OUTSIDE_ROOT")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        runtime = json.loads(raw)
        if (digest != environment.get("KQUANT_BACKEND_MANIFEST_SHA256")
                or digest != record.get("runtime_manifest_sha256")
                or path.parent.name != environment.get("KQUANT_BACKEND_RELEASE_ID")):
            raise ValueError("RUNTIME_ACCEPTANCE_CHANGED")
        front = runtime["frontend_files"]
        if common.digest(front) != record.get("frontend_files_hash"):
            raise ValueError("FRONTEND_ACCEPTANCE_CHANGED")
        served = environment.get("KQUANT_GATEWAY_WEB_DIST")
        expected_front = runtime.get("frontend")
        if root == ROOT or expected_front is not None:
            if not served or not expected_front or Path(served).resolve() != (root / expected_front).resolve():
                raise ValueError("ACTUAL_SERVED_FRONTEND_NOT_ACCEPTED")
        fingerprint = []
        for name, expected in front.items():
            file = (root / name).resolve()
            if not file.is_relative_to(root.resolve()):
                raise ValueError("FRONTEND_ARTIFACT_CHANGED")
            stat = file.stat()
            fingerprint.append((str(file), stat.st_mtime_ns, stat.st_size, expected))
        if not _checked_frontend(tuple(fingerprint)):
            raise ValueError("FRONTEND_ARTIFACT_CHANGED")
        bundle_path = (root / record["bundle_path"]).resolve()
        if not bundle_path.is_relative_to(root.resolve()):
            raise ValueError("BUNDLE_OUTSIDE_ROOT")
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        if (bundle.get("bundle_sha256") != record.get("bundle_sha256")
                or common.digest({k: v for k, v in bundle.items() if k != "bundle_sha256"}) != record["bundle_sha256"]
                or bundle.get("runtime_manifest_sha256") != digest
                or bundle.get("source_contract_policy_hash") != record.get("source_contract_policy_hash")
                or runtime.get("source_contract_policy_hash") != record.get("source_contract_policy_hash")):
            raise ValueError("BUNDLE_ACCEPTANCE_CHANGED")
        return {"status": "PASS", "runtime_manifest_sha256": digest,
                "bundle_sha256": record["bundle_sha256"], "frontend_files_hash": record["frontend_files_hash"]}
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return {"status": "BLOCKED", "reason": str(exc) or type(exc).__name__}
