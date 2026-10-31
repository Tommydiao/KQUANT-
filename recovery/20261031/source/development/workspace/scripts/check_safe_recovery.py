"""Audit a local recovery manifest. A failed audit never starts a service."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

module_path = Path(__file__).absolute().parents[1] / "kquant/recovery_preflight.py"
spec = importlib.util.spec_from_file_location("safe_recovery_preflight", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
checked_path = module.checked_path


def check_manifest(path: Path, roots: list[Path], entry_root: Path,
                   runtime_root: Path | None = None, python_executable: Path | None = None) -> dict:
    """Bind one bounded manifest read to this entry before any DB observation."""
    path = checked_path(str(path), roots)
    with path.open("rb") as stream:
        content = stream.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        raise ValueError("MANIFEST_TOO_LARGE")
    value = json.loads(content.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("MANIFEST_OBJECT_REQUIRED")
    runtime = checked_path(str(value.get("runtime_root", "")), roots)
    approved = checked_path(str(value.get("approved_runtime_root", "")), roots)
    expected_runtime = checked_path(str(runtime_root or entry_root), roots)
    code_matches = (runtime_root is None or
                    checked_path(str(value.get("code_root", "")), roots) == entry_root)
    if runtime != expected_runtime or approved != expected_runtime or not code_matches:
        return {"can_launch": False, "errors": [{"code": "MANIFEST_NOT_BOUND_TO_ACTUAL_RECOVERY_ENTRY",
                                                 "subject": "runtime_root"}],
                "database_opens": 0, "business_writes": 0, "f_drive_reads": 0}
    if python_executable is not None:
        executable = checked_path(str(python_executable), roots)
        declared = checked_path(str(value.get("python_executable", "")), roots)
        active_paths = value.get("dependencies", {}).get("active_paths", [])
        if executable != declared or str(executable) not in active_paths:
            return {"can_launch": False, "errors": [{"code": "MANIFEST_PYTHON_BINDING_MISMATCH",
                                                     "subject": "python_executable"}],
                    "database_opens": 0, "business_writes": 0, "f_drive_reads": 0}
    return module.evaluate(value, roots=roots)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--approved-local-root", type=Path, action="append", default=[])
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--python-executable", type=Path)
    args = parser.parse_args()
    entry_root = module_path.parents[1]
    workspace = entry_root.parent if entry_root.name == "dev" else entry_root
    roots = [workspace, *args.approved_local_root]
    try:
        result = check_manifest(args.manifest, roots, entry_root, args.runtime_root, args.python_executable)
    except (OSError, ValueError, TypeError) as exc:
        result = {"can_launch": False, "errors": [{"code": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                                                   "subject": "manifest"}],
                  "database_opens": 0, "business_writes": 0, "f_drive_reads": 0}
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["can_launch"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
