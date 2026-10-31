"""Opt-in for isolated spawned readers only, not installed in the environment."""
import os
from pathlib import Path

if os.environ.get('KQUANT_TEST_D7_OVERLAY') == str(Path(__file__).resolve().parents[1]):
    from bootstrap import activate
    activate()
