from datetime import timedelta
from importlib.util import module_from_spec, spec_from_file_location
import sys
import pytest

from kquant import options_intraday_comparison as comparison
from kquant import options_opening_momentum as s0
from kquant import options_opening_trend_store as store
from test_method_binding import BASE, synthetic_inputs


def original_reader():
    name = 'kquant._d7_original_current_reader'
    if name not in sys.modules:
        spec = spec_from_file_location(name, BASE/'kquant/options_opening_trend_store.py')
        value = module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
    return sys.modules[name]


@pytest.mark.parametrize('delta,expected', [(1, 1), (299.999999, 1), (300, 0), (301, 0)])
def test_current_window_matches_original_without_renewing_deadline(tmp_path, delta, expected):
    args = synthetic_inputs()
    args['bars'] = args['bars'][2:]
    rows = comparison.evaluate_comparison_pair(**args)
    assert rows[0]['state'] == 'INCOMPLETE'
    assert rows[0]['strategy_comparison']['s1']['state'] == 'NUMERIC_PASS'
    path = tmp_path/'research.sqlite3'
    store.initialize(path)
    store.persist(rows, path)
    kwargs = dict(path=path, session='2026-10-19', scope_hash=args['scope_hash'],
        now=args['checkpoint']+timedelta(seconds=delta), policy=s0.load_policy())
    result = store.current_cards(**kwargs)
    assert result == original_reader().current_cards(**kwargs)
    assert result['evaluations_total'] == expected
    assert result['candidates'] == []
