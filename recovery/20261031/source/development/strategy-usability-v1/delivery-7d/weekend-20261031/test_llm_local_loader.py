"""Local loader regression: no real key, network or business store access."""
from types import SimpleNamespace
from unittest.mock import patch
from bootstrap import activate
activate()
from kquant import options_llm_credentials as credentials
from run_real_capability import failed_remote_probe


def test_windows_loader_drops_only_inherited_module_path(tmp_path):
    path=tmp_path/'TEST_ONLY.dpapi'
    path.write_text('TEST_ONLY_NOT_ENCRYPTED')
    with patch.object(credentials,'credential_path',return_value=path), \
            patch.dict(credentials.os.environ,{'PSModulePath':'TEST_ONLY_wrong_host','KEEP_ME':'yes'}), \
            patch.object(credentials.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='TEST_ONLY_KEY')) as run:
        assert credentials.api_key()=='TEST_ONLY_KEY'
    kwargs=run.call_args.kwargs
    assert not any(k.upper()=='PSMODULEPATH' for k in kwargs['env'])
    assert kwargs['env']['KEEP_ME']=='yes'
    assert kwargs['timeout']==10
    assert run.call_args.args[0][0]=='powershell.exe'


def test_remote_failures_not_retried_for_unchanged_key():
    for state in ('NOT_ACCESSIBLE','PROBE_FAILED','AUTHORIZATION_REQUIRED','UNKNOWN'):
        assert failed_remote_probe({'state':state,'credential_version':'v1'},'v1')
        assert not failed_remote_probe({'state':state,'credential_version':'v1'},'v2')
    for state in ('MISSING_LOCAL_KEY','ACCESSIBLE'):
        assert not failed_remote_probe({'state':state,'credential_version':'v1'},'v1')
