"""Spawn-safe loading of exactly the unpublished Monday overlay."""
import importlib.util
from importlib import import_module
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('monday_overlay_bootstrap',HERE/'bootstrap.py')
overlay=importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)
BASE=overlay.BASE
MODULES=('options_one_minute','options_one_minute_status','status_worker','main_store_runtime',
    'options_minute_decisions','options_intraday_comparison','options_opening_trend_runtime',
    'options_opening_trend_store','options_opening_trend_summary','options_one_minute_runtime','options_intraday_reference',
    'options_api_budget','options_research_ai','options_research_ai_store','options_research_ai_lane','options_research_ai_worker',
    'recovery_preflight','recovery_runtime_probe','dashboard.app')

FOLLOWUP=('options_opening_trend_store','options_opening_trend_summary',
    'options_intraday_comparison','options_research_ai','options_research_ai_worker')


def selected_overrides():
    selected=os.environ.get('KQUANT_TEST_FROZEN_PROJECTION')
    if not selected:
        return {}
    manifest=Path(selected).resolve()
    if not manifest.is_relative_to((HERE/'release').resolve()):
        raise ValueError('TEST_PROJECTION_OUTSIDE_DELIVERY')
    projection=json.loads(manifest.read_text(encoding='utf-8'))
    if projection.get('projection_followup')!='SELECT_BEFORE_COMPACT_AND_READ_ONLY_AI_BOUNDARY_V1':
        return {}
    changes={row['target']:row for row in projection['changes']}
    result={}
    for name in FOLLOWUP:
        target='kquant/'+name+'.py'
        proof=changes[target]
        path=Path(proof['payload']).resolve()
        expected=(HERE/'projection-followup/patches'/target).resolve()
        if path!=expected or sha256(path.read_bytes()).hexdigest()!=proof['sha256']:
            raise ValueError('FOLLOWUP_PAYLOAD_MISMATCH:'+name)
        result[name]=path
    return result

def activate(*,verify=False):
    overlay.activate()
    overrides=selected_overrides()
    if overrides:
        import kquant
        path=str(HERE/'projection-followup/patches/kquant')
        if path not in kquant.__path__:
            kquant.__path__.insert(0,path)
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
            expected=overrides.get(name) or (HERE/'patches/kquant'/Path(*name.split('.'))).with_suffix('.py')
            if not expected.is_file():
                expected=(HERE.parent/'legacy-status-fix/patches/kquant'/Path(*name.split('.'))).with_suffix('.py')
            if not expected.is_file():
                expected=(BASE/'kquant'/Path(*name.split('.'))).with_suffix('.py')
            if Path(module.__file__).resolve()!=expected.resolve():
                raise RuntimeError('MONDAY_DELTA_MODULE_MISMATCH:'+name)
    return HERE,BASE
