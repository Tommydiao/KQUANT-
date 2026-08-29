from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kquant_crypto.backup import restore_sqlite  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore a KQUANT CRYPTO SQLite backup.")
    parser.add_argument("--source", type=Path, required=True, help="backup sqlite file")
    parser.add_argument("--destination", type=Path, required=True, help="new or explicitly replaced database")
    parser.add_argument("--replace", action="store_true", help="allow replacing an existing destination")
    args = parser.parse_args()
    result = restore_sqlite(args.source.resolve(), args.destination.resolve(), replace=args.replace)
    print(result["path"])
    print(f"sha256={result['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
