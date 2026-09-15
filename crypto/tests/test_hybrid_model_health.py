import json
import pytest
from kquant_crypto.hybrid_model_health import inspect_model_metadata


@pytest.mark.parametrize('enabled,state',[(False,'WAITING'),(True,'FAILED'),(0,'FAILED'),(None,'FAILED')])
def test_permission_metadata_is_not_model_quality(tmp_path,enabled,state):
    p=tmp_path/'artifact.json'
    p.write_text(json.dumps({'scope':'DEV_ONLY','admission':'ABSTAIN','runtime_enabled':enabled,'secret':'DO_NOT_COPY'}))
    report=inspect_model_metadata(p)
    assert report['state']==state
    assert not report['model_loaded'] and not report['execution_authorized']
    assert 'DO_NOT_COPY' not in json.dumps(report)


def test_missing_metadata_remains_unknown(tmp_path):
    assert inspect_model_metadata(tmp_path/'absent')['state']=='UNKNOWN'
