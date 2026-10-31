import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('local_entry', Path(__file__).with_name('prepare_local_entry.py'))
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(entry, 'ROOT', tmp_path)
    monkeypatch.setattr(entry, 'CODE', tmp_path / 'code')
    (entry.CODE / 'config/review_acceptances').mkdir(parents=True)
    return tmp_path


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def test_external_producer_same_size_change_changes_identity(local):
    folder = local / 'source'
    folder.mkdir()
    for name in entry.EXTERNAL_PRODUCTION_TOOLS:
        (folder / name).write_bytes(b'original')
    before = [entry.proof(path) for path in entry.external_production_tools()]
    (folder / 'integrate_recaptured_assets.py').write_bytes(b'modified')
    after = [entry.proof(path) for path in entry.external_production_tools()]
    assert entry.canonical_hash({'source': before}) != entry.canonical_hash({'source': after})
    assert not any(path.name.startswith('test_') for path in entry.external_production_tools())
    (folder / 'run_quote_facts.py').unlink()
    with pytest.raises(ValueError, match='EXTERNAL_PRODUCTION_TOOL_MISSING'):
        entry.external_production_tools()


def test_nested_contract_and_proof(local):
    fact = entry.CODE / 'outputs/fact.txt'
    fact.parent.mkdir()
    fact.write_text('original', encoding='utf-8')
    config = entry.CODE / 'config/review_acceptances/facts.json'
    write(config, {'nested': [{'source_path': 'outputs/fact.txt', 'source_sha256': entry.proof(fact)['sha256']}]})
    assert config in entry.configuration_files()
    assert entry.source_proofs(entry.configuration_files()) == [entry.proof(fact)]
    fact.write_text('modified', encoding='utf-8')
    with pytest.raises(ValueError, match='HASH_MISMATCH'):
        entry.source_proofs([config])


@pytest.mark.parametrize('path', ['../outside', 'F:/broken/file', 'outputs/../../escape', 'C:\\secret'])
def test_unsafe_source_rejected_before_read(local, path):
    config = entry.CODE / 'config/facts.json'
    write(config, {'source_path': path, 'source_sha256': '0' * 64})
    with pytest.raises(ValueError):
        entry.source_proofs([config])


def old_entry(local, accepted=False):
    recovery = local / 'runtime/recovery.json'
    write(recovery, {'final_runtime_accepted': accepted})
    path = entry.CODE / 'config/local_workspace_entry.json'
    write(path, {'production_accepted': False, 'recovery_manifest': entry.proof(recovery)})
    return path


def test_selection_requires_exact_old_hash_and_retains_history(local):
    path = old_entry(local)
    original = entry.proof(path)
    new = {'production_accepted': False, 'candidate_id': 'next'}
    with pytest.raises(ValueError, match='COMPARE_AND_SWAP'):
        entry.select_entry(path, new)
    assert entry.proof(path) == original
    entry.select_entry(path, new, original['sha256'])
    assert json.loads(path.read_text()) == new
    assert (local / 'runtime/releases/entry-history' / (original['sha256'] + '.json')).exists()
    assert not path.with_suffix('.lock').exists()
    assert entry.select_entry(path, new) == entry.proof(path)


def test_accepted_recovery_cannot_be_replaced(local):
    path = old_entry(local, accepted=True)
    original = entry.proof(path)
    with pytest.raises(ValueError, match='RELEASE_WORKFLOW'):
        entry.select_entry(path, {'candidate_id': 'new'}, original['sha256'])
    assert entry.proof(path) == original


def test_missing_proof_fails(local):
    config = entry.CODE / 'config/facts.json'
    write(config, {'source_path': 'outputs/missing', 'source_sha256': '0' * 64})
    with pytest.raises(FileNotFoundError):
        entry.source_proofs([config])


def test_missing_proof_retains_each_consumer_and_escaped_pointer(local):
    first = entry.CODE / 'config/first.json'
    second = entry.CODE / 'config/second.json'
    fact = {'source_path': 'outputs/missing', 'source_sha256': 'a' * 64}
    write(first, {'asset/~': [fact]})
    write(second, {'depth': fact})
    facts, issues = entry.source_inventory([first, second])
    assert facts == []
    assert len(issues) == 2
    assert issues[0]['json_pointer'] == '/asset~1~0/0'
    assert issues[1]['json_pointer'] == '/depth'
    assert issues[0]['config_path'] != issues[1]['config_path']
    assert all(row['expected_sha256'] == 'a' * 64 for row in issues)
    assert all(row['code'] == 'FileNotFoundError' for row in issues)


def test_declared_asset_unavailable_is_retained_but_never_a_verified_proof(local):
    config = entry.CODE / 'config/review_acceptances/options_opening_trend_reference_sources.json'
    fact = {'source_path': 'outputs/missing', 'source_sha256': 'a' * 64,
            'status': 'UNAVAILABLE', 'underlying': 'TEST', 'unavailable_reason': 'SOURCE_ORIGINAL_MISSING'}
    write(config, {'instrument_facts': {'TEST': fact}})
    facts, issues = entry.source_inventory([config])
    assert facts == [] and len(issues) == 1
    assert issues[0]['code'] == 'DECLARED_ASSET_UNAVAILABLE'
    assert entry.source_proofs([config]) == []
    from datetime import datetime, timezone
    from kquant.options_opening_trend_reference import source_review
    assert source_review(fact, root=entry.CODE, now=datetime.now(timezone.utc)) is None
    write(config, {'shared_interface': fact})
    with pytest.raises(ValueError, match='UNAVAILABLE_DECLARATION_INVALID'):
        entry.source_proofs([config])
    write(config, {'instrument_facts': {'WRONG': fact}})
    with pytest.raises(ValueError, match='UNAVAILABLE_DECLARATION_INVALID'):
        entry.source_proofs([config])
    write(config, {'instrument_facts': {'TEST': {**fact, 'status': 'APPROVED'}}})
    with pytest.raises(FileNotFoundError):
        entry.source_proofs([config])


def test_tampered_recovery_refuses_selection(local):
    path = old_entry(local)
    original = entry.proof(path)
    write(local / 'runtime/recovery.json', {'final_runtime_accepted': False, 'changed': True})
    with pytest.raises(ValueError, match='OLD_RECOVERY_HASH_MISMATCH'):
        entry.select_entry(path, {'candidate_id': 'new'}, original['sha256'])


def test_both_frontend_builds_are_required_and_hash_bound(local):
    unified = entry.CODE / 'web/dist-unified/unified.html'
    stock = entry.CODE / 'web/dist-stock/index.html'
    write(unified, 'unified')
    with pytest.raises(ValueError, match='BUILT_FRONTEND_REQUIRED:dist-stock'):
        entry.built_frontends()
    write(stock, 'stock1')
    before = entry.built_frontends()
    write(stock, 'stock2')
    after = entry.built_frontends()
    assert before['dist-unified'] == after['dist-unified']
    assert before['dist-stock'] != after['dist-stock']
