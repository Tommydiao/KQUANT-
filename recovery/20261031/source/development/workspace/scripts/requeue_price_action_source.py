"""Release failed source retries after an explicitly recorded condition change."""
import argparse
from datetime import UTC, date, datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).absolute().parents[1]))
from kquant.options_price_action_source import requeue_after_condition_change


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--evidence-sha256', required=True)
    parser.add_argument('--target-session', type=date.fromisoformat, required=True)
    parser.add_argument('--symbol', action='append', required=True)
    args = parser.parse_args()
    result = requeue_after_condition_change(
        args.index, symbols=args.symbol, target=args.target_session,
        evidence_path=args.evidence, evidence_sha256=args.evidence_sha256,
        now=datetime.now(UTC))
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
