"""Recover a constructed partial copy of actual engineering paths, not originals."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_mc_recovery import read_pair_prefix


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();base=ROOT/'outputs/hybrid_delivery'
    source,out=[(ROOT/s).resolve() for s in (a.source,a.output)]
    if any(not s.is_relative_to(base) for s in (source,out)) or out.exists():raise ValueError('New evidence directory required')
    report=json.loads((source/'report.json').read_text())
    if report['phase']!='engineering':raise ValueError('Engineering fixture only')
    hashes={p.name:sha(p) for p in source.glob('pair_*.jsonl')}
    if not hashes:raise ValueError('No actual completed paths')
    out.mkdir(exist_ok=False);partial=out/'constructed_partial';partial.mkdir()
    shutil.copy2(source/'preregistration.json',partial/'preregistration.json')
    for name in hashes:shutil.copy2(source/name,partial/name)
    first=sorted(hashes)[0];rows,raw=read_pair_prefix(partial/first,2)
    if len(rows)!=2:raise ValueError('Expected two actual engineering paths')
    (partial/first).write_bytes(raw.splitlines(keepends=True)[0])
    write_json(partial/'fixture.json',dict(constructed_interruption=True,real_crash_claim=False,
        original_source=str(source),retained_prefix=1,missing_paths=1,source_hashes=hashes))
    recovered=out/'recovered'
    command=[sys.executable,str(ROOT/'scripts/run_rx06_prospective_pair_dev.py'),
        '--phase','engineering','--output',str(recovered),'--resume-from',str(partial)]
    with (out/'recovery.log').open('x',encoding='utf-8') as log:
        result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    if result.returncode:raise RuntimeError('Actual recovery failed; see preserved log')
    checks={name:sha(recovered/name)==digest and sha(source/name)==digest for name,digest in hashes.items()}
    restored=json.loads((recovered/'report.json').read_text())
    if not all(checks.values()) or restored['records']!=report['records']:
        raise ValueError('Recovered evidence differs from complete actual source')
    write_json(out/'verification.json',dict(scope='ACTUAL_PATH_RECOVERY_ENGINEERING',
        constructed_partial_fixture=True,originals_unchanged=True,all_path_hashes_match=True,
        completed_files=len(hashes),reused_paths=2*len(hashes)-1,recomputed_paths=1,
        command=command,exit_code=result.returncode,log_hash=sha(out/'recovery.log'),
        runtime_enabled=False,code_hash=sha(Path(__file__))))
    print(json.dumps(dict(files=len(hashes),recomputed_paths=1,all_hashes_match=True)))


if __name__=='__main__':main()
