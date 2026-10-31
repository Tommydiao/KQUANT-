import importlib.util
import json
import logging
from pathlib import Path

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('transport_audit', HERE/'next-tools/transport_audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_filter_never_records_unrelated_or_raw_error_messages():
    keep = audit.TransportFilter()
    assert keep.filter(logging.LogRecord('x', 20, '', 1, 'status_query_attempt %s', (), None))
    assert not keep.filter(logging.LogRecord('x', 40, '', 1, 'status_query_failed %s', (), None))


def record(attempt, outcome, successes, failures):
    return 'status_query_attempt '+json.dumps(dict(parent_pid=11, attempt_id=attempt,
        request_id=str(attempt), observed_at='2026-10-16T17:00:00Z', outcome=outcome,
        stages_ms={}, returncode=0 if outcome == 'SUCCESS' else 1,
        denominator=dict(attempts=attempt, successes=successes, failures=failures, deadlines=0)))


def test_success_and_failure_share_one_denominator(tmp_path):
    (tmp_path/'TEST_ONLY-query-transport-11.jsonl').write_text(
        record(1, 'SUCCESS', 1, 0)+'\n'+record(2, 'CHILD_ERROR', 1, 1)+'\n')
    value = audit.summarize(tmp_path)
    assert value['complete']
    assert value['totals'] == dict(records=2, success=1, failure=1, deadline=0)


def test_missing_early_attempts_not_reported_as_complete(tmp_path):
    (tmp_path/'TEST_ONLY-query-transport-11.jsonl').write_text(record(2, 'SUCCESS', 2, 0))
    value = audit.summarize(tmp_path)
    assert not value['complete']
    assert {row['code'] for row in value['problems']} == {'ATTEMPT_SEQUENCE_GAP', 'DENOMINATOR_MISMATCH'}
