"""Final projected UI delivery fix, no paid model calls or live stores."""
import sys
from bootstrap import activate
HERE,BASE,_=activate()
import kquant
for directory in ('projection-followup','budget-followup','delivery-followup'):
    kquant.__path__.insert(0,str(HERE/directory/'patches/kquant'))
sys.path.insert(0,str(BASE/'tests'))
import pytest
raise SystemExit(pytest.main([str(HERE),str(BASE/'tests/test_options_opening_momentum.py'),
    str(BASE/'tests/test_r58_positive_chain.py'),str(BASE/'tests/test_r58_p10_active_restart.py'),
    str(BASE/'tests/test_r58_p10_source_failure_isolation.py'),str(BASE/'tests/test_manual_operation_recovery.py'),
    '-q','--tb=short','--junitxml='+str(HERE/'evidence/delivery-boundary-regressions.xml')]))
