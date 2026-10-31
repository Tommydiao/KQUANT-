"""Original source bytes remain authoritative; no persistent validation cache."""
from hashlib import sha256
import os
from pathlib import Path

import pytest

from kquant.options_opening_trend_reference import _reviewed_file


def test_same_size_same_mtime_mutation_is_still_rejected(tmp_path):
    path = tmp_path / "source.txt"
    path.write_bytes(b"original")
    original = path.stat()
    digest = sha256(path.read_bytes()).hexdigest()
    assert _reviewed_file(path.name, digest, tmp_path) == b"original"
    path.write_bytes(b"modified")
    os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
    with pytest.raises(ValueError, match="SOURCE_ARCHIVE_CHANGED"):
        _reviewed_file(path.name, digest, tmp_path)


@pytest.mark.parametrize("size", [0, 2097153])
def test_empty_and_oversized_actual_content_are_invalid(tmp_path, size):
    path = tmp_path / "source.txt"
    path.write_bytes(b"x" * size)
    with pytest.raises(ValueError, match="SOURCE_ARCHIVE_INVALID"):
        _reviewed_file(path.name, sha256(path.read_bytes()).hexdigest(), tmp_path)


def test_maximum_size_and_directory_and_outside_root(tmp_path):
    raw = b"x" * 2097152
    source = tmp_path / "source.txt"
    source.write_bytes(raw)
    assert _reviewed_file(source.name, sha256(raw).hexdigest(), tmp_path) == raw
    with pytest.raises((OSError, ValueError)):
        _reviewed_file(".", sha256(raw).hexdigest(), tmp_path)
    with pytest.raises(ValueError, match="SOURCE_ARCHIVE_INVALID"):
        _reviewed_file("../outside.txt", sha256(raw).hexdigest(), tmp_path)


def test_root_resolution_is_reused_but_children_resolve_each_time(tmp_path, monkeypatch):
    raw = b"TEST_ONLY bytes must still be checked"
    (tmp_path / "source.txt").write_bytes(raw)
    original = Path.resolve
    resolutions = []

    def observed(path, *args, **kwargs):
        resolutions.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", observed)
    for _ in range(2):
        assert _reviewed_file("source.txt", sha256(raw).hexdigest(), tmp_path) == raw
    assert resolutions.count(tmp_path) == 1
    assert resolutions.count(tmp_path / "source.txt") == 2


def test_retargeted_root_alias_fails_closed(tmp_path):
    first, other = tmp_path / "first", tmp_path / "other"
    first.mkdir()
    other.mkdir()
    raw = b"TEST_ONLY same bytes do not authorize another source root"
    (first / "source.txt").write_bytes(raw)
    (other / "source.txt").write_bytes(raw)
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(first, target_is_directory=True)
    except OSError as exc:
        pytest.skip("Directory symlink permission unavailable: " + str(exc))
    assert _reviewed_file("source.txt", sha256(raw).hexdigest(), alias) == raw
    alias.unlink()
    alias.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match="SOURCE_ARCHIVE_INVALID"):
        _reviewed_file("source.txt", sha256(raw).hexdigest(), alias)


@pytest.mark.parametrize("size", [76, 65535, 65536, 65537, 2097152, 2097153])
def test_actual_reads_use_small_blocks_with_the_original_total_bound(tmp_path, monkeypatch, size):
    source = tmp_path / "source.txt"
    raw = b"x" * size
    source.write_bytes(raw)
    original = Path.open
    requests, received = [], []

    class ObservedRead:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, count):
            requests.append(count)
            value = self.stream.read(count)
            received.append(len(value))
            return value

    def observed(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        return ObservedRead(stream) if path == source and args == ("rb",) else stream

    monkeypatch.setattr(Path, "open", observed)
    if size > 2097152:
        with pytest.raises(ValueError, match="SOURCE_ARCHIVE_INVALID"):
            _reviewed_file(source.name, sha256(raw).hexdigest(), tmp_path)
    else:
        assert _reviewed_file(source.name, sha256(raw).hexdigest(), tmp_path) == raw
    assert max(requests) <= 65536
    assert sum(received) == min(size, 2097153)
