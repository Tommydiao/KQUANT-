"""Offline archive integrity check; never extracts or executes archived code."""
import argparse
import hashlib
import json
from pathlib import PurePosixPath
import zipfile


def verify(path):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [i.filename for i in entries]
        if len(names) != len(set(names)) or any(
                PurePosixPath(n).is_absolute() or '..' in PurePosixPath(n).parts or '\\' in n or ':' in n
                for n in names):
            raise ValueError('Unsafe or duplicate archive member')
        if sum(i.file_size for i in entries) > 1024 ** 3:
            raise ValueError('Review archive exceeds one GiB uncompressed limit')
        if archive.getinfo('MANIFEST.json').file_size > 2 ** 20:
            raise ValueError('Oversized manifest')
        manifest = json.loads(archive.read('MANIFEST.json'))
        if manifest['scope'] != 'DEV_ONLY_REVIEW' or manifest['deployable'] is not False:
            raise ValueError('Unexpected deployment scope')
        if set(names) != {'MANIFEST.json', *manifest['files']}:
            raise ValueError('Manifest membership mismatch')
        for name, expected in manifest['files'].items():
            digest = hashlib.sha256()
            with archive.open(name) as stream:
                for chunk in iter(lambda: stream.read(1024 ** 2), b''):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise ValueError('Evidence hash mismatch: ' + name)
        return {'integrity': 'PASS', 'files': len(manifest['files']),
                'scope': manifest['scope'], 'deployable': False,
                'performance': manifest['performance'],
                'limits': 'Internal integrity only; not provenance authentication or model validation'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive')
    print(json.dumps(verify(parser.parse_args().archive)))
