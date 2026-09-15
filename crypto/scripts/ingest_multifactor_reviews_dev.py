"""Persist verified sidecar reviews in their own database; never real-time fills."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha
from kquant_crypto.hybrid_research_review_store import ResearchReviewStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    source = (ROOT / args.source).resolve()
    if not source.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Isolated review source required')
    report = json.loads((source / 'report.json').read_text())
    if report['scope'] != 'DEV_ONLY' or sha(source / 'reviews.jsonl') != report['review_hash']:
        raise ValueError('Review source hash/scope mismatch')
    reviews = [json.loads(line) for line in (source / 'reviews.jsonl').read_text().splitlines()]
    if len(reviews) != report['reviewed_plans']:
        raise ValueError('Review count mismatch')
    destination = ROOT / 'work/multifactor_research_reviews.sqlite3'
    if destination.resolve() != destination:
        raise ValueError('Refusing redirected research database')
    with sqlite3.connect(destination, timeout=2) as connection:
        store = ResearchReviewStore(connection)
        result = store.ingest(args.run_id, {'scope': 'DEV_ONLY', 'report_hash': sha(source / 'report.json'),
            'review_hash': report['review_hash'], 'contract_hash': sha(source / 'contract.json')},
            reviews, recorded_at=datetime.now(timezone.utc).isoformat())
    print(json.dumps({**result, 'database': str(destination), 'run_id': args.run_id}))


if __name__ == '__main__':
    main()
