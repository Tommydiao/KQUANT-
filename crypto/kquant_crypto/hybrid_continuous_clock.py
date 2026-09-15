"""Clock renewal for the isolated public observer, never a source timestamp."""
import math
from .hybrid_clock import POLICY


def renewal_due(segment, monotonic_at):
    age = monotonic_at - segment.mono_anchor
    if not math.isfinite(age) or age < 0:
        raise ValueError('Monotonic clock discontinuity')
    width = segment.offset_upper - segment.offset_lower
    projected_width = width + 2 * (age + 90) * POLICY['drift_ppm'] / 1e6
    return age >= 180 or projected_width >= POLICY['max_interval_width_seconds']


def validate_renewal(old, new, monotonic_at, local_at):
    previous = old.bounds(monotonic_at, local_at)
    current = new.bounds(monotonic_at, local_at)
    if max(previous['received_at_lower'], current['received_at_lower']) > min(
            previous['received_at_upper'], current['received_at_upper']):
        raise ValueError('Renewed receiver intervals conflict; do not widen policy')
    return current
