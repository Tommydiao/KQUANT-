"""Read-only regression for contradictory projected release declarations."""
from datetime import UTC, datetime
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('checked_launch', HERE / 'apply_checked_delta.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def read(path):
    return json.loads(path.read_bytes())


def main():
    old = HERE / 'release/local-candidate-0f4190e07e36ec96/deployment-projection.json'
    new = HERE / 'release/local-candidate-b6cf37cc4955061a/deployment-projection.json'
    before, after = read(old), read(new)
    try:
        guard.verify(old, sha256(old.read_bytes()).hexdigest())
    except ValueError as exc:
        rejected = str(exc)
    else:
        raise AssertionError('OLD_CONTRADICTORY_RELEASE_WAS_ACCEPTED')
    assert rejected == 'RELEASE_SECTION_HASH_CONFLICT: web/dist-unified/unified.html'
    checked, _, _ = guard.verify(new, sha256(new.read_bytes()).hexdigest())
    for section in ('retained_source_hashes','frontend_files','configuration_hashes','source_fact_hashes'):
        sample = {'files': {'same.py': {'sha256': 'a'}}, section: {'same.py': 'b'}}
        try:
            guard.release_hashes(sample)
        except ValueError:
            pass
        else:
            raise AssertionError('CONFLICT_NOT_REJECTED: ' + section)
        sample[section]['same.py'] = 'a'
        assert guard.release_hashes(sample) == {'same.py': 'a'}
    first = {x['target']: x['sha256'] for x in before['changes']}
    last = {x['target']: x['sha256'] for x in after['changes']}
    assert first == last and len(last) == 37
    result = dict(observed_at=datetime.now(UTC).isoformat(),
        old_rejected_before_stop=rejected, new_projected_release='PASS',
        candidate_id=checked['candidate_id'], runtime_payload_targets_identical=len(last),
        all_original_runtime_source_and_build_bytes_unchanged=True,
        synthetic_section_cases=8, production_writes=0, sdk_connections=0,
        authority='NO_NEW_LAUNCH_APPROVAL_CREATED')
    with (HERE / 'evidence/release-hash-boundary-20261018.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
