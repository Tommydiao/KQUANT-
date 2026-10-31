from copy import deepcopy
from datetime import timedelta
import importlib.util
from pathlib import Path

import pytest
from overlay import install, BASE
install()
from kquant import options_minute_decisions as revised
from kquant import options_opening_trend_store as store
from kquant import options_opening_momentum_journal as journal
from test_options_opening_momentum import inputs
from test_r58_p8_closeout import local_method, three_versions

spec = importlib.util.spec_from_file_location('kquant._previous_decisions', BASE/'kquant/options_minute_decisions.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)


@pytest.mark.parametrize('duplicates', [False, True])
def test_exact_decisions_and_idempotency_with_fewer_hashes(tmp_path, monkeypatch, duplicates):
    args = inputs()
    early, push, pull = three_versions(args)
    rows = [early, push, pull]
    if duplicates:
        rows.extend([deepcopy(push), deepcopy(pull)])
    proof = local_method(tmp_path, args)
    results, counts = [], []
    digest = revised.common.digest
    for name, module in [('old', previous), ('new', revised)]:
        path = tmp_path/(name+'.sqlite3')
        store.initialize(path)
        journal.initialize(path)
        calls = []
        def counted(value):
            calls.append(1)
            return digest(value)
        with monkeypatch.context() as patch:
            patch.setattr(revised.common, 'digest', counted)
            results.append(module.resolve(path, rows, symbol='TEST', session='2026-10-02',
                now=args['now'], proof=proof, root=tmp_path))
            assert module.resolve(path, rows, symbol='TEST', session='2026-10-02',
                now=args['now']+timedelta(seconds=1), proof=proof, root=tmp_path) == []
        counts.append(len(calls))
    assert results[0] == results[1]
    assert counts[1] < counts[0]
