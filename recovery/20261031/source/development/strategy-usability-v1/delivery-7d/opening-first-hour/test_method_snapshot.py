import pytest
from method_snapshot import calculation_scope, checked, SourceSnapshotChanged


def test_one_calculation_revalidates_and_does_not_share_results():
    calls = []
    def validate():
        calls.append(1)
        return {'approved': ['TEST_ONLY']}
    with calculation_scope():
        for _ in range(55):
            value = checked('method', validate)
            value['approved'].clear()
        assert len(calls) == 1
    assert len(calls) == 2
    with calculation_scope():
        assert checked('method', validate) == {'approved': ['TEST_ONLY']}
    assert len(calls) == 4


def test_changed_same_size_bytes_discard_result(tmp_path):
    from hashlib import sha256
    path = tmp_path/'TEST_ONLY.txt'
    path.write_text('aaaa')
    expected = sha256(path.read_bytes()).hexdigest()
    def validate():
        return {'hash': expected} if sha256(path.read_bytes()).hexdigest() == expected else None
    with pytest.raises(SourceSnapshotChanged):
        with calculation_scope():
            assert checked('method', validate)
            path.write_text('bbbb')
    assert checked('method', validate) is None


def test_scope_does_not_leak_after_failure():
    with pytest.raises(RuntimeError):
        with calculation_scope():
            checked('method', lambda: 'old')
            raise RuntimeError('TEST_ONLY')
    assert checked('method', lambda: 'new') == 'new'


def test_path_resolution_shared_only_inside_scope_and_rechecked(tmp_path, monkeypatch):
    from pathlib import Path
    from method_snapshot import resolve_path
    path = tmp_path/'TEST_ONLY.txt'
    path.write_bytes(b'AAAA')
    original = Path.resolve
    calls = []
    def resolve(value, *args, **kwargs):
        calls.append(str(value))
        return original(value, *args, **kwargs)
    monkeypatch.setattr(Path, 'resolve', resolve)
    with calculation_scope():
        for _ in range(55):
            assert resolve_path(path) == path
        assert len(calls) == 1
    assert len(calls) == 2
    resolve_path(path)
    assert len(calls) == 3


def test_retargeted_path_rejects_scope_without_reusing_old_resolution(tmp_path, monkeypatch):
    from pathlib import Path
    from method_snapshot import resolve_path
    first, other = tmp_path/'first', tmp_path/'other'
    target = [first]
    monkeypatch.setattr(Path, 'resolve', lambda *a, **kw: target[0])
    with pytest.raises(SourceSnapshotChanged):
        with calculation_scope():
            assert resolve_path(first) == first
            target[0] = other
            assert resolve_path(first) == first
    assert resolve_path(first) == other


def test_cached_resolution_never_caches_file_bytes(tmp_path):
    from prepared_generation import source_files
    path = tmp_path/'TEST_ONLY.txt'
    path.write_bytes(b'AAAA')
    with calculation_scope():
        before = source_files(tmp_path, {'source_path':path.name})
        path.write_bytes(b'BBBB')
        after = source_files(tmp_path, {'source_path':path.name})
        assert before != after
