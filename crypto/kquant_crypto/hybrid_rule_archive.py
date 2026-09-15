"""Content-addressed public rule evidence, separate from any execution cache."""
import hashlib
import json
from pathlib import Path
import re


def save_snapshot(directory, payload, *, received_at, source):
    if type(received_at) is not int or received_at < 0:
        raise ValueError('Explicit local receipt time required')
    if source != 'BINANCE_SPOT_PUBLIC_EXCHANGE_INFO':
        raise ValueError('Public rule evidence only')
    if not isinstance(payload, dict) or not isinstance(payload.get('symbols'), list):
        raise ValueError('Public exchangeInfo object required')
    record = {'payload':payload,'received_at':received_at,'source':source,
              'source_event_time':None,'execution_allowed':False}
    raw = json.dumps(record, sort_keys=True, separators=(',',':'), allow_nan=False).encode()
    digest = hashlib.sha256(raw).hexdigest()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (digest + '.json')
    try:
        with path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError('Existing snapshot corrupted; do not overwrite')
    return digest


def read_snapshot(directory, digest):
    if not isinstance(digest,str) or re.fullmatch('[0-9a-f]{64}',digest) is None:
        raise ValueError('Content identity required')
    raw = (Path(directory) / (digest + '.json')).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('Rule snapshot integrity failure')
    return json.loads(raw)
