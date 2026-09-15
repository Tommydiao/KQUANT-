"""Synthetic contract evidence, not runtime or performance certification."""

from concurrent.futures import Future
from dataclasses import asdict
import sqlite3

import pytest

from kquant_crypto.hybrid_contracts import DecisionTimeline
from kquant_crypto.hybrid_identity import economic_signal_id
from kquant_crypto.hybrid_transaction_contract import ContractWriter, SyntheticLedger


def create(db=None, *, run='fixture', arm='T+B'):
    ledger = SyntheticLedger(db or sqlite3.connect(':memory:'))
    ledger.create_account(run, arm, cash=10000, risk_limit=50)
    return ledger


def offer(ledger, *, seq=1, version=None, model='model_fixture', news='none', arm='T+B'):
    state = ledger.account('fixture', arm)
    signal = economic_signal_id('base', 'base_policy', 'BTCUSDT', 'UP_TREND', 36000, seq)
    return ledger.record_evaluation(
        run='fixture', arm=arm, signal_id=signal,
        expected_version=state['version'] if version is None else version,
        portfolio_hash=state['state_hash'], bindings={
            'base_policy': 'base_policy', 'feature': 'features', 'model': model,
            'intelligence_policy': 'disabled_fixture', 'execution_policy': 'delayed_fixture',
            'cost': 'base_cost', 'risk_forecast': 'risk_fixture', 'events': news,
        }, timeline=asdict(DecisionTimeline(36000, 36001, 36001, 36002, 36003, 36004, 36004, 36301)),
        quantity=1, reserve_cash=100, reserve_risk=10,
    )


def test_stale_portfolio_rejects_without_reservation():
    ledger = create()
    first, second = offer(ledger), offer(ledger, seq=2)
    assert ledger.commit_entry(first, committed_at=36004)['status'] == 'ACCEPTED'
    assert ledger.commit_entry(second, committed_at=36004)['status'] == 'ABSTAIN_PORTFOLIO_CHANGED'
    assert ledger.account('fixture', 'T+B')['reserved_cash'] == 100


def test_news_reevaluation_one_intent_and_repeat_no_cash_change():
    ledger = create()
    ids = [offer(ledger, news=str(i)) for i in range(3)]
    result = ledger.commit_entry(ids[0], committed_at=36004)
    for eid in ids:
        assert ledger.commit_entry(eid, committed_at=36004)['intent_id'] == result['intent_id']
    assert ledger.count('hybrid_entry_intents') == 1
    assert ledger.account('fixture', 'T+B')['reserved_cash'] == 100


def test_arms_have_independent_intents():
    ledger = create()
    ledger.create_account('fixture', 'T', cash=10000, risk_limit=50)
    a = ledger.commit_entry(offer(ledger), committed_at=36004)
    b = ledger.commit_entry(offer(ledger, arm='T'), committed_at=36004)
    assert a['intent_id'] != b['intent_id']
    assert ledger.count('hybrid_entry_intents') == 2


def test_partial_commit_fault_rolls_back_everything():
    ledger = create()
    eid = offer(ledger)
    before = ledger.account('fixture', 'T+B')
    with pytest.raises(RuntimeError, match='injected'):
        ledger.commit_entry(eid, committed_at=36004, inject_fault=True)
    assert ledger.account('fixture', 'T+B') == before
    assert ledger.count('hybrid_entry_intents') == 0
    assert ledger.count('hybrid_decisions') == 0


def test_protection_before_ready_entry_and_never_waits_model_future():
    ledger = create()
    eid = offer(ledger)
    model_future = Future()
    writer = ContractWriter(ledger)
    writer.enqueue_entry(eid, at=36004)
    writer.enqueue_model(model_future)
    writer.enqueue_protection('fixture', 'T+B', 'btc_exit_no_quote', at=36004,
                              reason='EXIT_PENDING_NO_VALID_QUOTE')
    results = writer.drain_ready()
    assert results[0]['status'] == 'EXIT_PENDING_NO_VALID_QUOTE'
    assert results[1]['status'] == 'ABSTAIN_PORTFOLIO_CHANGED'
    assert not model_future.done()
    assert ledger.account('fixture', 'T+B')['reserved_cash'] == 0
    assert ledger.count('hybrid_fills') == 0


def test_restart_same_intent_and_consumed_fill_are_idempotent(tmp_path):
    path = tmp_path / 'synthetic.sqlite3'
    ledger = create(sqlite3.connect(path))
    eid = offer(ledger)
    intent = ledger.commit_entry(eid, committed_at=36004)['intent_id']
    ledger.close()
    recovered = SyntheticLedger(sqlite3.connect(path))
    assert recovered.commit_entry(eid, committed_at=36004)['intent_id'] == intent
    assert recovered.fill(intent, 'quote_1', event_at=36005, received_at=36005,
                          quantity=.5, spent_cash=50)['status'] == 'PARTIAL'
    before = recovered.account('fixture', 'T+B')
    recovered.fill(intent, 'quote_1', event_at=36005, received_at=36005, quantity=.5, spent_cash=50)
    assert recovered.account('fixture', 'T+B') == before
    assert recovered.count('hybrid_fills') == 1
    with pytest.raises(ValueError, match='approved'):
        recovered.fill(intent, 'quote_2', event_at=36006, received_at=36006, quantity=.6, spent_cash=60)


def test_past_open_and_expired_fill_never_mutate_ledger():
    ledger = create()
    intent = ledger.commit_entry(offer(ledger), committed_at=36004)['intent_id']
    before = ledger.account('fixture', 'T+B')
    for event, receipt in [(36000, 36005), (36004, 36005), (36302, 36302)]:
        with pytest.raises(ValueError, match='time'):
            ledger.fill(intent, str(event), event_at=event, received_at=receipt, quantity=1, spent_cash=100)
    assert ledger.account('fixture', 'T+B') == before


def test_duplicate_event_with_changed_payload_rejected():
    ledger = create()
    intent = ledger.commit_entry(offer(ledger), committed_at=36004)['intent_id']
    ledger.fill(intent, 'q1', event_at=36005, received_at=36005, quantity=.5, spent_cash=50)
    with pytest.raises(ValueError, match='conflict'):
        ledger.fill(intent, 'q1', event_at=36005, received_at=36005, quantity=.5, spent_cash=51)


def test_foreign_database_refused():
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE candidate_runs (id TEXT)')
    with pytest.raises(ValueError, match='isolated'):
        SyntheticLedger(db)


def test_missing_binding_or_nonfinite_number_rejected():
    ledger = create()
    with pytest.raises(ValueError):
        ledger.create_account('bad', 'T', cash=float('nan'), risk_limit=50)
    with pytest.raises(ValueError):
        offer(ledger, model='')


def test_writer_failure_halts_without_replaying_or_consuming_next_event(monkeypatch):
    ledger=create()
    eid=offer(ledger)
    writer=ContractWriter(ledger)
    writer.enqueue_entry(eid,at=36004)
    writer.enqueue_protection('fixture','T+B','later',at=36005,reason='EXIT_PENDING_NO_VALID_QUOTE')
    def failure(*args,**kwargs):
        raise sqlite3.OperationalError('synthetic disk failure')
    monkeypatch.setattr(ledger,'commit_entry',failure)
    with pytest.raises(sqlite3.OperationalError):
        writer.drain_ready()
    assert writer.halted and len(writer.queue)==1
    assert ledger.count('hybrid_entry_intents')==0
    with pytest.raises(RuntimeError,match='halted'):
        writer.drain_ready()
