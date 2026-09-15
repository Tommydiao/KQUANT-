"""Audit captured actual public rules with synthetic IOC proposals, no network."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_delivery import load, sha, atomic_json
from kquant_crypto.hybrid_exchange_rule_audit import audit_limit_ioc


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    source=(ROOT/args.input).resolve()
    out=(ROOT/args.output).resolve()
    base=ROOT/'outputs/hybrid_delivery'
    if not source.is_relative_to(base) or not out.is_relative_to(base):
        raise ValueError('Independent evidence paths required')
    meta=load(source/'evidence.json')
    if sha(source/'response.json') != meta['response_sha256']:
        raise ValueError('Captured source hash mismatch')
    payload=load(source/'response.json')
    out.mkdir(parents=True,exist_ok=False)
    fixtures={'BTCUSDT':('100000','.001'),'ETHUSDT':('3000','.01'),'SOLUSDT':('100','.1')}
    results={s:audit_limit_ioc(payload,s,price=p,quantity=q) for s,(p,q) in fixtures.items()}
    atomic_json(out/'results.json',results)
    atomic_json(out/'evidence.json',{'scope':'REAL_CAPTURED_RULES_SYNTHETIC_PROPOSALS',
        'input':str(source.relative_to(ROOT)), 'response_sha256':meta['response_sha256'],
        'fixtures':fixtures,'result_sha256':sha(out/'results.json'),
        'execution_allowed':False,'account_accessed':False,'T34_passed':False})
    print(out/'evidence.json')


if __name__=='__main__':
    main()
