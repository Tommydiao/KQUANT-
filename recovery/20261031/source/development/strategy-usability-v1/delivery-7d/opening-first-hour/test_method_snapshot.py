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
