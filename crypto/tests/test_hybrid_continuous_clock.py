import pytest
from kquant_crypto.hybrid_clock import ClockSegment, POLICY, digest
from kquant_crypto.hybrid_continuous_clock import renewal_due, validate_renewal


def segment(anchor=0, lower=1000, upper=1000.1):
    return ClockSegment(lower, upper, anchor, anchor + 10, 'probes', digest(POLICY))


def test_renewal_does_not_extend_clock_policy():
    old = segment()
    assert not renewal_due(old, 100)
    assert renewal_due(old, 180)
    assert renewal_due(segment(upper=1000.99), 1)
    new = segment(anchor=180, lower=1000.02, upper=1000.08)
    assert validate_renewal(old, new, 181, 191)['clock_segment_id'] == new.segment_id
    with pytest.raises(ValueError, match='conflict'):
        validate_renewal(old, segment(anchor=180, lower=1320, upper=1320.1), 181, 191)
    with pytest.raises(ValueError, match='expired'):
        validate_renewal(old, segment(anchor=601), 601, 611)
    with pytest.raises(ValueError, match='discontinuity'):
        renewal_due(old, -1)
