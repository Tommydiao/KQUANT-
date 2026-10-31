"""Private current-user DPAPI input using the existing credential file format."""
import argparse
import getpass
import os
from pathlib import Path
import secrets
import subprocess
import sys
from bootstrap import activate
activate()
from kquant.options_llm_credentials import credential_path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replace',action='store_true')
    args=parser.parse_args()
    if not sys.stdin.isatty():
        parser.error('Run privately in a local interactive terminal. Do not pipe a key.')
    path=credential_path()
    if path.exists() and not args.replace:
        raise ValueError('CONFIG_EXISTS_USE_EXPLICIT_REPLACE')
    for node in (path,*path.parents):
        if node.exists() and (node.is_symlink() or getattr(node.lstat(),'st_file_attributes',0)&0x400):
            raise ValueError('REPARSE_CREDENTIAL_PATH')
    key=getpass.getpass('OpenAI API key (hidden, local only): ').strip()
    if not key or any(char.isspace() for char in key):
        raise ValueError('NONEMPTY_SINGLE_KEY_REQUIRED')
    script="""$ErrorActionPreference='Stop'
$raw=[Console]::In.ReadToEnd()
$value=ConvertTo-SecureString -String $raw -AsPlainText -Force
[Console]::Out.Write((ConvertFrom-SecureString $value))
"""
    env={k:v for k,v in os.environ.items() if k.upper()!='PSMODULEPATH'}
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
        input=key.encode('utf-8'),capture_output=True,timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,env=env)
    encrypted=result.stdout.strip()
    if result.returncode or not encrypted or any(c not in b'0123456789abcdefABCDEF' for c in encrypted):
        raise ValueError('DPAPI_SAVE_FAILED')
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+secrets.token_hex(8)+'.preparing')
    with temp.open('xb') as stream:
        stream.write(encrypted)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path) if args.replace else temp.rename(path)
    print('LLM key saved using current-user DPAPI. No API call or service start was made.')


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
        print(str(exc) if isinstance(exc,ValueError) else type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
