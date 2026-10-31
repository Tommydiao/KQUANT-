"""Explicit unpublished test overlay, including actual status CLI and app."""
import importlib.abc
import importlib.util
from pathlib import Path
import sys
from importlib import import_module

HERE = Path(__file__).resolve().parents[1]
BASE = HERE.parents[4]/'source/development/workspace'
MODULES = ('options_one_minute', 'options_one_minute_status', 'status_worker',
           'recovery_preflight', 'recovery_runtime_probe', 'main_store_runtime', 'dashboard.app',
           'options_minute_decisions')


class AppDelta(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'kquant.dashboard.app':
            return importlib.util.spec_from_file_location(fullname, HERE/'patches/kquant/dashboard/app.py')
        return None


def activate(*, verify=False):
    sys.path.insert(0, str(BASE))
    import kquant
    patch = str(HERE/'patches/kquant')
    if patch not in kquant.__path__:
        kquant.__path__.insert(0, patch)
    if not any(isinstance(finder, AppDelta) for finder in sys.meta_path):
        sys.meta_path.insert(0, AppDelta())
    if verify:
        for name in MODULES:
            module = import_module('kquant.'+name)
            if Path(module.__file__).resolve() != (HERE/'patches/kquant'/Path(*name.split('.'))).with_suffix('.py').resolve():
                raise RuntimeError('DELTA_MODULE_MISMATCH: '+name)
    return HERE, BASE
