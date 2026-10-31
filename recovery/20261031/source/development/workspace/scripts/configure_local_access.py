"""Interactive current-user DPAPI setup. Never accepts credentials as arguments."""
import argparse
import getpass
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kquant.security import generate_password_hash

FILENAMES = {'login': 'workspace_login.dpapi', 'market': 'longbridge_market.dpapi'}


def protect(value):
    if sys.platform != 'win32':
        raise ValueError('WINDOWS_CURRENT_USER_DPAPI_REQUIRED')
    script = """
$ErrorActionPreference='Stop'
$raw=[Console]::In.ReadToEnd()
$secure=ConvertTo-SecureString -String $raw -AsPlainText -Force
[Console]::Out.Write((ConvertFrom-SecureString $secure))
"""
    # A Python child of PowerShell 7 can inherit incompatible module paths for Windows PowerShell.
    environment = {key: value for key, value in os.environ.items() if key.upper() != 'PSMODULEPATH'}
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
        input=json.dumps(value, ensure_ascii=True).encode('ascii'), capture_output=True,
        timeout=10, creationflags=subprocess.CREATE_NO_WINDOW, env=environment)
    if result.returncode or not result.stdout.strip():
        raise ValueError('DPAPI_PROTECTION_FAILED_NO_CONFIG_WRITTEN')
    encrypted = result.stdout.strip()
    if len(encrypted) % 2 or any(c not in b'0123456789abcdefABCDEF' for c in encrypted):
        raise ValueError('DPAPI_OUTPUT_INVALID')
    return encrypted


def save(kind, payload, *, replace=False):
    if not os.environ.get('LOCALAPPDATA'):
        raise ValueError('LOCALAPPDATA_REQUIRED')
    directory = Path(os.environ['LOCALAPPDATA']) / 'KQUANT'
    for item in [directory, *directory.parents]:
        if item.exists() and (item.is_symlink() or getattr(item.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('REPARSE_CONFIG_PATH')
    path = directory / FILENAMES[kind]
    if path.exists() and not replace:
        raise ValueError('CONFIG_EXISTS_USE_EXPLICIT_REPLACE')
    if path.exists() and (path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400):
        raise ValueError('REPARSE_CONFIG_PATH')
    encrypted = protect(payload)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / (path.name + '.' + secrets.token_hex(8) + '.preparing')
    with temporary.open('xb') as stream:
        stream.write(encrypted)
        stream.flush()
        os.fsync(stream.fileno())
    if replace:
        temporary.replace(path)
    else:
        temporary.rename(path)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=sorted(FILENAMES), required=True)
    parser.add_argument('--replace', action='store_true')
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.error('Run locally in an interactive terminal; do not pipe credentials.')
    if args.kind == 'login':
        email = input('Local login email: ').strip()
        if '@' not in email or len(email) > 254:
            raise ValueError('VALID_LOGIN_EMAIL_REQUIRED')
        password = getpass.getpass('New local password (at least 12 characters): ')
        if password != getpass.getpass('Repeat password: '):
            raise ValueError('PASSWORDS_DO_NOT_MATCH')
        payload = {'KQUANT_WORKSPACE_LOGIN_ENABLED': 'true', 'KQUANT_WORKSPACE_LOGIN_EMAIL': email,
            'KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH': generate_password_hash(password),
            'KQUANT_WORKSPACE_SESSION_SECRET': secrets.token_urlsafe(48)}
    else:
        names = ('LONGBRIDGE_APP_KEY', 'LONGBRIDGE_APP_SECRET', 'LONGBRIDGE_ACCESS_TOKEN')
        payload = {name: getpass.getpass(name + ': ').strip() for name in names}
        if not all(payload.values()):
            raise ValueError('ALL_MARKET_FIELDS_REQUIRED')
    path = save(args.kind, payload, replace=args.replace)
    print('Encrypted configuration saved locally: ' + str(path))
    print('No service was started; no provider request, order or approval was made.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(str(exc) if isinstance(exc, ValueError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
