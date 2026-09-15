import json
from pathlib import Path

from kquant_crypto.hybrid_failure_frames import failure_frames


def test_no_message_or_locals():
    secret = 'never-export-this-secret'
    try:
        raise ValueError(secret)
    except ValueError as exc:
        result = failure_frames(exc, Path(__file__).resolve().parents[1])
    assert secret not in json.dumps(result)
    assert result['frames'][-1]['file'] == 'tests/test_hybrid_failure_frames.py'
    assert result['locals_included'] is False
    assert result['cause_proven'] is False


def test_external_paths_are_hidden(tmp_path):
    try:
        raise ValueError('hidden')
    except ValueError as exc:
        result = failure_frames(exc, tmp_path)
    assert result['frames'] == [{'file': '<external>', 'line': result['frames'][0]['line'],
                                 'function': '<external>'}]


def test_bounded_frames():
    def recurse(n):
        if n:
            return recurse(n - 1)
        raise ValueError('failure')
    try:
        recurse(30)
    except ValueError as exc:
        result = failure_frames(exc, Path(__file__).resolve().parents[1])
    assert len(result['frames']) == 16
    assert result['truncated'] is True
