"""Offline tests: no credentials read and no provider/network requests."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import probe_minute_history as probe

sys.path.insert(0, str(probe.WORKSPACE))
from kquant.market_clock import session_bounds_utc


def candles():
    opening, closing = session_bounds_utc(date(2026, 10, 6))
    return [SimpleNamespace(timestamp=opening + timedelta(minutes=i),
        open=Decimal('10'), high=Decimal('12'), low=Decimal('9'), close=Decimal('11'),
        volume=Decimal('100'), turnover=Decimal('1010.25'))
        for i in range(int((closing - opening).total_seconds() / 60))]


def run_fake(tmp_path, rows):
    import longbridge.openapi as sdk
    context = SimpleNamespace(history_candlesticks_by_date=lambda *a, **kw: rows)
    args = SimpleNamespace(symbol='NVDA', sessions='2026-10-06')
    with patch('kquant.local_env.load_market_data_env', return_value={'longbridge_credentials_configured': True}), \
         patch.dict(os.environ, {k: 'offline-placeholder' for k in ('LONGBRIDGE_APP_KEY', 'LONGBRIDGE_APP_SECRET', 'LONGBRIDGE_ACCESS_TOKEN')}), \
         patch.object(sdk, 'QuoteContext', return_value=context), \
         patch.object(sdk, 'Config', SimpleNamespace(from_apikey=lambda *a, **kw: None)), \
         patch.object(probe, 'OUT', tmp_path):
        return probe.run_worker(args)


def test_expired_token_is_classified_without_sdk_text():
    error = Exception('token expired; private-token-placeholder')
    error.code = 401003
    error.kind = 'OpenApi'
    report = probe.safe_provider_error(error)
    assert report['error_category'] == 'TOKEN_EXPIRED'
    assert report['provider_error_code'] == 401003
    assert 'private-token-placeholder' not in json.dumps(report)


def test_fresh_full_page_passes_and_keeps_decimal_fields(tmp_path):
    first = run_fake(tmp_path, candles())
    second = run_fake(tmp_path, candles())
    assert first['status'] == second['status'] == 'PROBE_PASSED'
    assert first['requests'] == second['requests'] == 1
    assert first['results'][0]['path'] != second['results'][0]['path']
    page = json.loads(Path(first['results'][0]['path']).read_text(encoding='utf-8'))
    assert page['accepted_unique_minutes'] == 390
    assert page['rows'][0]['turnover'] == '1010.25'
    assert page['production_admission_verified'] is False


def test_invalid_native_amount_prevents_pass(tmp_path):
    rows = candles()
    rows[0].turnover = Decimal('-1')
    result = run_fake(tmp_path, rows)
    assert result['status'] == 'PROBE_INCOMPLETE'
    assert result['results'][0]['accepted_unique_minutes'] == 389
    assert result['results'][0]['missing_minutes'] == 1


def test_naive_time_requires_contract_validation(tmp_path):
    rows = candles()
    for row in rows:
        row.timestamp = row.timestamp.replace(tzinfo=None)
    result = run_fake(tmp_path, rows)
    assert result['status'] == 'PROBE_INCOMPLETE'
    assert result['results'][0]['accepted_unique_minutes'] == 0


def test_duplicate_and_short_page_cannot_pass(tmp_path):
    rows = candles()
    result = run_fake(tmp_path, rows[:-1] + [rows[0]])
    assert result['status'] == 'PROBE_INCOMPLETE'
    assert result['results'][0]['missing_minutes'] == 1


def test_missing_native_numeric_field_is_rejected(tmp_path):
    rows = candles()
    rows[0].volume = None
    result = run_fake(tmp_path, rows)
    assert result['status'] == 'PROBE_INCOMPLETE'
    assert result['results'][0]['accepted_unique_minutes'] == 389
