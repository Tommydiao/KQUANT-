import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('quote_audit', Path(__file__).resolve().parents[1] / 'scripts/audit_hybrid_quote_rejections.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_inside_interval_remains_rejected():
    row = dict(symbol='BTCUSDT', clock_validation='quote_receipt_order_uncertain',
               source_time=1.1, source_event_time_native_ms=1100,
               received_at_lower=1, received_at_upper=1.5)
    result = module.summarize([row])
    assert result['groups'][0]['reason'] == 'quote_receipt_order_uncertain'
    assert result['groups'][0]['source_positions'] == {'within_interval': 1}
    assert not result['changes_freshness']
    row['source_event_time_native_ms'] = 1200
    with pytest.raises(ValueError):
        module.summarize([row])
