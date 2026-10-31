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
    'recovery_preflight','recovery_runtime_probe','research_http_snapshots','dashboard.app')

FOLLOWUP=('options_opening_trend_store','options_opening_trend_summary',
    'options_intraday_comparison','options_research_ai','options_research_ai_worker')


def selected_projection():
    selected=os.environ.get('KQUANT_TEST_FROZEN_PROJECTION')
    if not selected:
        return None
    manifest=Path(selected).resolve()
    if not manifest.is_relative_to((HERE/'release').resolve()):
        raise ValueError('TEST_PROJECTION_OUTSIDE_DELIVERY')
    projection=json.loads(manifest.read_text(encoding='utf-8'))
    if projection.get('recovery_input_boundary') == 'REJECT_PUSH_BEFORE_PULL_TIME_PARSE_V1':
        proof = projection['inherited_projection']
        parent_path = Path(proof['path']).resolve()
        if (not parent_path.is_relative_to((HERE/'release').resolve())
                or sha256(parent_path.read_bytes()).hexdigest() != proof['sha256']):
            raise ValueError('FROZEN_PARENT_PROJECTION_CHANGED')
        parent = json.loads(parent_path.read_text(encoding='utf-8'))
        if parent['candidate_id'] != projection['base_candidate']:
            raise ValueError('FROZEN_PARENT_IDENTITY_MISMATCH')
        if [row['target'] for row in projection['changes']] != ['kquant/options_minute_decisions.py']:
            raise ValueError('EXACT_SINGLE_MINUTE_HELPER_REQUIRED')
        changes = {row['target']: row for row in parent['changes']}
        changes.update({row['target']: row for row in projection['changes']})
        projection = {**parent, **projection, 'changes': list(changes.values())}
    return projection


def selected_overrides():
    projection = selected_projection()
    if not projection:
        return {}
    if projection.get('projection_followup')!='SELECT_BEFORE_COMPACT_AND_READ_ONLY_AI_BOUNDARY_V1':
        return {}
    changes={row['target']:row for row in projection['changes']}
    result={}
    for name in FOLLOWUP:
        target='kquant/'+name+'.py'
        proof=changes[target]
        path=Path(proof['payload']).resolve()
        directory=('read-followup' if projection.get('read_projection_boundary')=='PURE_READ_EVIDENCE_V1' and name=='options_research_ai' else
            'budget-followup' if projection.get('model_cost_boundary')=='QUARANTINE_RETURNED_MODEL_IDENTITY_V1' and name in {'options_research_ai','options_research_ai_worker'} else 'projection-followup')
        expected=(HERE/directory/'patches'/target).resolve()
        if path!=expected or sha256(path.read_bytes()).hexdigest()!=proof['sha256']:
            raise ValueError('FOLLOWUP_PAYLOAD_MISMATCH:'+name)
        result[name]=path
    if projection.get('snapshot_delivery_boundary')=='ASYNC_NESTED_REVISIONS_V1':
        proof=changes['kquant/research_http_snapshots.py']
        path=Path(proof['payload']).resolve()
        expected=(HERE/'delivery-followup/patches/kquant/research_http_snapshots.py').resolve()
        if path!=expected or sha256(path.read_bytes()).hexdigest()!=proof['sha256']:
            raise ValueError('SNAPSHOT_DELIVERY_PAYLOAD_MISMATCH')
        result['research_http_snapshots']=path
    if projection.get('read_projection_boundary')=='PURE_READ_EVIDENCE_V1':
        for name in ('options_research_ai_store','options_research_ai_evidence'):
            target='kquant/'+name+'.py'
            proof=changes[target]
            path=Path(proof['payload']).resolve()
            expected=(HERE/'read-followup/patches'/target).resolve()
            if path!=expected or sha256(path.read_bytes()).hexdigest()!=proof['sha256']:
                raise ValueError('READ_PROJECTION_PAYLOAD_MISMATCH:'+name)
            result[name]=path
    if projection.get('metadata_restart_boundary') == 'WATCHLIST_TIMESTAMP_METADATA_V1':
        for name in ('recovery_preflight','recovery_runtime_probe'):
            target = 'kquant/' + name + '.py'
            proof = changes[target]
            path = Path(proof['payload']).resolve()
            expected = (HERE/'metadata-followup/patches'/target).resolve()
            if path != expected or sha256(path.read_bytes()).hexdigest() != proof['sha256']:
                raise ValueError('RESTART_METADATA_PAYLOAD_MISMATCH:' + name)
            result[name] = path
    if projection.get('recovery_input_boundary') == 'REJECT_PUSH_BEFORE_PULL_TIME_PARSE_V1':
        proof = changes['kquant/options_minute_decisions.py']
        path = Path(proof['payload']).resolve()
        expected = (HERE/'recovery-null-time-followup/patches/kquant/options_minute_decisions.py').resolve()
        if path != expected or sha256(path.read_bytes()).hexdigest() != proof['sha256']:
            raise ValueError('RECOVERY_INPUT_BOUNDARY_PAYLOAD_MISMATCH')
        result['options_minute_decisions'] = path
    return result

def activate(*,verify=False):
    overlay.activate()
    overrides=selected_overrides()
    if overrides:
        import kquant
        for directory in ('projection-followup','budget-followup','delivery-followup','read-followup','metadata-followup','recovery-null-time-followup'):
            path=str(HERE/directory/'patches/kquant')
            if any(file.is_relative_to(HERE/directory) for file in overrides.values()) and path not in kquant.__path__:
                kquant.__path__.insert(0,path)
    crypto=str(BASE/'crypto')
    if crypto not in sys.path:
        sys.path.insert(0,crypto)
    import kquant_crypto
    patch=str(HERE/'patches/crypto/kquant_crypto')
    if patch not in kquant_crypto.__path__:
        kquant_crypto.__path__=[patch,*list(kquant_crypto.__path__)]
    selected = os.environ.get('KQUANT_TEST_FROZEN_PROJECTION')
    if selected:
        projection = selected_projection()
        if projection.get('gateway_transport_boundary') == 'BOUNDED_COOKIELESS_SNAPSHOT_POOL_IDLE2_V1':
            proof = next(row for row in projection['changes'] if row['target'] == 'crypto/kquant_crypto/gateway.py')
            expected_gateway = HERE/'transport-idle-followup/patches/crypto/kquant_crypto/gateway.py'
            if Path(proof['payload']).resolve() != expected_gateway.resolve() or sha256(expected_gateway.read_bytes()).hexdigest() != proof['sha256']:
                raise ValueError('GATEWAY_TRANSPORT_PAYLOAD_MISMATCH')
            directory = str(expected_gateway.parent)
            if directory not in kquant_crypto.__path__:
                kquant_crypto.__path__.insert(0, directory)
            if verify and Path(import_module('kquant_crypto.gateway').__file__).resolve() != expected_gateway.resolve():
                raise RuntimeError('GATEWAY_TRANSPORT_MODULE_MISMATCH')
    if verify:
        extra=('options_research_ai_evidence',) if 'options_research_ai_evidence' in overrides else ()
        for name in (*MODULES,*extra):
            module=import_module('kquant.'+name)
            expected=overrides.get(name) or (HERE/'patches/kquant'/Path(*name.split('.'))).with_suffix('.py')
            if not expected.is_file():
                expected=(HERE.parent/'legacy-status-fix/patches/kquant'/Path(*name.split('.'))).with_suffix('.py')
            if not expected.is_file():
                expected=(BASE/'kquant'/Path(*name.split('.'))).with_suffix('.py')
            if Path(module.__file__).resolve()!=expected.resolve():
                raise RuntimeError('MONDAY_DELTA_MODULE_MISMATCH:'+name)
    return HERE,BASE
