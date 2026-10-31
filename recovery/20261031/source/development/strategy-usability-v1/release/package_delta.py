"""Package only proposed files and their verified rollback bytes; never apply."""
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
import sys

DEV = Path(__file__).resolve().parents[1]
BASE = DEV.parent / 'workspace'


def package(projection):
    projection = projection.resolve()
    if not projection.is_relative_to(DEV / 'release'):
        raise ValueError('PROJECTION_OUTSIDE_RELEASE_DIRECTORY')
    bundle = json.loads(projection.read_text())
    entry = BASE / 'config/local_workspace_entry.json'
    if sha256(entry.read_bytes()).hexdigest() != bundle['base_entry_sha256']:
        raise ValueError('BASE_ENTRY_CHANGED')
    archive = projection.parent / 'changed-files-and-rollback.zip'
    contents = {'metadata/deployment-projection.json': projection.read_bytes(),
                'rollback/config/local_workspace_entry.json': entry.read_bytes()}
    absent = []
    for row in bundle['changes']:
        target = (BASE / row['target']).resolve()
        payload = Path(row['payload']).resolve()
        if not target.is_relative_to(BASE) or not payload.is_relative_to(DEV):
            raise ValueError('DELTA_PATH_OUTSIDE_BOUNDARY')
        raw = payload.read_bytes()
        if sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('PAYLOAD_CHANGED')
        contents['payload/' + row['target']] = raw
        if row['previous_sha256'] is None:
            if target.exists():
                raise ValueError('UNEXPECTED_TARGET_EXISTS')
            absent.append(row['target'])
        else:
            old = target.read_bytes()
            if sha256(old).hexdigest() != row['previous_sha256']:
                raise ValueError('ROLLBACK_BASE_CHANGED')
            contents['rollback/' + row['target']] = old
    for relative in bundle['retired_build_assets']:
        target = (BASE / relative).resolve()
        if not target.is_relative_to(BASE / 'web'):
            raise ValueError('RETIRED_ASSET_OUTSIDE_WEB')
        contents['rollback/' + relative] = target.read_bytes()
    inventory = {name: sha256(raw).hexdigest() for name, raw in sorted(contents.items())}
    contents['metadata/archive-inventory.json'] = json.dumps({
        'files': inventory, 'originally_absent': absent, 'database_files': 0,
        'credentials_included': False, 'applied': False}, indent=2).encode()
    if archive.exists():
        with ZipFile(archive) as existing:
            if set(existing.namelist()) != set(contents) or any(existing.read(k) != v for k, v in contents.items()):
                raise ValueError('EXISTING_ARCHIVE_DIFFERS')
    else:
        with ZipFile(archive, 'x', compression=ZIP_DEFLATED) as zipped:
            for name, raw in sorted(contents.items()):
                info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                zipped.writestr(info, raw)
    with ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        assert all(sha256(zipped.read(k)).hexdigest() == h for k, h in inventory.items())
    return {'path': str(archive), 'sha256': sha256(archive.read_bytes()).hexdigest(),
            'bytes': archive.stat().st_size, 'files': len(contents), 'applied': False,
            'verification': 'ALL_ARCHIVE_MEMBERS_READ_AND_HASHED_NOT_DEPLOYMENT_RESTORE'}


if __name__ == '__main__':
    print(json.dumps(package(Path(sys.argv[1]))))
