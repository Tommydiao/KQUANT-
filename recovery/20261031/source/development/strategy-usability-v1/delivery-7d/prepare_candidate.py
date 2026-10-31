"""Freeze a small unaccepted delta; no live code/config/database is written."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
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


def prepare():
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
    changes = []
    for path in sorted((HERE/'patches').rglob('*')):
        if path.is_file() and path.suffix in {'.py', '.json'}:
            target = path.relative_to(HERE/'patches').as_posix()
            previous = BASE/target
            changes.append(dict(target=target, payload=str(path), sha256=digest(path),
                previous_sha256=digest(previous) if previous.is_file() else None))
    assert len(changes) == 12
    projected = deepcopy(release)
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
    for row in recovery['databases']:
        if row['role'] == 'opening_research':
            row['schema_extension'] = 'OPENING_SOURCE_INDEX_V1'
    recovery_proof = save(out/'recovery-manifest.json', recovery)
    proposed_entry = dict(entry, candidate_id=candidate, runtime_manifest=release_proof,
        recovery_manifest=recovery_proof, production_accepted=False, shadow_runtime_accepted=False)
    proposed_entry_proof = save(out/'proposed-local-workspace-entry.json', proposed_entry)
    constraint = read(HERE/'constraint.json')
    bundle = dict(schema='KQUANT_UNACCEPTED_RESEARCH_DELTA_V1', candidate_id=candidate,
        candidate_payload_sha256=candidate_hash(recovery), base_candidate=entry['candidate_id'],
        base_entry_sha256=digest(entry_path), base_release_manifest=entry['runtime_manifest'],
        base_recovery_manifest=entry['recovery_manifest'], release_manifest=release_proof,
        recovery_manifest=recovery_proof, changes=changes, retired_build_assets=[],
        proposed_entry=proposed_entry_proof,
        deployment_tool=dict(path=str(HERE/'apply_accepted_delta.py'), sha256=digest(HERE/'apply_accepted_delta.py')),
        approved=False, applied=False, production_accepted=False, qualified_signal_authorized=False,
        frontend_rebuilt=False, frontend_reuse='EXACT_ACCEPTED_UNCHANGED_BUILD',
        data_epoch_reinitialized=False, live_writes=0, deadline_constraint=constraint,
        schema_extension=dict(role='opening_research', contract='OPENING_SOURCE_INDEX_V1',
            sql='CREATE INDEX IF NOT EXISTS trend_input_source ON two_hour_jobs(session,symbol,queued_at)',
            apply='original Worker initialization only after exact new launch acceptance',
            preserves_rows=True, deletes_or_replaces_databases=False,
            rollback='Older gate does not accept this additive index; refuse incompatible rollback, never overwrite business data.'),
        method_binding=read(HERE/'minute-method-binding-20261016.json'),
        deployment_requires=['exact new OWNER limited-research O-LAUNCH acceptance',
            'matching frozen assembly-hour evidence and separate performance verdict',
            'original controlled stop with process creation identities',
            'recheck baseline and delta hashes, changed-file-only rollback reference',
            'atomic payload replacement while stopped, original five-role gate',
            'original launch and ten-minute real loop/page observation'],
        preparation_tool_sha256=digest(Path(__file__)))
    proof = save(out/'deployment-projection.json', bundle)
    print(json.dumps(dict(proof, candidate_id=candidate, candidate_payload_sha256=bundle['candidate_payload_sha256'],
        changes=len(changes), applied=False)))


if __name__ == '__main__':
    prepare()
