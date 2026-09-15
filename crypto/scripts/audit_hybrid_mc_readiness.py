"""Read-only engineering prerequisite audit with independent output."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_delivery import atomic_json
from kquant_crypto.hybrid_mc_evidence_audit import audit_mc_engineering

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--output',required=True)
    args=p.parse_args()
    out=(ROOT/args.output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery'):
        raise ValueError('Independent output required')
    out.mkdir(parents=True,exist_ok=False)
    result=audit_mc_engineering(ROOT)
    atomic_json(out/'evidence.json',result)
    raise SystemExit(0 if result['engineering_artifacts_consistent'] else 1)
