"""Spawn-safe first-hour TEST_ONLY overlay; no accepted payload is edited."""
import importlib.abc
import importlib.util
import importlib
from pathlib import Path
import sys
import os

FIRST = Path(__file__).resolve().parents[1]
HERE = FIRST.parent/'monday-signal-llm'
spec = importlib.util.spec_from_file_location('inherited_assembly_bootstrap', HERE/'live-fact-child-tools/bootstrap.py')
inherited = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inherited)
BASE = inherited.BASE
MODULES = inherited.MODULES
selected_projection = inherited.selected_projection


class FirstHourFinder(importlib.abc.MetaPathFinder):
    def __init__(self, mapping):
        self.mapping = mapping

    def find_spec(self, fullname, path=None, target=None):
        file = self.mapping.get(fullname)
        return importlib.util.spec_from_file_location(fullname, file) if file else None


def activate(*, verify=False):
    inherited.activate()
    if str(FIRST) not in sys.path:
        sys.path.insert(0, str(FIRST))
    mapping = {'kquant.'+name:path for name,path in inherited.selected_overrides().items()}
    mapping['kquant_crypto.gateway'] = FIRST/'gateway_candidate.py'
    for name, file in {
        'options_minute_admission':'first_hour_minute_admission.py',
        'options_minute_decisions':'first_hour_minute_decisions.py',
        'options_opening_trend_runtime':'first_hour_runtime.py',
        'options_opening_trend_store':'first_hour_store.py',
        'options_opening_trend_current':'first_hour_current.py',
        'options_opening_trend_summary':'first_hour_summary.py',
        'options_opening_trend_pipeline':'first_hour_pipeline.py',
        'options_intraday_reference':'first_hour_reference.py',
        'status_worker':'first_hour_status_worker.py',
        'research_http_snapshots':'first_hour_http_snapshots.py',
        'published_status_snapshot':'published_status_snapshot.py',
    }.items():
        mapping['kquant.'+name] = FIRST/file
    weekend=FIRST.parent/'weekend-20261031'
    if os.environ.get('KQUANT_TEST_WEEKEND_OVERLAY')==str(weekend):
        for path in (weekend/'patches/kquant').rglob('*.py'):
            module='.'.join(path.relative_to(weekend/'patches/kquant').with_suffix('').parts)
            mapping['kquant.'+module]=path
    if not any(isinstance(f, FirstHourFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, FirstHourFinder(mapping))
    if verify:
        for name in MODULES:
            importlib.import_module('kquant.'+name)
        for name, path in mapping.items():
            module = importlib.import_module(name)
            if Path(module.__file__).resolve() != path.resolve():
                raise RuntimeError('FIRST_HOUR_MODULE_MISMATCH:'+name)
    return HERE, BASE
