"""One small changed-file payload/rollback archive, with no databases or secrets."""
from hashlib import sha256
import json
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = ROOT/'source/development/workspace'
sys.path.insert(0, str(HERE/'tools'))
from bootstrap import activate
activate(verify=True)
from kquant.recovery_preflight import checked_path, candidate_hash


def raw(path):
    return checked_path(str(path), [ROOT]).read_bytes()


def digest(value):
    return sha256(value).hexdigest()


def main():
    projection_path = checked_path(sys.argv[1], [HERE/'release'])
    projection = json.loads(raw(projection_path))
    import importlib.util
    spec=importlib.util.spec_from_file_location('pack_exact_research_deployment',HERE/'apply_accepted_delta.py')
    deployment=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(deployment)
    deployment.verify(projection_path,digest(raw(projection_path)),None)
    recovery = json.loads(raw(Path(projection['recovery_manifest']['path'])))
    assert candidate_hash(recovery) == projection['candidate_payload_sha256']
    assert projection['approved'] is False and projection['applied'] is False
    entry = raw(BASE/'config/local_workspace_entry.json')
    assert digest(entry) == projection['base_entry_sha256']
    entries = {'rollback/local_workspace_entry.json':entry, 'deployment-projection.json':raw(projection_path)}
    for row in projection['changes']:
        # The existing exact deployment verifier above owns the target whitelist.
        pending = raw(Path(row['payload']))
        assert digest(pending) == row['sha256']
        entries['pending/'+row['target']] = pending
        target = checked_path(str(BASE/row['target']), [BASE])
        if row['previous_sha256'] is not None:
            previous = raw(target)
            assert digest(previous) == row['previous_sha256']
            entries['rollback/'+row['target']] = previous
        else:
            assert not target.exists()
    index = dict(candidate_id=projection['candidate_id'],
        candidate_payload_sha256=projection['candidate_payload_sha256'],
        projection_sha256=digest(raw(projection_path)), files={name:digest(body) for name,body in entries.items()},
        contains_databases=False, contains_credentials=False, contains_environment_or_browser_data=False,
        approved=False, applied=False, schema_extension_requires_compatible_rollback=True,
        rollback_is_code_reference_not_permission_to_drop_schema_or_overwrite_business=True,
        tool_sha256=digest(raw(Path(__file__))))
    entries['archive-index.json'] = (json.dumps(index, indent=2, ensure_ascii=True)+'\n').encode()
    destination = projection_path.parent/'changed-files-and-rollback.zip'
    if destination.exists():
        raise ValueError('ARCHIVE_ALREADY_EXISTS_NO_DUPLICATE')
    with ZipFile(destination, 'x', compression=ZIP_DEFLATED) as archive:
        for name, body in sorted(entries.items()):
            info = ZipInfo(name, (2026,10,16,0,0,0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, body)
    with ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == set(entries)
        for name, body in entries.items():
            assert archive.read(name) == body
    result = dict(path=str(destination), sha256=digest(raw(destination)), bytes=destination.stat().st_size,
        file_count=len(entries), roundtrip_in_memory_verified=True,
        cloud_uploaded=False, cloud_redownload_verified=False, production_writes=0)
    with (projection_path.parent/'delta-archive-receipt.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
