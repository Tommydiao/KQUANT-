import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest


def setup_module_under_test():
    path = Path(__file__).parents[1] / 'scripts/configure_local_access.py'
    spec = importlib.util.spec_from_file_location('isolated_access_setup', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_dpapi_roundtrip_and_no_plaintext_file(tmp_path, monkeypatch):
    helper = setup_module_under_test()
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    payload = {'LONGBRIDGE_APP_KEY': 'TEST_ONLY-secret-not-real'}
    path = helper.save('market', payload)
    raw = path.read_bytes()
    assert b'TEST_ONLY' not in raw
    code = '''$s=ConvertTo-SecureString ([Console]::In.ReadToEnd());
$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);
try {[Console]::Out.Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($p))}
finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p)}'''
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code],
        input=raw, capture_output=True, timeout=10, env={k: v for k, v in os.environ.items() if k.upper() != 'PSMODULEPATH'})
    assert result.returncode == 0
    assert json.loads(result.stdout) == payload
    with pytest.raises(ValueError, match='CONFIG_EXISTS'):
        helper.save('market', payload)
    assert path.read_bytes() == raw


def test_encrypt_failure_does_not_create_config(tmp_path, monkeypatch):
    helper = setup_module_under_test()
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    def failed(payload):
        raise ValueError('DPAPI_PROTECTION_FAILED_NO_CONFIG_WRITTEN')
    monkeypatch.setattr(helper, 'protect', failed)
    with pytest.raises(ValueError, match='DPAPI_PROTECTION_FAILED'):
        helper.save('login', {'TEST_ONLY': True})
    assert not (tmp_path / 'KQUANT').exists()
