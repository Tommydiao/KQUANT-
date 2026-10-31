"""TEST_ONLY Windows spawn topology for persistent source claims and budgets."""
from datetime import UTC, datetime, timedelta
import json
import multiprocessing
import os
from pathlib import Path

from kquant.options_price_action_source import SourceRequestBudget, claim_action, commit_action


def reserve_and_crash(directory, when):
    root = Path(directory)
    now = datetime.fromisoformat(when)
    budget = SourceRequestBudget(root / 'budget.json', cap=12, now=now)
    assert budget.grant(3) == 3
    claim = claim_action(root / 'index.json', [{'symbol': 'TEST', 'identity_status': 'verified'}],
                         now.date(), 'TEST_ONLY-method', now)
    (root / 'before-crash.json').write_text(json.dumps({'pid': os.getpid(), 'claim': claim,
                                                     'pending_before': budget.snapshot()['pending_reservations']}))
    os._exit(17)


def test_spawn_crash_preserves_unknown_cost_and_original_claim(tmp_path):
    now = datetime(2026, 10, 12, 12, 30, tzinfo=UTC)
    process = multiprocessing.get_context('spawn').Process(target=reserve_and_crash,
        args=(str(tmp_path), now.isoformat()))
    process.start()
    try:
        process.join(15)
        assert not process.is_alive()
        assert process.exitcode == 17
        before = json.loads((tmp_path / 'before-crash.json').read_text())
        assert before['pid'] != os.getpid()
        assert before['pending_before'] == 1
        recovered = SourceRequestBudget(tmp_path / 'budget.json', cap=12,
                                        now=now + timedelta(seconds=61))
        assert recovered.remaining == 9
        # Restart cannot claim an unknown old request was free.
        recovered.settle(3, 0)
        assert recovered.remaining == 9
        scope = [{'symbol': 'TEST', 'identity_status': 'verified'}]
        assert claim_action(tmp_path / 'index.json', scope, now.date(), 'TEST_ONLY-method',
                            now + timedelta(seconds=59)) is None
        replacement = claim_action(tmp_path / 'index.json', scope, now.date(), 'TEST_ONLY-method',
                                    now + timedelta(seconds=61))
        assert replacement[1]['attempts'] == 2
        assert replacement[1]['target_session'] == before['claim'][1]['target_session']
        assert replacement[1]['lease_id'] != before['claim'][1]['lease_id']
        assert not commit_action(tmp_path / 'index.json', 'TEST', before['claim'][1], {},
            tmp_path / 'unused.json', tmp_path, now.date(), 1, now + timedelta(seconds=62))
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        process.close()
