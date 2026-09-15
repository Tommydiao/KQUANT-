import json
import sqlite3

import pytest
from kquant_crypto.hybrid_observation import ObservationStore
from kquant_crypto.hybrid_observer_run_audit import snapshot_database, audit_database
from test_candidate_portfolio import warm_states, RULES
from test_hybrid_observation import seeded, quote, btc
from kquant_crypto.hybrid_observation_window import planned_window
from kquant_crypto.candidate_policy import digest


def test_actual_store_snapshot_keeps_pending_and_unfilled_separate(tmp_path, warm_states):
    observer = seeded(warm_states)
    path = tmp_path / 'hybrid_source.sqlite3'
    store = ObservationStore(path, observer.portfolio.policy, RULES)
    store.db.execute('INSERT INTO observer_checkpoint VALUES(1,?)', (json.dumps(observer.state()),))
    store.db.commit()
    store.process('quote', quote(observer))
    target = tmp_path / 'hybrid_copy.sqlite3'
    snapshot_database(path, target)
    report = audit_database(target)
    assert report['ledger_integrity_pass']
    assert not report['G3_passed'] and not report['exchange_fill_evidence']
    assert any(g['counts'].get('fill:FILLED') and g['counts'].get('label:PENDING') for g in report['label_funnel'])
    assert store.db.execute('SELECT COUNT(*) FROM observer_events').fetchone()[0] == 1
    with pytest.raises(ValueError, match='New independent'):
        snapshot_database(path, target)
    store.close()


def test_missing_label_or_modified_event_is_detected(tmp_path, warm_states):
    observer = seeded(warm_states)
    path = tmp_path / 'hybrid_source.sqlite3'
    store = ObservationStore(path, observer.portfolio.policy, RULES)
    store.db.execute('INSERT INTO observer_checkpoint VALUES(1,?)', (json.dumps(observer.state()),))
    store.db.commit()
    store.process('quote', quote(observer))
    store.close()
    db = sqlite3.connect(path)
    with db:
        db.execute('DELETE FROM observer_labels')
        db.execute('UPDATE observer_events SET hash=?', ('modified',))
    db.close()
    report = audit_database(path)
    assert not report['ledger_integrity_pass']
    reasons = {e['reason'] for e in report['integrity_errors']}
    assert {'EVENT_HASH_MISMATCH', 'CHECKPOINT_LABEL_ID_SET_MISMATCH'} <= reasons


def test_planned_denominator_does_not_shrink_to_observed_quotes(tmp_path, warm_states):
    observer = seeded(warm_states)
    path = tmp_path / 'hybrid_window.sqlite3'
    store = ObservationStore(path, observer.portfolio.policy, RULES)
    store.db.execute('INSERT INTO observer_checkpoint VALUES(1,?)', (json.dumps(observer.state()),))
    store.db.commit()
    window = planned_window(100, 86400)
    event = quote(observer) | {'received_at_monotonic': 110, 'observation_window_hash': digest(window)}
    store.process('first', event)
    clock = {'type': 'clock', 'received_at': event['received_at'] + 10,
             'received_at_monotonic': 120, 'observation_window_hash': digest(window)}
    store.process('later', clock)
    store.close()
    report = audit_database(path, observation_window=window)
    assert report['ledger_integrity_pass']
    planned = report['preregistered_slo_window']
    assert planned['per_symbol']['BTCUSDT']['scheduled_seconds'] == 86400
    assert not planned['G3_passed']
    wrong = audit_database(path, observation_window=planned_window(200, 86400))
    assert not wrong['ledger_integrity_pass']
