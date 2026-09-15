"""Measure supervisor polling while an actual independent MC smoke run executes."""
import argparse
from pathlib import Path
import sys
import time
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from kquant_crypto.hybrid_delivery import atomic_json, sha, load
from kquant_crypto.hybrid_math_process import DevelopmentMathProcess


def calculate(output, paths):
    from benchmark_hybrid_mc_v12 import run
    code = run(output, paths, alternatives=True)
    return {'exit_code': code, 'report': output + '/report.json'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    p.add_argument('--paths', type=int, choices=(20,5000), default=20)
    args = p.parse_args()
    out = (ROOT / args.output).resolve()
    if not out.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent output required')
    out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0,str(ROOT/'tests'))
    from test_candidate_portfolio import warm_states, warmed, enter_normal, batch, bar
    fixtures=warm_states.__wrapped__()
    reference=warmed(fixtures)
    t=enter_normal(reference,symbols=('BTCUSDT',))
    initial=deepcopy(reference.snapshot())
    stop=reference.positions['BTCUSDT']['stop']
    current=bar(t,stop-1,open=365,high=366,low=stop-2)
    batch(reference,current,symbols=('BTCUSDT',),allow=False)
    expected=(reference.trades,reference.cash,reference.positions)
    sources = [Path(__file__), ROOT / 'kquant_crypto/hybrid_math_process.py',
               ROOT / 'scripts/benchmark_hybrid_mc_v12.py', ROOT/'tests/test_candidate_portfolio.py',
               ROOT/'kquant_crypto/candidate_simulation.py']
    hashes = {str(x.relative_to(ROOT)): sha(x) for x in sources}
    timeout=60 if args.paths==20 else 1000
    atomic_json(out / 'preregistration.json', {'timeout_seconds': timeout, 'paths': args.paths,
        'poll_interval_seconds': .01, 'scope': 'INDEPENDENT_SUPERVISOR_NOT_PRODUCTION_PROTECTION',
        'source_hashes': hashes, 'admission': 'ABSTAIN'})
    worker = DevelopmentMathProcess(calculate, (str((out / 'mc').relative_to(ROOT)),args.paths), timeout_seconds=timeout)
    timings = []
    protection_times=[]
    next_protection=time.monotonic()
    try:
        while True:
            start = time.perf_counter()
            result = worker.poll()
            timings.append(time.perf_counter() - start)
            if result['status'] != 'PENDING':
                break
            if time.monotonic()>=next_protection:
                portfolio=warmed(fixtures)
                portfolio.restore(deepcopy(initial))
                protection_start=time.perf_counter()
                batch(portfolio,current,symbols=('BTCUSDT',),allow=False)
                protection_times.append(time.perf_counter()-protection_start)
                if (portfolio.trades,portfolio.cash,portfolio.positions)!=expected:
                    result={'status':'FAILED','reason':'SYNTHETIC_PROTECTION_PARITY_MISMATCH'}
                    break
                next_protection=time.monotonic()+1
            time.sleep(.01)
    finally:
        worker.close()
    timings.sort()
    protection_times.sort()
    passed = result['status'] == 'COMPLETED' and result['value']['exit_code'] == 0
    unchanged = all(sha(ROOT / name) == value for name, value in hashes.items())
    atomic_json(out / 'result.json', {'worker': result, 'observed_polls': len(timings),
        'p95_poll_seconds': timings[int((len(timings)-1)*.95)], 'max_poll_seconds': max(timings),
        'child_stopped': not worker.process.is_alive(), 'reader_stopped': not worker.reader.is_alive(),
        'source_unchanged': unchanged, 'smoke_completed': passed, 'G4_passed': False,
        'paths_requested':args.paths,'protection_checks':len(protection_times),
        'synthetic_protection_parity':passed and bool(protection_times),
        'p95_protection_seconds':protection_times[int((len(protection_times)-1)*.95)] if protection_times else None,
        'max_protection_seconds':max(protection_times) if protection_times else None,
        'scope': 'INDEPENDENT_SUPERVISOR_NOT_PRODUCTION_PROTECTION'})
    print(out / 'result.json')
    return 0 if passed and unchanged else 1


if __name__ == '__main__':
    sys.exit(main())
