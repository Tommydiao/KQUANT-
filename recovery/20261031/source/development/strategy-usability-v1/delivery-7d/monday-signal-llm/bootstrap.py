"""Load this unpublished delta above the frozen 4549 delta and accepted code."""
from pathlib import Path
import importlib.abc
import importlib.util
import sys

HERE = Path(__file__).resolve().parent
D7 = HERE.parent
ROOT = D7.parents[3]
BASE = ROOT / 'source/development/workspace'

class DashboardDelta(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname=='kquant.dashboard.app':
            return importlib.util.spec_from_file_location(fullname,HERE/'patches/kquant/dashboard/app.py')
        return None


def activate():
    sys.path.insert(0, str(BASE))
    import kquant
    for path in (D7 / 'legacy-status-fix/patches/kquant', HERE / 'patches/kquant'):
        if str(path) not in kquant.__path__:
            kquant.__path__.insert(0, str(path))
    if not any(isinstance(finder,DashboardDelta) for finder in sys.meta_path):
        sys.meta_path.insert(0,DashboardDelta())
    return HERE, BASE, ROOT
