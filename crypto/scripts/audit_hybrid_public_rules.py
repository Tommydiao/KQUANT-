"""One bounded public market-data request; never an account or execution client."""
import argparse
from datetime import datetime, UTC
import json
from pathlib import Path
import sys
import time
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_delivery import atomic_json, sha
from kquant_crypto.hybrid_exchange_rule_audit import audit_symbol
from kquant_crypto.hybrid_rule_archive import save_snapshot, read_snapshot


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    p.add_argument('--index', action='store_true')
    a = p.parse_args()
    out = (ROOT / a.output).resolve()
    if not out.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent output required')
    out.mkdir(parents=True, exist_ok=False)
    url = 'https://data-api.binance.vision/api/v3/exchangeInfo?symbols=%5B%22BTCUSDT%22,%22ETHUSDT%22,%22SOLUSDT%22%5D'
    started = time.monotonic()
    metadata = {'source': url, 'requested_at_local_utc': datetime.now(UTC).isoformat(),
                'source_event_time': None, 'execution_allowed': False,
                'scope': 'PUBLIC_SPOT_RULE_INVENTORY_ONLY'}
    try:
        with urlopen(Request(url), timeout=20) as response:
            raw = response.read(2_000_001)
            received_at_ms = time.time_ns() // 1_000_000
            if len(raw) > 2_000_000:
                raise ValueError('Response size exceeded')
        (out / 'response.json').write_bytes(raw)
        payload = json.loads(raw)
        snapshot_id = save_snapshot(out / 'archive', payload, received_at=received_at_ms,
                                    source='BINANCE_SPOT_PUBLIC_EXCHANGE_INFO')
        restored = read_snapshot(out / 'archive', snapshot_id)
        if restored['payload'] != payload:
            raise ValueError('Archive read-back mismatch')
        if a.index:
            from kquant_crypto.hybrid_public_rule_index import PublicRuleIndex
            directory=ROOT/'work/hybrid_delivery/public_rule_observations'
            archived=save_snapshot(directory/'archive',payload,received_at=received_at_ms,
                                   source='BINANCE_SPOT_PUBLIC_EXCHANGE_INFO')
            if archived!=snapshot_id:
                raise ValueError('Index archive identity mismatch')
            index=PublicRuleIndex(directory,directory/'archive')
            try:
                index.register(archived)
                metadata['indexed_rules']={s:index.latest(s,now_ms=time.time_ns()//1_000_000,max_age_ms=5000)
                                           for s in ('BTCUSDT','ETHUSDT','SOLUSDT')}
            finally:
                index.close()
        result = {s: audit_symbol(payload, s) for s in ('BTCUSDT','ETHUSDT','SOLUSDT')}
        atomic_json(out / 'audit.json', result)
        metadata.update(status='PUBLIC_RESPONSE_AUDITED', response_sha256=sha(out / 'response.json'),
                        snapshot_id=snapshot_id, archive_readback_verified=True,
                        archive_clock_basis='LOCAL_RECEIPT_MILLISECONDS_NOT_SOURCE_EVENT')
        code = 0
    except HTTPError as exc:
        metadata.update(status='PROVIDER_UNAVAILABLE', http_status=exc.code)
        code = 2
    except (URLError, TimeoutError, ValueError) as exc:
        metadata.update(status='UNAVAILABLE_OR_INVALID', error_type=type(exc).__name__)
        code = 2
    metadata.update(elapsed_seconds=time.monotonic()-started,
                    received_at_local_utc=datetime.now(UTC).isoformat())
    atomic_json(out / 'evidence.json', metadata)
    print(json.dumps(metadata))
    return code


if __name__ == '__main__':
    sys.exit(main())
