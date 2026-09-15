"""Research-only path adapter retaining pending orders but no new signals."""
from .hybrid_research_portfolio import ResearchPortfolio


class ExistingExposurePortfolio(ResearchPortfolio):
    def _reserve(self, symbol, signal, time):
        self.event('MC_NEW_SIGNAL_SUPPRESSED', time, symbol)

    def on_path_batch(self, bars, hourly, now):
        # allow_entries=False cancels pre-existing pending in the legacy engine.
        # Suppress only new reservations, leaving all original protection intact.
        super().on_closed_batch(bars, hourly, now, allow_entries=True)


def drawdowns(value, starting_peak, historical_peak):
    if min(value, starting_peak, historical_peak) <= 0:
        raise ValueError('Positive NAV and peaks required')
    starting_peak = max(starting_peak, value)
    historical_peak = max(historical_peak, value)
    return dict(starting_peak=starting_peak, historical_peak=historical_peak,
                incremental=(starting_peak-value)/starting_peak,
                historical=(historical_peak-value)/historical_peak)
