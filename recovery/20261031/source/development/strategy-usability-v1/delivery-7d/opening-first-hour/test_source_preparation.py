import pytest
from method_snapshot import calculation_scope, source_reader, SourceSnapshotChanged


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
