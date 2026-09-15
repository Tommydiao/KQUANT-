"""M1 executable specifications only; not connected to any runtime or writer."""

from dataclasses import dataclass, fields
import math


def _finite(value: float) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


@dataclass(frozen=True)
class DecisionTimeline:
    """UTC epoch seconds. Strict post-commit events, inclusive expiry boundary."""

    signal_time: float
    received_at: float
    feature_snapshot_frozen_at: float
    evaluation_started_at: float
    evaluation_finished_at: float
    decision_committed_at: float
    earliest_fill_at: float
    signal_expires_at: float

    def __post_init__(self):
        values = [getattr(self, f.name) for f in fields(self)]
        if not all(_finite(v) and v >= 0 for v in values):
            raise ValueError('Non-finite or negative UTC timestamp')
        if values != sorted(values) or self.earliest_fill_at >= self.signal_expires_at:
            raise ValueError('Invalid decision chronology or no remaining fill window')

    def validate_inputs(self, *, feature_available_at, model_available_at):
        if not _finite(model_available_at) or not 0 <= model_available_at <= self.evaluation_started_at:
            raise ValueError('Model not available when evaluation began')
        for value in feature_available_at:
            if not _finite(value) or not 0 <= value <= self.feature_snapshot_frozen_at:
                raise ValueError('Feature unavailable at snapshot freeze')

    def permits_fill(self, event_at: float, received_at: float) -> bool:
        # Timing is necessary, never sufficient: the writer must still check
        # source, BBO, size, expiry, portfolio version and original hard risk.
        return (
            _finite(event_at) and _finite(received_at)
            and self.earliest_fill_at < event_at <= received_at <= self.signal_expires_at
        )


@dataclass(frozen=True)
class RiskLines:
    """Distinct equity references; no portfolio sizing or MC probability here."""

    day_start_equity: float
    current_liquidation_equity: float
    historical_high_watermark: float
    daily_loss_limit: float

    def __post_init__(self):
        values = (self.day_start_equity, self.current_liquidation_equity, self.historical_high_watermark)
        if not all(_finite(v) and v > 0 for v in values):
            raise ValueError('Risk baseline unavailable')
        if not _finite(self.daily_loss_limit) or not 0 < self.daily_loss_limit < 1:
            raise ValueError('Invalid daily loss limit')
        if self.historical_high_watermark < self.current_liquidation_equity:
            raise ValueError('High watermark is inconsistent with current equity')

    @property
    def daily_loss_line(self):
        return self.day_start_equity * (1 - self.daily_loss_limit)

    @property
    def remaining_daily_loss_budget(self):
        return max(0, self.current_liquidation_equity - self.daily_loss_line)

    def daily_breached(self, equity):
        self._validate_mark(equity)
        return equity <= self.daily_loss_line

    @staticmethod
    def _validate_mark(equity):
        if not _finite(equity) or equity < 0:
            raise ValueError('Unknown liquidation mark')

    def incremental_drawdown(self, equity, path_peak=None):
        self._validate_mark(equity)
        peak = self.current_liquidation_equity if path_peak is None else path_peak
        self._validate_mark(peak)
        return max(0, 1 - equity / max(self.current_liquidation_equity, peak, equity))

    def hwm_drawdown(self, equity, path_peak=None):
        self._validate_mark(equity)
        peak = self.historical_high_watermark if path_peak is None else path_peak
        self._validate_mark(peak)
        return max(0, 1 - equity / max(self.historical_high_watermark, peak, equity))
