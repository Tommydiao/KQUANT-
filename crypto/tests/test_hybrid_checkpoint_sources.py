from scripts.verify_hybrid_delivery_checkpoint import source_manifest
import pytest


@pytest.mark.parametrize('extension', ['ps1', 'PS1', 'cmd', 'bat', 'sh'])
def test_shell_entrypoints_are_versioned(tmp_path, extension):
    script = tmp_path / 'scripts' / ('inspect.' + extension)
    script.parent.mkdir()
    script.write_text('version1', encoding='utf-8')
    before = source_manifest(tmp_path)
    assert str(script.relative_to(tmp_path)) in before
    script.write_text('version2', encoding='utf-8')
    assert source_manifest(tmp_path) != before


def test_manifest_covers_candidate_dependencies_and_membership_changes(tmp_path):
    source = tmp_path / 'kquant_crypto' / 'candidate.py'
    source.parent.mkdir()
    source.write_text('VERSION = 1', encoding='utf-8')
    before = source_manifest(tmp_path)
    assert str(source.relative_to(tmp_path)) in before
    source.write_text('VERSION = 2', encoding='utf-8')
    assert source_manifest(tmp_path) != before
    before = source_manifest(tmp_path)
    config = tmp_path / 'config' / 'policy.json'
    config.parent.mkdir()
    config.write_text('{}', encoding='utf-8')
    assert source_manifest(tmp_path) != before
    before = source_manifest(tmp_path)
    source.unlink()
    assert source_manifest(tmp_path) != before


def test_manifest_excludes_runtime_data_and_credentials(tmp_path):
    (tmp_path / '.env').write_text('SECRET=not-a-real-key', encoding='utf-8')
    work = tmp_path / 'work'
    work.mkdir()
    (work / 'state.json').write_text('{}', encoding='utf-8')
    assert source_manifest(tmp_path) == {}
