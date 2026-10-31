"""Explicit private environment loader for the bounded quote-only P3 probe."""
import json
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'development/workspace'))

MARKET_KEYS = ('LONGBRIDGE_APP_KEY', 'LONGBRIDGE_APP_SECRET', 'LONGBRIDGE_ACCESS_TOKEN')


def market_environment():
    """Read current-user DPAPI privately; never merge partial credential sets."""
    if sys.platform != 'win32' or not os.environ.get('LOCALAPPDATA'):
        raise ValueError('CURRENT_USER_DPAPI_UNAVAILABLE')
    path = Path(os.environ['LOCALAPPDATA']) / 'KQUANT' / 'longbridge_market.dpapi'
    if not path.is_file():
        raise ValueError('DPAPI_CONFIG_MISSING')
    for item in [path, *path.parents]:
        if item.is_symlink() or getattr(item.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('REPARSE_CONFIG_PATH')
    script = r"""
$ErrorActionPreference='Stop'
$pointer=[IntPtr]::Zero
try {
  $path=Join-Path $env:LOCALAPPDATA 'KQUANT\longbridge_market.dpapi'
  $secure=ConvertTo-SecureString ([IO.File]::ReadAllText($path))
  $pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  [Console]::Out.Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer))
} finally {
  if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}
"""
    environment = {k: v for k, v in os.environ.items() if k.upper() != 'PSMODULEPATH'}
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, timeout=10, env=environment,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise ValueError('DPAPI_DECRYPT_FAILED')
    try:
        payload = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise ValueError('DPAPI_PAYLOAD_INVALID') from None
    if not isinstance(payload, dict) or not all(
            isinstance(payload.get(key), str) and payload[key].strip() for key in MARKET_KEYS):
        raise ValueError('DPAPI_CREDENTIAL_SET_INCOMPLETE')
    # Case-insensitive Windows environment: remove all inherited credential aliases.
    environment = {k: v for k, v in environment.items() if k.upper() not in MARKET_KEYS}
    environment.update({key: payload[key] for key in MARKET_KEYS})
    return environment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol', default='NVDA')
    parser.add_argument('--include-minute', action='store_true')
    args = parser.parse_args(argv)
    try:
        environment = market_environment()
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        status = str(exc) if isinstance(exc, ValueError) else 'DPAPI_LOADER_FAILED'
        print(json.dumps({'status': status, 'requests': 0}))
        return 2
    command = [sys.executable, str(ROOT / 'probe_market_readiness.py'), 'quote-facts',
               '--symbol', args.symbol, '--timestamp-contract', 'aware-only',
               '--max-requests', '12', '--run-seconds', '48']
    if args.include_minute:
        command.append('--include-minute')
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=65, env=environment)
        report = json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        print(json.dumps({'status': 'QUOTE_FACT_WRAPPER_TIMED_OUT', 'requests': None}))
        return 2
    except (OSError, ValueError):
        print(json.dumps({'status': 'QUOTE_FACT_WRAPPER_FAILED', 'requests': None}))
        return 2
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
