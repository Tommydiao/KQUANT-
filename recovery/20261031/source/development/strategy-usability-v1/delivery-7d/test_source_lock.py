from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from time import monotonic

import pytest

from kquant.options_source_updates import config_lock, merge_facts


@pytest.mark.parametrize('round_number', range(5))
def test_real_concurrent_first_open_and_updates_preserve_method(tmp_path, round_number):
    path = tmp_path/f'TEST_ONLY-{round_number}.json'
    method = {'status': 'ACCEPTED', 'proof': 'TEST_ONLY_NOT_OWNER'}
    path.write_text(json.dumps({'canonical_resolution_method': method}))
    with ThreadPoolExecutor(max_workers=8) as workers:
        list(workers.map(lambda n: merge_facts(path, [(('instrument_facts',str(n)),
            {'source_sha256':str(n)})]), range(40)))
    result = json.loads(path.read_text())
    assert len(result['instrument_facts']) == 40
    assert result['canonical_resolution_method'] == method
    assert Path(str(path)+'.source-update.lock').read_bytes() == b'0'


def test_empty_existing_lock_initializes_only_under_lock(tmp_path):
    path = tmp_path/'TEST_ONLY.json'
    lock = Path(str(path)+'.source-update.lock')
    lock.write_bytes(b'')
    with config_lock(path):
        assert lock.stat().st_size == 1
    with config_lock(path):
        pass
    assert lock.read_bytes() == b'0'


def test_permission_denial_is_not_swallowed_or_retried(tmp_path, monkeypatch):
    path = tmp_path/'TEST_ONLY.json'
    calls = []
    def denied(*args, **kwargs):
        calls.append(1)
        raise PermissionError('TEST_ONLY ACL denial')
    monkeypatch.setattr(Path, 'open', denied)
    with pytest.raises(PermissionError):
        with config_lock(path):
            pytest.fail('lock not acquired')
    assert len(calls) == 1


def test_contended_lock_obeys_bound_and_recovers(tmp_path):
    path = tmp_path/'TEST_ONLY.json'
    with config_lock(path):
        started = monotonic()
        with pytest.raises(TimeoutError, match='SOURCE_CONFIG_UPDATE_BUSY'):
            with config_lock(path, timeout=.05):
                pytest.fail('not exclusive')
        assert monotonic()-started < .5
    with config_lock(path, timeout=.05):
        pass
