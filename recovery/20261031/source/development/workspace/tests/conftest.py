"""Resolve retained handoff tools from this checkout, never from the old machine."""
from pathlib import Path
import sys


HANDOFF_TOOLS = Path(__file__).resolve().parents[2] / 'handoff' / 'tools'
if not (HANDOFF_TOOLS / 'new_data_epoch.py').is_file():
    raise RuntimeError('RETAINED_NEW_EPOCH_TOOL_MISSING')
sys.path.insert(0, str(HANDOFF_TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
