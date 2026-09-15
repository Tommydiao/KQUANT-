import pytest
from kquant_crypto.hybrid_health_journal import HealthJournal


def test_restart_dedup_and_recovery_transition(tmp_path):
    j = HealthJournal(tmp_path)
    first = j.append({}, now=10, max_age=5)
    assert first['changed']
    j.close()
    j = HealthJournal(tmp_path)
    assert not j.append({}, now=10, max_age=5)['inserted']
    assert not j.append({}, now=11, max_age=5)['changed']
    assert j.append({'process': {'state': 'OK', 'observed_at': 12}}, now=12, max_age=5)['changed']
    assert j.append({}, now=13, max_age=5)['changed']
    assert j.db.execute('SELECT COUNT(*) FROM health_samples').fetchone()[0] == 4
    j.close()


def test_clock_conflict_and_failed_insert_rollback(tmp_path):
    j = HealthJournal(tmp_path)
    j.append({}, now=10, max_age=5)
    with pytest.raises(ValueError, match='backward'):
        j.append({}, now=9, max_age=5)
    with pytest.raises(ValueError, match='Conflicting'):
        j.append({'process': {'state': 'OK', 'observed_at': 10}}, now=10, max_age=5)
    j.db.execute("CREATE TRIGGER fail_write BEFORE INSERT ON health_samples BEGIN SELECT RAISE(ABORT,'failure'); END")
    with pytest.raises(Exception, match='failure'):
        j.append({}, now=11, max_age=5)
    j.db.execute('DROP TRIGGER fail_write')
    assert j.append({}, now=11, max_age=5)['inserted']
    assert j.db.execute('SELECT COUNT(*) FROM health_samples').fetchone()[0] == 2
    j.close()
