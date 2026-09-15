import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

SPEC = importlib.util.spec_from_file_location('review_verifier',
    Path(__file__).resolve().parents[1] / 'scripts/verify_multifactor_review_bundle.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make(tmp_path, *, name='evidence.json', data=b'{}', expected=b'{}', extra=False):
    path = tmp_path / 'review.zip'
    manifest = {'scope': 'DEV_ONLY_REVIEW', 'deployable': False, 'performance': 'PERFORMANCE_UNPROVEN',
                'files': {name: hashlib.sha256(expected).hexdigest()}}
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('MANIFEST.json', json.dumps(manifest))
        archive.writestr(name, data)
        if extra:
            archive.writestr('undeclared.txt', 'no')
    return path


def test_read_only_verification_does_not_extract(tmp_path):
    result = MODULE.verify(make(tmp_path))
    assert result['integrity'] == 'PASS'
    assert not result['deployable']
    assert not (tmp_path / 'evidence.json').exists()


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'C:/absolute', 'a\\b'])
def test_unsafe_names_rejected(tmp_path, name):
    with pytest.raises(ValueError):
        MODULE.verify(make(tmp_path, name=name))


def test_tamper_and_extra_members_rejected(tmp_path):
    with pytest.raises(ValueError):
        MODULE.verify(make(tmp_path, data=b'changed'))
    with pytest.raises(ValueError):
        MODULE.verify(make(tmp_path, extra=True))
