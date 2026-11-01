import pytest
from method_snapshot import calculation_scope, source_reader, SourceSnapshotChanged


def test_consumer_dependencies_exclude_prior_consumer_but_include_cached_method(tmp_path):
    from method_snapshot import checked, source_usage, observed_source_paths
    for name in ('a.txt', 'b.txt', 'method.txt'):
        (tmp_path/name).write_bytes(name.encode())
    read = source_reader(lambda relative, digest, root: (root/relative).read_bytes())
    calls = []
    def method():
        calls.append('method')
        return read('method.txt', 'TEST_ONLY', tmp_path)
    with calculation_scope():
        with source_usage():
            read('a.txt', 'TEST_ONLY', tmp_path)
            checked(('TEST_ONLY_METHOD',), method)
            assert set(observed_source_paths()) == {tmp_path/'a.txt', tmp_path/'method.txt'}
        with source_usage():
            read('b.txt', 'TEST_ONLY', tmp_path)
            checked(('TEST_ONLY_METHOD',), method)
            assert set(observed_source_paths()) == {tmp_path/'b.txt', tmp_path/'method.txt'}
        assert calls == ['method']
    assert len(calls) == 2  # Scope exit still invokes the original method validator.


def test_other_consumer_changed_bytes_still_discards_whole_batch(tmp_path):
    from method_snapshot import source_usage, observed_source_paths
    a, b = tmp_path/'a.txt', tmp_path/'b.txt'
    a.write_bytes(b'aaaa')
    b.write_bytes(b'bbbb')
    read = source_reader(lambda relative, digest, root: (root/relative).read_bytes())
    with pytest.raises(SourceSnapshotChanged):
        with calculation_scope():
            with source_usage():
                read('a.txt', 'TEST_ONLY', tmp_path)
            with source_usage():
                read('b.txt', 'TEST_ONLY', tmp_path)
                assert set(observed_source_paths()) == {b}
            a.write_bytes(b'AAAA')


def test_source_bytes_shared_only_inside_bounded_scope(tmp_path):
    calls = []
    path = tmp_path/'source.txt'
    path.write_bytes(b'abcd')
    def original(relative, digest, root):
        calls.append(relative)
        return (root/relative).read_bytes()
    read = source_reader(original)
    assert source_reader(read) is read
    with calculation_scope():
        for _ in range(16):
            assert read('source.txt', 'test', tmp_path) == b'abcd'
        assert len(calls) == 1
    assert len(calls) == 2
    read('source.txt', 'test', tmp_path)
    assert len(calls) == 3


def test_source_changed_during_preparation_discards_batch(tmp_path):
    path = tmp_path/'source.txt'
    path.write_bytes(b'abcd')
    read = source_reader(lambda relative, digest, root: (root/relative).read_bytes())
    with pytest.raises(SourceSnapshotChanged):
        with calculation_scope():
            assert read('source.txt', 'test', tmp_path) == b'abcd'
            path.write_bytes(b'efgh')
    assert read('source.txt', 'test', tmp_path) == b'efgh'


def test_real_source_hash_and_expiry_are_not_cached_as_approval(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, UTC
    from hashlib import sha256
    from kquant import options_opening_trend_reference as reference
    path = tmp_path/'source.txt'
    path.write_bytes(b'test-only-source')
    now = datetime(2026, 10, 22, 13, 30, tzinfo=UTC)
    proof = dict(status='APPROVED', reviewer='TEST_ONLY_REVIEWER',
        reviewed_at=(now-timedelta(seconds=1)).isoformat(),
        valid_until=(now+timedelta(seconds=1)).isoformat(),
        source_url='https://open.longbridge.com/docs/quote/overview',
        source_path='source.txt', source_sha256=sha256(path.read_bytes()).hexdigest(),
        excerpt='test-only-source')
    monkeypatch.setattr(reference, '_reviewed_file', source_reader(reference._reviewed_file))
    with calculation_scope():
        assert reference.source_review(proof, root=tmp_path, now=now) == proof
        assert reference.source_review(proof, root=tmp_path,
                                       now=now+timedelta(seconds=1)) is None
    with pytest.raises(ValueError):
        with calculation_scope():
            assert reference.source_review(proof, root=tmp_path, now=now) == proof
            path.write_bytes(b'TEST-ONLY-SOURCE')
