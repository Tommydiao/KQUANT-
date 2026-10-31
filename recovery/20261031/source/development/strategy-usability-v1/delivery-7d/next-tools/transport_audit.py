"""Capture the existing sanitized transport records in isolated assembly only."""
import json
import logging
import os
from pathlib import Path


class TransportFilter(logging.Filter):
    def filter(self, record):
        return record.msg == 'status_query_attempt %s'


def install(out, evidence_root):
    out, evidence_root = Path(out).resolve(), Path(evidence_root).resolve()
    if not out.is_relative_to(evidence_root) or not (out/'TEST_ONLY.json').is_file():
        raise ValueError('TRANSPORT_AUDIT_REQUIRES_ISOLATED_STORE')
    logger = logging.getLogger('kquant.status_worker')
    path = out/f'TEST_ONLY-query-transport-{os.getpid()}.jsonl'
    if any(getattr(item, 'baseFilename', None) == str(path) for item in logger.handlers):
        return
    handler = logging.FileHandler(path, mode='a', encoding='utf-8')
    handler.addFilter(TransportFilter())
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)
    warnings = logging.StreamHandler()
    warnings.setLevel(logging.WARNING)
    logger.addHandler(warnings)
    logger.propagate = False
    logger.setLevel(logging.INFO)


def summarize(directory):
    processes, files, problems = {}, [], []
    for path in sorted(Path(directory).glob('TEST_ONLY-query-transport-*.jsonl')):
        lines = path.read_text(encoding='utf-8').splitlines()
        files.append(str(path))
        for line in lines:
            try:
                prefix, raw = line.split(' ', 1)
                if prefix != 'status_query_attempt':
                    raise ValueError('UNEXPECTED_TRANSPORT_RECORD')
                row = json.loads(raw)
                pid, attempt = str(row['parent_pid']), row['attempt_id']
                process = processes.setdefault(pid, dict(records=0, success=0, failure=0,
                    deadline=0, last_attempt=0, last_denominator=None, errors=[]))
                if attempt != process['last_attempt']+1:
                    problems.append(dict(pid=pid, code='ATTEMPT_SEQUENCE_GAP', attempt=attempt))
                process['records'] += 1
                process['last_attempt'] = attempt
                process['last_denominator'] = row['denominator']
                process['success' if row['outcome'] == 'SUCCESS' else 'failure'] += 1
                process['deadline'] += int(row['outcome'] == 'PROCESS_DEADLINE')
                if row['outcome'] != 'SUCCESS':
                    process['errors'].append(dict(attempt_id=attempt, request_id=row['request_id'],
                        observed_at=row['observed_at'], outcome=row['outcome'],
                        stages_ms=row['stages_ms'], returncode=row['returncode']))
            except (ValueError, KeyError, TypeError) as exc:
                problems.append(dict(path=str(path), code=type(exc).__name__))
    for pid, process in processes.items():
        last = process['last_denominator'] or {}
        if (process['records'], process['success'], process['failure'], process['deadline']) != (
                last.get('attempts'), last.get('successes'), last.get('failures'), last.get('deadlines')):
            problems.append(dict(pid=pid, code='DENOMINATOR_MISMATCH'))
    return dict(test_only=True, available=bool(files), files=files, processes=processes,
        complete=bool(files) and not problems, problems=problems,
        totals={key: sum(row[key] for row in processes.values())
                for key in ('records', 'success', 'failure', 'deadline')})
