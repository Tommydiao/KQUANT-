"""Opt-in isolated subprocess overlay; never installed in the live environment."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
if os.environ.get('KQUANT_TEST_RESEARCH_OVERLAY') == str(root):
    base = root.parent / 'workspace'
    sys.path.insert(0, str(base))
    import kquant
    kquant.__path__.insert(0, str(root / 'kquant'))
