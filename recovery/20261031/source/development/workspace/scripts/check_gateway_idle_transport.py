"""TEST_ONLY real Gateway TCP idle-connection comparison; no SDK or business DB."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import json
import multiprocessing as mp
from pathlib import Path
import socket
from time import sleep

import httpx

from check_r58_p10_topology import configure, gateway, spawn, command, safe, observe_http


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=20)
    args = parser.parse_args()
    if not 2 <= args.rounds <= 30:
        parser.error('rounds must be between 2 and 30')
    out = safe(args.out)
    out.mkdir(parents=True, exist_ok=False)
    dist = out / 'TEST_ONLY-empty-dist'
    dist.mkdir()
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    cfg = {'out': str(out), 'dist': str(dist), 'backend_port': 1, 'gateway_port': port}
    process, control, ready = spawn(mp.get_context('spawn'), gateway, cfg, None)
    samples = []
    try:
        for attempt in range(40):
            try:
                with httpx.Client(timeout=1) as client:
                    if client.get(f'http://127.0.0.1:{port}/api/health/live').status_code == 200:
                        break
            except httpx.HTTPError:
                pass
            sleep(.1)
        else:
            raise RuntimeError('TEST_GATEWAY_NOT_LISTENING')

        def poll(page, expiry):
            rows = []
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=3,
                              limits=httpx.Limits(keepalive_expiry=expiry)) as client:
                for sequence in range(args.rounds):
                    row = observe_http(client, '/api/health/live', page, sequence)
                    row['client_keepalive_expiry_seconds'] = expiry
                    rows.append(row)
                    if sequence + 1 < args.rounds:
                        sleep(5)
            return rows

        with ThreadPoolExecutor(max_workers=6) as pool:
            jobs = [pool.submit(poll, page, 5 if page < 3 else 1) for page in range(6)]
            for job in jobs:
                samples.extend(job.result())
    finally:
        try:
            command(control, 'stop')
        finally:
            process.join(15)
            if process.is_alive():
                process.terminate()
                process.join(5)
            control.close()
    report = {'test_only': True, 'production_started': False, 'sdk_connections': 0,
              'actual_gateway_pid': ready['pid'], 'port': port,
              'observed_at': datetime.now(UTC).isoformat(), 'samples': samples,
              'errors_by_expiry': {str(expiry): dict(Counter(r['error'] for r in samples
                  if r['client_keepalive_expiry_seconds'] == expiry and 'error' in r)) for expiry in (5, 1)},
              'not_full_topology_acceptance': True}
    (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'samples'}))


if __name__ == '__main__':
    main()
