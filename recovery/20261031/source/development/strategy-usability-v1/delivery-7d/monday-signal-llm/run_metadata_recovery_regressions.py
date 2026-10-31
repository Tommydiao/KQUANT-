import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
os.environ['KQUANT_TEST_FROZEN_PROJECTION'] = str(HERE/'release/local-candidate-4998d113d64b3570/deployment-projection.json')
sys.path.insert(0, str(HERE/'metadata-tools'))
from bootstrap import activate
_, BASE = activate(verify=True)
sys.path[:0] = [str(BASE/'tests'), str(BASE)]
import pytest
raise SystemExit(pytest.main([
    str(BASE/'tests/test_r58_p10_recovery_gate.py'),
    str(BASE/'tests/test_r58_p10_session_recovery.py'),
    str(HERE/'test_watchlist_restart_metadata.py'), '-q',
    '--junitxml='+str(HERE/'evidence/restart-metadata-affected-regressions.xml')]))
