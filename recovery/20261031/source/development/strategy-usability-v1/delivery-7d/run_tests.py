import sys
import importlib
from pathlib import Path

HERE = Path(__file__).parent
BASE = HERE.parents[1] / 'workspace'
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(HERE))
import kquant
kquant.__path__.insert(0, str(HERE/'patches/kquant'))
next_delta = '--next' in sys.argv
if next_delta:
    kquant.__path__.insert(0, str(HERE/'next-patches/kquant'))
names = ('options_opening_trend_store', 'options_one_minute_recovery', 'options_opening_trend_recovery',
             'options_opening_trend_pipeline', 'options_intraday_reference', 'options_minute_decisions',
             'options_opening_momentum_journal', 'recovery_preflight', 'recovery_runtime_probe',
             'options_source_updates')
for name in names:
    loaded = importlib.import_module('kquant.' + name)
    expected = 'next-patches' if next_delta and name in {
        'options_opening_trend_recovery', 'options_opening_trend_store'} else 'patches'
    assert Path(loaded.__file__).resolve().is_relative_to((HERE/expected).resolve())
import pytest
tests = [HERE/'test_recovery_readiness.py', HERE/'test_delivery_accounting.py',
         HERE/'test_no_expiry_completion.py', HERE/'test_method_binding.py',
         HERE/'test_worker_recovery_flow.py', HERE/'test_journal_lookup.py', HERE/'test_index_restart.py',
         HERE/'test_source_lock.py']
tests += [HERE/'test_recovery_clock_boundary.py', HERE/'test_current_window_query.py',
          HERE/'test_deployment_guard.py', HERE/'test_transport_audit.py', HERE/'test_label_audit.py']
related = '--related' in sys.argv
if related:
    sys.path.insert(0, str(BASE/'tests'))
    tests += [BASE/'tests'/name for name in ('test_options_opening_momentum.py',
        'test_options_opening_trend_reference.py', 'test_r58_signal_recovery.py',
        'test_r58_p8_closeout.py', 'test_r58_p10_active_restart.py',
        'test_new_epoch_runtime.py', 'test_p12_metadata_restart.py')]
    tests += [BASE/'tests'/name for name in ('test_positive_contract_snapshot.py',
        'test_r58_p10_positive_acceptance.py', 'test_r58_positive_chain.py')]
    tests += [HERE.parent/'tests/test_strategy_usability.py',
              HERE.parent/'tests/test_writer_recovery.py']
report = 'related-tests.xml' if related else 'targeted-tests.xml'
if next_delta:
    report = 'next-' + report
raise SystemExit(pytest.main([*map(str, tests), '-q', '--junitxml='+str(HERE/report)]))
