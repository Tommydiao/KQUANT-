"""Explicit candidate-only switch; accepted production bootstrap is untouched."""
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
env=dict(os.environ,KQUANT_TEST_WEEKEND_OVERLAY=str(HERE))
raise SystemExit(subprocess.call([sys.executable,str(HERE.parent/'opening-first-hour/run_topology.py'),
    *sys.argv[1:]],env=env))
