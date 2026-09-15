"""Explicit DEV risk-event definitions, separate from financial admission."""
from dataclasses import asdict, dataclass
import math

from .candidate_policy import digest


@dataclass(frozen=True)
class RiskEvent:
    event_id: str
    metric: str
    threshold: float | None = None

    def __post_init__(self):
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError('Named event required')
        allowed = {'daily_loss_line_breached', 'incremental_peak_drawdown',
                   'absolute_high_watermark_drawdown', 'terminal_net_change'}
        if self.metric not in allowed:
            raise ValueError('Unregistered risk metric')
        if self.metric == 'daily_loss_line_breached':
            if self.threshold is not None:
                raise ValueError('Daily loss uses the original portfolio line')
        elif type(self.threshold) not in (int, float) or not math.isfinite(self.threshold):
            raise ValueError('Explicit finite DEV threshold required')
        elif self.metric.endswith('drawdown') and not 0 < self.threshold < 1:
            raise ValueError('Drawdown threshold is a positive fraction below one')
        elif self.metric == 'terminal_net_change' and self.threshold > 0:
            raise ValueError('Loss threshold cannot be a profit target')

    def classify(self, risk):
        value = risk[self.metric]
        if self.metric == 'daily_loss_line_breached':
            if type(value) is not bool:
                raise ValueError('Unknown daily event is not false')
            return value
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('Missing or invalid risk observation')
        if self.metric.endswith('drawdown') and not 0 <= value <= 1:
            raise ValueError('Invalid drawdown fraction')
        # Loss magnitude includes threshold equality; zero PnL is not a loss.
        if self.metric == 'terminal_net_change':
            return value < 0 if self.threshold == 0 else value <= self.threshold
        return value >= self.threshold


def freeze_events(events, *, policy_hash, costs, comparison_budget, input_exposure):
    if not events or len({e.event_id for e in events}) != len(events):
        raise ValueError('Nonempty unique event definitions required')
    if not isinstance(policy_hash, str) or len(policy_hash) != 64 or any(c not in '0123456789abcdef' for c in policy_hash):
        raise ValueError('Frozen source policy hash required')
    if any(type(c) is not int for c in costs) or tuple(costs) not in ((1,), (1, 2)):
        raise ValueError('Only original BASE or BASE/double-cost scenarios')
    expected = len(events) * 4 * len(costs)
    if type(comparison_budget) is not int or comparison_budget < expected:
        raise ValueError('Comparison family must include all events, sizes and costs')
    if input_exposure not in {'EXPOSED_RESEARCH', 'SYNTHETIC'}:
        raise ValueError('This contract grants no unexposed evaluation access')
    body = {'version': 'mc_event_dev_v1', 'events': [asdict(e) for e in events],
            'policy_hash': policy_hash, 'costs': list(costs),
            'comparison_budget': comparison_budget, 'input_exposure': input_exposure,
            'scope': 'DEV_ONLY', 'admission': 'ABSTAIN', 'G4_passed': False,
            'changes_original_daily_line': False, 'execution_enabled': False}
    return body | {'contract_hash': digest(body)}
