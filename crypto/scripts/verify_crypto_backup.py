from __future__ import annotations

import argparse
import json
from pathlib import Path

from kquant_crypto.backup import verify_backup_restore


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore and verify a KQUANT CRYPTO SQLite backup.")
    parser.add_argument("--backup-dir", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    result = verify_backup_restore(args.backup_dir, args.destination)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
