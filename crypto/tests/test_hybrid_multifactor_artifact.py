import hashlib
import json
import pytest
from kquant_crypto.hybrid_multifactor_artifact import inspect_artifact


def test_development_only_integrity(tmp_path):
    data = b'research'
    (tmp_path/'posterior.nc').write_bytes(data)
    (tmp_path/'artifact.json').write_text(json.dumps({
        'scope':'DEV_ONLY','runtime_enabled':False,'exposure':'EXPOSED_RESEARCH',
        'posterior_sha256':hashlib.sha256(data).hexdigest()}))
    assert inspect_artifact(tmp_path,purpose='DEV_ONLY')['runtime_enabled'] is False
    for purpose in ['LIVE','PAPER','SHADOW','EVAL','SIZING']:
        with pytest.raises(ValueError):
            inspect_artifact(tmp_path,purpose=purpose)
    (tmp_path/'posterior.nc').write_bytes(b'changed')
    with pytest.raises(ValueError):
        inspect_artifact(tmp_path,purpose='DEV_ONLY')
