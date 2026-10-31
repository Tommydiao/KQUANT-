"""Detect local wall-clock discontinuities without claiming external time sync."""
from time import monotonic


class ClockContinuity:
    def __init__(self, *, elapsed_clock=monotonic):
        self.elapsed_clock = elapsed_clock
        self.previous = None
        self.fault = None

    def sample(self, now):
        elapsed = self.elapsed_clock()
        if self.previous is not None:
            wall, monotone = self.previous
            difference = (now - wall).total_seconds() - (elapsed - monotone)
            # This is a process-health alarm, not a market timestamp tolerance.
            if abs(difference) > 1 and self.fault is None:
                self.fault = {"detected_at": now.isoformat(), "wall_jump_seconds": difference}
        self.previous = now, elapsed
        return {"state": "CLOCK_DISCONTINUITY" if self.fault else "CONTINUOUS_NOT_SYNC_VERIFIED",
                "absolute_sync_verified": False, "requires_restart": self.fault is not None,
                "checked_at": now.isoformat(), "fault": self.fault}
