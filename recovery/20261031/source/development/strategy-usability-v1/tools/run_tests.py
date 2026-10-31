import sys
from bootstrap import activate
DEV, BASE = activate()
sys.path.insert(0, str(BASE / "tests"))
import pytest

raise SystemExit(pytest.main([str(DEV / "tests"),
    str(BASE / "tests/test_options_opening_momentum.py"),
    str(BASE / "tests/test_r58_positive_chain.py"),
    str(BASE / "tests/test_p14_research_writers.py"),
    "-q", "--junitxml=" + str(DEV / "evidence/backend-tests.xml")]))
