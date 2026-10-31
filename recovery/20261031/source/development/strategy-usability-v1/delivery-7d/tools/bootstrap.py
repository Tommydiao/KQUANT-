"""Explicit development overlay; never alters the accepted runtime payload."""
from importlib import import_module
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parents[1]
BASE = HERE.parents[1] / 'workspace'
MODULES = ('options_opening_trend_store', 'options_one_minute_recovery', 'options_opening_trend_recovery',
    'options_opening_trend_pipeline', 'options_intraday_reference', 'options_minute_decisions',
    'options_opening_momentum_journal', 'recovery_preflight', 'recovery_runtime_probe',
    'options_source_updates')


def activate(*, verify=False):
    sys.path.insert(0, str(BASE))
    import kquant
    patch = HERE/'patches/kquant'
    if str(patch) not in kquant.__path__:
        kquant.__path__.insert(0, str(patch))
    if verify:
        for name in MODULES:
            module = import_module('kquant.' + name)
            if Path(module.__file__).resolve() != (patch/(name+'.py')).resolve():
                raise RuntimeError('D7_OVERLAY_MODULE_MISMATCH: '+name)
    return HERE, BASE
