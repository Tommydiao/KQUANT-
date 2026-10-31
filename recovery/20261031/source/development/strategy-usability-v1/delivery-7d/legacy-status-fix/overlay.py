"""Test-only small delta loader; policy files remain the actual accepted base files."""
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = ROOT / 'source/development/workspace'


def install():
    sys.path.insert(0, str(BASE))
    import kquant
    if str(HERE/'patches/kquant') not in kquant.__path__:
        kquant.__path__.insert(0, str(HERE/'patches/kquant'))
    spec = importlib.util.spec_from_file_location('kquant._legacy_original', BASE/'kquant/options_one_minute.py')
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    from kquant import options_one_minute, status_worker
    for name in ('ROOT', 'CONFIG', 'EVENT_PROPOSAL', 'EVENT_APPROVAL', 'STRATEGY_APPROVAL',
                 'STORE', 'EXPIRY_AUDIT_DIR'):
        setattr(options_one_minute, name, getattr(original, name))
    # Defaults are captured at function definition; use the same read-only source policy.
    options_one_minute.load_policy.__defaults__ = (original.CONFIG,)
    options_one_minute.status.__defaults__ = (original.STORE,)
    status_worker.ROOT = BASE
    return original, options_one_minute, status_worker
