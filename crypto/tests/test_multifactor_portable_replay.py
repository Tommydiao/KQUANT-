import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest


def module():
    path = Path(__file__).resolve().parents[1]/'scripts/verify_multifactor_portable_replay_dev.py'
    spec = importlib.util.spec_from_file_location('portable_verifier', path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize('name', ['../escape.py', '/escape.py', 'C:/escape.py', 'x\\escape.py'])
def test_unsafe_member_rejected_before_extraction(tmp_path, name):
    archive = tmp_path/'bad.zip'
    payload = b'not executed'
    manifest = dict(scope='DEV_ONLY_DATASET_REPLAY', execution_enabled=False,
        files={name:hashlib.sha256(payload).hexdigest()})
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('REPLAY_MANIFEST.json', json.dumps(manifest))
        z.writestr(name, payload)
    out = tmp_path/'out'
    with pytest.raises(ValueError, match='Unsafe member'):
        module().verify(archive, hashlib.sha256(archive.read_bytes()).hexdigest(), out)
    assert not out.exists()


def test_hash_mismatch_prevents_execution(tmp_path):
    archive = tmp_path/'bad.zip'
    archive.write_bytes(b'invalid')
    with pytest.raises(ValueError, match='Archive identity'):
        module().verify(archive, 'wrong', tmp_path/'out')
    assert not (tmp_path/'out').exists()
