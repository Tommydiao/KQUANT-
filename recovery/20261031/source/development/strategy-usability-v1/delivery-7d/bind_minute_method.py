"""Prepare the accepted method only in the unpublished delivery overlay."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1] / 'workspace'
PATCH = HERE / 'patches'
RELATIVE = Path('config/review_acceptances')
RECEIPT = RELATIVE / 'local_closed_snapshot_owner_20261016.json'
CONFIG = RELATIVE / 'options_opening_trend_reference_sources.json'
sys.path.insert(0, str(BASE))
from kquant import options_minute_decisions as decisions
from kquant import options_one_minute as common


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_once(path, value):
    raw = (json.dumps(value, indent=2, ensure_ascii=True) + '\n').encode('utf-8')
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('EXISTING_OVERLAY_DIFFERS_REFUSE_OVERWRITE: ' + str(path))
        return
    with path.open('xb') as stream:
        stream.write(raw)


def main():
    receipt = load(PATCH / RECEIPT)
    proposal = HERE / receipt['human_decision_evidence']['scope_document']
    assert digest(proposal) == receipt['human_decision_evidence']['scope_document_sha256']
    assert common.digest(decisions.LOCAL_METHOD) == receipt['method_hash']
    constraint = load(HERE / 'constraint.json')
    assert common.timestamp(receipt['valid_until']) == common.timestamp(constraint['deadline_utc'])
    entry = load(BASE / 'config/local_workspace_entry.json')
    manifest_path = Path(entry['runtime_manifest']['path'])
    assert digest(manifest_path) == entry['runtime_manifest']['sha256']
    manifest = load(manifest_path)
    parent_hash = digest(BASE / CONFIG)
    assert parent_hash == manifest['files'][CONFIG.as_posix()]['sha256']
    source = load(BASE / CONFIG)
    assert source.get('canonical_resolution_method') is None
    proof = dict(status='ACCEPTED', semantics='CLOSED_SNAPSHOT_ADOPTION',
        method=decisions.LOCAL_METHOD, acceptance_path=RECEIPT.as_posix(),
        acceptance_sha256=digest(PATCH / RECEIPT))
    assert decisions._method(proof, now=datetime.now(timezone.utc), root=PATCH) == proof
    target = {**source, 'canonical_resolution_method': proof}
    write_once(PATCH / CONFIG, target)
    record = dict(schema='KQUANT_PENDING_METHOD_BINDING_V1',
        accepted_parent_candidate=entry['candidate_id'],
        parent_config_sha256=parent_hash, pending_config_sha256=digest(PATCH / CONFIG),
        acceptance_path=RECEIPT.as_posix(), acceptance_sha256=digest(PATCH / RECEIPT),
        method_hash=receipt['method_hash'], approved_at=receipt['approved_at'],
        valid_until=receipt['valid_until'], only_changed_key='canonical_resolution_method',
        production_config_modified=False, production_restarted=False,
        new_candidate_launch_approved=False, real_clock_measurement_proven=False,
        strict_s0_source_facts_proven=False)
    assert digest(BASE / CONFIG) == parent_hash
    write_once(HERE / 'minute-method-binding-20261016.json', record)
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
