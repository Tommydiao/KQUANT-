import importlib.util
from pathlib import Path
import json
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('health_cli',ROOT/'scripts/run_hybrid_health.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_evidence_refuses_outside_location(tmp_path):
    with pytest.raises(ValueError,match='Independent'):
        module.save_probe_evidence(tmp_path/'outside.json',{})


def test_evidence_no_overwrite(monkeypatch,tmp_path):
    monkeypatch.setattr(module,'ROOT',tmp_path)
    # Hash actual implementation files without changing the shared workspace.
    for name in ('health_contract','health_journal','local_health_probe','loopback_transport','model_health'):
        p=tmp_path/'kquant_crypto'/f'hybrid_{name}.py'
        p.parent.mkdir(exist_ok=True)
        p.write_text('# fixture',encoding='utf-8')
    script=tmp_path/'run.py'
    script.write_text('# fixture',encoding='utf-8')
    monkeypatch.setattr(module,'__file__',str(script))
    target='outputs/hybrid_delivery/test.json'
    module.save_probe_evidence(target,{'http_status':200})
    data=json.loads((tmp_path/target).read_text())
    assert len(data['source_hashes'])==6
    assert not data['live_enabled']
    before=(tmp_path/target).read_bytes()
    with pytest.raises(FileExistsError):
        module.save_probe_evidence(target,{'http_status':500})
    assert (tmp_path/target).read_bytes()==before
