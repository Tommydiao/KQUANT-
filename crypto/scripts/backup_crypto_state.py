from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kquant_crypto.backup import create_backup  # noqa: E402
from kquant_crypto.config import load_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a secret-free KQUANT CRYPTO backup.")
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--copy-data", action="store_true")
    parser.add_argument("--hash-data", action="store_true", help="hash up to the manifest limit; can be slow for large Parquet stores")
    args = parser.parse_args()
    settings = load_settings(ROOT)
    result = create_backup(
        db_path=(args.db_path or settings.db_path).resolve(),
        data_dir=(args.data_dir or settings.data_dir).resolve(),
        output_dir=(args.output_dir or settings.root_dir / "work" / "backups").resolve(),
        copy_data=args.copy_data,
        hash_data=args.hash_data,
    )
    print(result["backup_dir"])
    print(f"database_sha256={result['database']['sha256']}")
    print(f"data_files={len(result['data_manifest'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
