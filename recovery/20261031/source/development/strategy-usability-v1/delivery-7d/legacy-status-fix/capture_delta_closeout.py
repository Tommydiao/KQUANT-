"""Record small immutable development evidence, not a release or acceptance."""
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]/'source/development/workspace'
D7 = HERE.parent


def proof(path):
    return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest(),
            'bytes': path.stat().st_size}


changes = []
for path in sorted((HERE/'patches').rglob('*.py')):
    target = path.relative_to(HERE/'patches').as_posix()
    previous = BASE/target
    changes.append({**proof(path), 'target': target,
                    'live_sha256': proof(previous)['sha256'] if previous.is_file() else None})
tests = []
for name in ('tests-index-gate-bound.xml', 'tests-related-bound.xml',
             'tests-main-wal-20261017.xml', 'tests-related-wal-20261017.xml'):
    path = HERE/name
    suites = list(ET.parse(path).getroot().iter('testsuite'))
    tests.append({**proof(path), 'counts': {key: sum(int(s.get(key, 0)) for s in suites)
                                          for key in ('tests', 'failures', 'errors', 'skipped')}})
files = [HERE/name for name in ('indexed-cli-volume-result.json',
    'readonly-cli-results.json', 'readonly-cli-rowid-results.json',
    'universe-lock-20261017T032123Z.json')]
files += [D7/'user-page-confirmation-20261017.json',
    D7/'release/local-candidate-d4f4aad4be84d143/runtime-evidence-20261017T032504Z.json']
report = {'schema': 'KQUANT_UNPUBLISHED_DELTA_REVIEW_V1',
    'observed_at': datetime.now(UTC).isoformat(),
    'fixed_deadline': '2026-10-23T14:30:22Z',
    'running_candidate': 'local-candidate-d4f4aad4be84d143',
    'candidate_frozen': False, 'owner_launch_accepted': False,
    'production_writes': 0, 'sdk_connections': 0, 'frontend_changed': False,
    'changes': changes, 'tests': tests, 'evidence': list(map(proof, files)),
    'scope': {'legacy_response_equivalence': 'PASS',
        'actual_background_and_status_cli_isolated': 'PASS',
        'covering_index_75900_rows_isolated': 'PASS_5_OF_5',
        'live_unindexed_cli': 'FAIL_PRESERVED',
        'main_delete_mode': 'REAL_READONLY_OBSERVED',
        'main_lock_holder': 'UNKNOWN',
        'wal_cross_process_universe_read_mitigation': 'ISOLATED_PASS',
        'actual_page': 'USER_REPORTED', 'actual_sse_delivery': 'NOT_MEASURED',
        'new_delta_matched_hour': 'NOT_RUN', 'production_fix_verified': False,
        'market_window': 'NOT_RUN_WEEKEND', 'natural_signal': 'NOT_PROVEN'},
    'remaining': ['freeze exact delta with both additive index and startup WAL preparation',
        'include legacy background lane and representative history in actual topology harness',
        'profile remaining queue delay and run matching short then full hour',
        'consolidated exact OWNER acceptance before any live change',
        'next complete market window and actual page-delivery evidence']}
out = HERE/('delta-review-'+datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')+'.json')
with out.open('x', encoding='utf-8') as stream:
    json.dump(report, stream, indent=2)
print(json.dumps({'evidence': proof(out), 'changed_modules': len(changes), 'tests': tests,
                  'production_writes': 0, 'new_delta_matched_hour': 'NOT_RUN'}))
