"""Freeze a small unaccepted delta; no live code/config/database is written."""
from copy import deepcopy
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = ROOT/'source/development/workspace'
sys.path.insert(0, str(HERE/'tools'))
from bootstrap import activate
activate(verify=True)
from kquant.recovery_preflight import candidate_hash


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, indent=2)+'\n').encode()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    body = encoded(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != body:
            raise ValueError('FROZEN_CONTENT_CHANGED')
    else:
        with path.open('xb') as stream:
            stream.write(body)
    return dict(path=str(path), sha256=sha256(body).hexdigest())


def prepare(*,followup=False,budget_boundary=False,delivery_boundary=False,read_boundary=False):
    entry_path = BASE/'config/local_workspace_entry.json'
    entry = read(entry_path)
    for key in ('runtime_manifest', 'recovery_manifest'):
        assert digest(Path(entry[key]['path'])) == entry[key]['sha256'], key
    parent_release_path = Path(entry['runtime_manifest']['path'])
    release = read(parent_release_path)
    recovery = read(Path(entry['recovery_manifest']['path']))
    for proof in recovery['required_source']+recovery['frontend']:
        path = Path(proof['path'])
        assert path.is_relative_to(ROOT) and digest(path) == proof['sha256'], path
    payloads={}
    parent_delta=HERE.parent/'legacy-status-fix/release/local-candidate-45492b7b0b7428ca/deployment-projection.json'
    frozen_parent=read(parent_delta)
    for row in frozen_parent['changes']:
        assert digest(Path(row['payload']))==row['sha256'],'FROZEN_PARENT_CHANGED'
        payloads[row['target']]=Path(row['payload'])
    for path in sorted((HERE/'patches').rglob('*')):
        if path.is_file() and path.suffix in {'.py','.json','.tsx','.ts','.css'}:
            payloads[path.relative_to(HERE/'patches').as_posix()]=path
    if followup:
        expected={'options_opening_trend_store','options_opening_trend_summary',
            'options_intraday_comparison','options_research_ai','options_research_ai_worker'}
        files=list((HERE/'projection-followup/patches/kquant').glob('*.py'))
        if {path.stem for path in files}!=expected:
            raise ValueError('EXACT_FOLLOWUP_FILES_REQUIRED')
        for path in files:
            payloads['kquant/'+path.name]=path
    if delivery_boundary:
        if not budget_boundary:
            raise ValueError('DELIVERY_BOUNDARY_REQUIRES_FINAL_BUDGET_BOUNDARY')
        path=HERE/'delivery-followup/patches/kquant/research_http_snapshots.py'
        if not path.is_file():
            raise ValueError('EXACT_DELIVERY_BOUNDARY_REQUIRED')
        payloads['kquant/research_http_snapshots.py']=path
    if budget_boundary:
        if not followup:
            raise ValueError('BUDGET_BOUNDARY_REQUIRES_PROJECTION_FOLLOWUP')
        files=list((HERE/'budget-followup/patches/kquant').glob('*.py'))
        if {path.stem for path in files}!={'options_research_ai','options_research_ai_worker'}:
            raise ValueError('EXACT_BUDGET_BOUNDARY_FILES_REQUIRED')
        for path in files:
            payloads['kquant/'+path.name]=path
    if read_boundary:
        if not delivery_boundary:
            raise ValueError('READ_BOUNDARY_REQUIRES_DELIVERY_BOUNDARY')
        files=list((HERE/'read-followup/patches/kquant').glob('*.py'))
        if {path.stem for path in files}!={'options_research_ai','options_research_ai_store','options_research_ai_evidence'}:
            raise ValueError('EXACT_READ_BOUNDARY_FILES_REQUIRED')
        for path in files:
            payloads['kquant/'+path.name]=path
    payloads['config/options_opening_research_ai.json']=HERE/'config/research_ai.json'
    payloads['config/review_acceptances/opening_ai_budget.json']=HERE/'config/owner_llm_budget_sol61_20261018.json'
    for source,target in (('unified','dist-unified'),('stock','dist')):
        for path in sorted((HERE/'build'/source).rglob('*')):
            if path.is_file():
                payloads['web/'+target+'/'+path.relative_to(HERE/'build'/source).as_posix()]=path
    changes=[dict(target=target,payload=str(path),sha256=digest(path),
        previous_sha256=digest(BASE/target) if (BASE/target).is_file() else None)
        for target,path in sorted(payloads.items())]
    projected = deepcopy(release)
    projected['deployment_tool_sha256']=digest(HERE/'apply_accepted_delta.py')
    for row in changes:
        projected['files'][row['target']] = {'sha256': row['sha256']}
    projected.pop('candidate_id', None)
    projected['production_accepted'] = False
    candidate = 'local-candidate-'+sha256(encoded(projected)).hexdigest()[:16]
    projected['candidate_id'] = candidate
    out = HERE/'release'/candidate
    release_proof = save(out/'release-manifest.json', projected)
    required = {p['path']: p for p in recovery['required_source'] if Path(p['path']) != parent_release_path}
    for row in changes:
        target = str(BASE/row['target'])
        required[target] = dict(path=target, sha256=row['sha256'])
    required[release_proof['path']] = release_proof
    recovery.update(candidate_id=candidate, required_source=list(required.values()),
        final_runtime_accepted=False, qualified_signal_authorized=False, can_launch=False)
    recovery.pop('acceptance_receipt', None)
    frontend={row['path']:row for row in recovery['frontend']}
    for row in changes:
        if row['target'].startswith(('web/dist/','web/dist-unified/')):
            frontend[str(BASE/row['target'])]={'path':str(BASE/row['target']),'sha256':row['sha256']}
    recovery['frontend']=list(frontend.values())
    for row in recovery['databases']:
        if row['role'] == 'opening_research':
            row['schema_extension'] = 'OPENING_SOURCE_AND_CURRENT_INDEX_V1'
        elif row['role'] == 'minute':
            row['schema_extension'] = 'MINUTE_STATUS_METADATA_INDEX_V1'
        elif row['role']=='signal_copilot':
            row['schema_extension']='COPILOT_AI_BUDGET_QUEUE_V1'
    recovery_proof = save(out/'recovery-manifest.json', recovery)
    proposed_entry = dict(entry, candidate_id=candidate, runtime_manifest=release_proof,
        recovery_manifest=recovery_proof, production_accepted=False, shadow_runtime_accepted=False)
    proposed_entry_proof = save(out/'proposed-local-workspace-entry.json', proposed_entry)
    constraint = read(HERE.parent/'constraint.json')
    bundle = dict(schema='KQUANT_UNACCEPTED_RESEARCH_DELTA_V1', candidate_id=candidate,
        candidate_payload_sha256=candidate_hash(recovery), base_candidate=entry['candidate_id'],
        base_entry_sha256=digest(entry_path), base_release_manifest=entry['runtime_manifest'],
        base_recovery_manifest=entry['recovery_manifest'], release_manifest=release_proof,
        recovery_manifest=recovery_proof, changes=changes, retired_build_assets=[],
        proposed_entry=proposed_entry_proof,
        deployment_tool=dict(path=str(HERE/'apply_accepted_delta.py'), sha256=digest(HERE/'apply_accepted_delta.py')),
        approved=False, applied=False, production_accepted=False, qualified_signal_authorized=False,
        frontend_rebuilt=True, frontend_reuse='PAIRED_LOCAL_STOCK_AND_UNIFIED_BUILD',
        data_epoch_reinitialized=False, live_writes=0, deadline_constraint=constraint,
        schema_extension=dict(role='minute', contract='MINUTE_STATUS_METADATA_INDEX_V1',
            sql='CREATE INDEX IF NOT EXISTS one_minute_status_metadata ON one_minute_evaluations(session,symbol,right_name,created_at,bar_end,state)',
            apply='original Worker initialization only after exact new launch acceptance',
            preserves_rows=True, deletes_or_replaces_databases=False,
            rollback='Older gate does not accept this additive index; refuse incompatible rollback, never overwrite business data.'),
        retained_research_index='OPENING_SOURCE_INDEX_V1',
        additional_research_index='OPENING_SOURCE_AND_CURRENT_INDEX_V1',
        copilot_schema_extension='COPILOT_AI_BUDGET_QUEUE_V1',
        llm_config=dict(primary_model='gpt-6.1-sol',reasoning_effort='medium',review_model='gpt-6-astra',
            automatic_escalation=False,daily_shared_limit_usd=5,whole_task_limit_usd=1,
            initial_capability_total_usd=1,api_credentials_in_payload=False,
            live_model_access_verified=False,scope='READ_ONLY_ASYNC_OPENING_RESEARCH'),
        main_store_startup=dict(journal_mode='WAL', existing_file_only=True,
            apply='after exact launch acceptance, before workers start', business_rows_changed=False),
        method_binding=read(HERE.parent/'minute-method-binding-20261016.json'),
        deployment_requires=['exact new OWNER limited-research O-LAUNCH acceptance',
            'matching frozen assembly-hour evidence and separate performance verdict',
            'original controlled stop with process creation identities',
            'recheck baseline and delta hashes, changed-file-only rollback reference',
            'atomic payload replacement while stopped, original five-role gate',
            'original launch and ten-minute real loop/page observation'],
        preparation_tool_sha256=digest(Path(__file__)),
        projection_followup='SELECT_BEFORE_COMPACT_AND_READ_ONLY_AI_BOUNDARY_V1' if followup else None,
        model_cost_boundary='QUARANTINE_RETURNED_MODEL_IDENTITY_V1' if budget_boundary else None,
        snapshot_delivery_boundary='ASYNC_NESTED_REVISIONS_V1' if delivery_boundary else None,
        read_projection_boundary='PURE_READ_EVIDENCE_V1' if read_boundary else None)
    proof = save(out/'deployment-projection.json', bundle)
    print(json.dumps(dict(proof, candidate_id=candidate, candidate_payload_sha256=bundle['candidate_payload_sha256'],
        changes=len(changes), applied=False)))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--followup',action='store_true')
    parser.add_argument('--budget-boundary',action='store_true')
    parser.add_argument('--delivery-boundary',action='store_true')
    parser.add_argument('--read-boundary',action='store_true')
    arguments=parser.parse_args()
    prepare(followup=arguments.followup,budget_boundary=arguments.budget_boundary,delivery_boundary=arguments.delivery_boundary,read_boundary=arguments.read_boundary)
