"""Create small observation evidence, without copying databases or accepting a runtime."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import types

entry = Path(__file__).absolute().parents[1]
package = types.ModuleType("safe_recovery_components")
package.__path__ = [str(entry / "kquant")]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location("safe_recovery_components.recovery_activation",
                                            entry / "kquant/recovery_activation.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--test-only", action="store_true")
    parser.add_argument("--approved-local-root", type=Path, action="append", default=[])
    args = parser.parse_args()
    roots = [entry.parent if entry.name == "dev" else entry, *args.approved_local_root]
    result = {"ok": False, "can_launch": False, "owner_acceptance_written": False,
              "business_writes": 0, "database_opens": 0, "f_drive_reads": 0}
    try:
        request = module.checked_path(str(args.request), roots)
        output = module.checked_path(str(args.output), roots)
        if output.suffix.lower() != ".json":
            raise ValueError("FACT_OUTPUT_MUST_BE_JSON_NOT_A_DATABASE")
        if output.exists():
            raise ValueError("EXISTING_EVIDENCE_NOT_OVERWRITTEN")
        if request.stat().st_size > 1024 * 1024:
            raise ValueError("REQUEST_TOO_LARGE")
        result = module.produce(json.loads(request.read_text(encoding="utf-8-sig")),
                                roots=roots, allow_test_only=args.test_only)
        with output.open("x", encoding="ascii") as stream:
            json.dump(result, stream, indent=2, ensure_ascii=True)
    except (OSError, ValueError, TypeError) as exc:
        result.update({"ok": False, "code": str(exc) if isinstance(exc, ValueError) else type(exc).__name__})
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
