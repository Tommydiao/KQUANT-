"""Export approved DEV rows and verify independent roundtrip before reporting."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dataset import load_development, file_hash
from kquant_crypto.hybrid_dataset_capsule import export_capsule, load_capsule


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    args = p.parse_args()
    out = (ROOT/args.output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery'):
        raise ValueError('Independent research output required')
    source = ROOT/'outputs/dual_regime_v1/frozen/data_manifest.json'
    data = load_development(source)
    contract = export_capsule(data, out)
    restored = load_capsule(out)
    if restored != data:
        raise ValueError('Portable rows/provenance differ from authorized loader')
    result = dict(status='ROUNDTRIP_PASS', scope='DEV_ONLY', dataset_hash=data.content_hash,
        source_manifest_hash=file_hash(source), capsule_hash=contract['capsule_hash'],
        cutoff=data.cutoff, rows={s:{tf:len(b) for tf,b in frames.items()} for s,frames in data.bars.items()},
        compressed_bytes=sum(p.stat().st_size for p in out.glob('*.gz')),
        execution_enabled=False, standalone_system_release=False)
    (out/'verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
