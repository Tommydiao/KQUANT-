import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('terminal_audit', Path(__file__).resolve().parents[1] / 'scripts/audit_hybrid_terminal_clock.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_cleanup_delay_is_not_exception_timestamp():
    report = {'last_received_interval': {'clock_segment_id': 'a', 'received_at_monotonic': 140},
              'observed_until_monotonic': 10000, 'failure': {}}
    clock = {'segment_id': 'a', 'segment': {'mono_anchor': 100}}
    result = module.audit(report, clock)
    assert result['last_receipt_segment_age'] == 40
    assert result['terminal_segment_age'] == 9900
    assert result['exception_time_recorded'] is False
    assert result['suspend_or_clock_reversal_proven'] is False
    assert result['continuity_pass'] is False
    clock['segment_id'] = 'b'
    with pytest.raises(ValueError):
        module.audit(report, clock)
