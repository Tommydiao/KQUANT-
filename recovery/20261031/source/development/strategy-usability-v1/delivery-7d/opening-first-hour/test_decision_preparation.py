from datetime import date

import first_hour_minute_decisions as decisions
from first_hour import session_bounds_utc


def test_preparation_reads_existing_decisions_once(tmp_path, monkeypatch):
    now, _ = session_bounds_utc(date(2026, 10, 22))
    existing = [{'selected_version_id': 'TEST_ONLY', 'source_semantics': {}}]
    reads = []
    monkeypatch.setattr(decisions, '_method', lambda *a, **kw: {'semantics': 'PROVIDER_CONFIRMED_BAR'})
    monkeypatch.setattr(decisions, 'read', lambda *a, **kw: reads.append(kw) or existing)
    assert decisions.resolve(tmp_path/'isolated.sqlite3', [], symbol='TEST',
        session='2026-10-22', now=now, proof={}, root=tmp_path, include_existing=True) == existing
    assert len(reads) == 1


def test_invalid_method_does_not_create_or_hide_existing_decisions(tmp_path, monkeypatch):
    now, _ = session_bounds_utc(date(2026, 10, 22))
    existing = [{'decision_hash': 'TEST_ONLY_REQUIRES_MODEL_REVALIDATION'}]
    monkeypatch.setattr(decisions, '_method', lambda *a, **kw: None)
    monkeypatch.setattr(decisions, 'read', lambda *a, **kw: existing)
    args = dict(symbol='TEST', session='2026-10-22', now=now, proof={}, root=tmp_path)
    assert decisions.resolve(tmp_path/'isolated.sqlite3', [], **args) == []
    assert decisions.resolve(tmp_path/'isolated.sqlite3', [], include_existing=True, **args) == existing
    assert not (tmp_path/'isolated.sqlite3').exists()
