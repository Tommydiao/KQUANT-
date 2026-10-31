"""Verify the installed SDK time adapter against its native UTC representation."""
from datetime import date, datetime, timezone
from importlib.metadata import version
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PREFIX = 'KQUANT_TIME_CONTRACT='


def worker():
    sys.path.insert(0, str(ROOT / 'development/workspace'))
    from kquant.local_env import load_market_data_env
    from kquant.market_clock import session_bounds_utc
    from longbridge.openapi import Config, QuoteContext, Period, AdjustType, TradeSessions
    from probe_minute_history import safe_provider_error
    audit = load_market_data_env(path=ROOT / '.env')
    if not audit['longbridge_credentials_configured']:
        return {'status': 'BLOCKED_CREDENTIALS_MISSING'}
    try:
        context = QuoteContext(Config.from_apikey(os.environ['LONGBRIDGE_APP_KEY'],
            os.environ['LONGBRIDGE_APP_SECRET'], os.environ['LONGBRIDGE_ACCESS_TOKEN'],
            enable_print_quote_packages=False))
        day = date(2026, 10, 6)
        rows = context.history_candlesticks_by_date('NVDA.US', Period.Min_1, AdjustType.NoAdjust,
            day, day, trade_sessions=TradeSessions.Intraday)
        pairs = []
        for row in rows:
            raw = row.timestamp
            match = re.search(r'\btimestamp:\s*"([^"]+)"', repr(row))
            if not isinstance(raw, datetime) or raw.tzinfo is not None or not match:
                raise ValueError('NATIVE_TIMESTAMP_REPRESENTATION_NOT_VERIFIABLE')
            native = datetime.fromisoformat(match.group(1).replace('Z', '+00:00'))
            if native.tzinfo is None:
                raise ValueError('NATIVE_UTC_TIMEZONE_MISSING')
            converted = raw.replace(tzinfo=ZoneInfo('Asia/Shanghai')).astimezone(timezone.utc)
            if converted != native:
                raise ValueError('NATIVE_UTC_AND_EXPLICIT_LOCAL_ADAPTER_MISMATCH')
            pairs.append({'raw_sdk_timestamp': raw.isoformat(), 'native_utc': native.isoformat(),
                          'converted_utc': converted.isoformat()})
        opening, closing = session_bounds_utc(day)
        expected = int((closing - opening).total_seconds() / 60)
        stamps = {datetime.fromisoformat(pair['native_utc']) for pair in pairs}
        if len(pairs) != expected or len(stamps) != expected or min(stamps) != opening:
            raise ValueError('LIVE_CONTRACT_SAMPLE_INCOMPLETE')
        if any(not opening <= stamp < closing or stamp.second or stamp.microsecond for stamp in stamps):
            raise ValueError('LIVE_CONTRACT_SAMPLE_OFF_MINUTE_GRID')
        wheel = ROOT / 'environment/wheels/longbridge-4.4.1-cp312-cp312-win_amd64.whl'
        report = {'status': 'VERIFIED', 'sdk_version': version('longbridge'),
            'sdk_wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
            'naive_timezone': 'Asia/Shanghai', 'verified_at': datetime.now(timezone.utc).isoformat(),
            'verification_method': 'Every live SDK naive timestamp independently matched its native UTC debug timestamp after explicit Asia/Shanghai conversion; full XNYS session grid matched.',
            'python_local_tzname': list(time.tzname), 'provider_symbol': 'NVDA.US', 'session': day.isoformat(),
            'verified_rows': len(pairs), 'requests': 1, 'pairs': pairs,
            'sources': [{'kind': 'INSTALLED_SDK_LIVE_NATIVE_UTC_REPRESENTATION'},
                {'url': 'https://github.com/longbridge/openapi/blob/f6e9f7d04ca58c09e64957b12ddc6aaf184afa8b/python/src/time.rs',
                 'observation': 'PyDateTime::from_timestamp(py, unix_timestamp, None) returns local naive time; upstream corroboration, not an exact wheel build provenance claim.'}],
            'production_admission_verified': False, 'old_business_continuity': 'UNKNOWN'}
        if report['sdk_version'] != '4.4.1':
            raise ValueError('SDK_VERSION_CHANGED')
        return report
    except Exception as exc:
        return {'status': 'TIMESTAMP_CONTRACT_VERIFICATION_FAILED', **safe_provider_error(exc)}


if __name__ == '__main__':
    if '--worker' in sys.argv:
        print(PREFIX + json.dumps(worker(), ensure_ascii=True))
    else:
        try:
            done = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=55)
            payloads = [line[len(PREFIX):] for line in done.stdout.splitlines() if line.startswith(PREFIX)]
            result = json.loads(payloads[-1]) if payloads else {'status': 'WORKER_FAILED', 'returncode': done.returncode}
        except subprocess.TimeoutExpired:
            result = {'status': 'WORKER_TIMED_OUT', 'child_terminated': True}
        target = ROOT / 'evidence' / ('sdk-timestamp-contract-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
        with target.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print(json.dumps({k: v for k, v in result.items() if k not in ('pairs', 'sources')}, ensure_ascii=True, indent=2))
        print(json.dumps({'evidence_path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}))
