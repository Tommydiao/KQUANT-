"""Spawn-safe loading of exactly the unpublished Monday overlay."""
import importlib.util
from importlib import import_module
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('monday_overlay_bootstrap',HERE/'bootstrap.py')
overlay=importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)
BASE=overlay.BASE
MODULES=('options_one_minute','options_one_minute_status','status_worker','main_store_runtime',
    'options_minute_decisions','options_intraday_comparison','options_opening_trend_runtime',
    'options_opening_trend_store','options_one_minute_runtime','options_intraday_reference',
    'options_api_budget','options_research_ai','options_research_ai_store','options_research_ai_lane','options_research_ai_worker',
    'recovery_preflight','recovery_runtime_probe','dashboard.app')

def activate(*,verify=False):
    overlay.activate()
    crypto=str(BASE/'crypto')
    if crypto not in sys.path:
        sys.path.insert(0,crypto)
    import kquant_crypto
    patch=str(HERE/'patches/crypto/kquant_crypto')
    if patch not in kquant_crypto.__path__:
        kquant_crypto.__path__=[patch,*list(kquant_crypto.__path__)]
    if verify:
        for name in MODULES:
            module=import_module('kquant.'+name)
            expected=(HERE/'patches/kquant'/Path(*name.split('.'))).with_suffix('.py')
            if not expected.is_file():
                expected=(HERE.parent/'legacy-status-fix/patches/kquant'/Path(*name.split('.'))).with_suffix('.py')
            if Path(module.__file__).resolve()!=expected.resolve():
                raise RuntimeError('MONDAY_DELTA_MODULE_MISMATCH:'+name)
    return HERE,BASE
