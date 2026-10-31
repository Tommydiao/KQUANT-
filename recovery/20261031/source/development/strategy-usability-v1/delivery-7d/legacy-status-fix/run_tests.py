from pathlib import Path
import os
import sys
import pytest

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]/'source/development/workspace'
sys.path.insert(0, str(BASE/'scripts'))
sys.path.insert(0, str(BASE/'tests'))
sys.path.insert(0, str(BASE.parent/'handoff/tools'))
os.environ['PYTHONPATH'] = str(HERE/'tools')+os.pathsep+str(BASE)
os.environ['KQUANT_TEST_LEGACY_OVERLAY'] = str(HERE)
related = '--related' in sys.argv
tests = [HERE/'test_legacy_status.py', HERE/'test_minute_index_restart.py',
         HERE/'test_main_store_concurrency.py']
if related:
    tests += [HERE.parent/'test_index_restart.py']
    tests += [BASE/'tests'/name for name in ('test_new_epoch_runtime.py',
        'test_p13_status_child.py', 'test_status_snapshot.py', 'test_market_calendar_singleflight.py')]
report = 'tests-related-bound.xml' if related else 'tests-final.xml'
raise SystemExit(pytest.main([*map(str, tests), '-q', '--junitxml='+str(HERE/report),
    *[arg for arg in sys.argv[1:] if arg != '--related']]))
