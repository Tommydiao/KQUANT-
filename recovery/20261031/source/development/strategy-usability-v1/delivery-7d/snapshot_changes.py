"""Hash only this delivery delta and its accepted parent, without deployment."""
from datetime import datetime, timezone
from hashlib import sha256
import argparse
import json
from pathlib import Path
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = ROOT / 'source/development/workspace'


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--assembly', type=Path)
    parser.add_argument('--projection', type=Path)
    args = parser.parse_args()
    if bool(args.assembly) != bool(args.projection):
        parser.error('--assembly and --projection must be provided together')
    entry_path = BASE/'config/local_workspace_entry.json'
    entry = read(entry_path)
    manifest_path = Path(entry['runtime_manifest']['path'])
    assert digest(manifest_path) == entry['runtime_manifest']['sha256']
    manifest = read(manifest_path)
    delta = []
    for path in sorted((HERE/'patches/kquant').glob('*.py')):
        relative = 'kquant/' + path.name
        actual = digest(BASE/relative)
        expected = manifest['files'][relative]['sha256']
        delta.append({'path':relative,'accepted_parent_sha256':expected,
            'actual_live_sha256':actual,'live_matches_accepted':actual == expected,
            'development_patch_sha256':digest(path)})
    if not all(row['live_matches_accepted'] for row in delta):
        raise ValueError('ACCEPTED_PARENT_DRIFT_NO_DEPLOYMENT')
    runtime = read(ROOT/'runtime/work/option_foundation/runtime/services.json')
    worker = read(ROOT/'runtime/work/option_foundation/runtime/one-minute-worker.json')
    checks = []
    for url in ('http://127.0.0.1:8001/api/health/live', 'http://127.0.0.1:8020/'):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                checks.append({'url':url,'status':response.status})
        except Exception as exc:
            checks.append({'url':url,'status':None,'error':type(exc).__name__})
    now = datetime.now(timezone.utc)
    assembly = {'state': 'NOT_CHECKED', 'final_acceptance': None}
    if args.assembly:
        from summarize_assembly import summary
        assembly = summary(args.assembly, args.projection)
    value = {'observed_at':now.isoformat(),'accepted_parent_candidate':entry['candidate_id'],
        'entry_sha256':digest(entry_path),'manifest_sha256':digest(manifest_path),
        'constraint_sha256':digest(HERE/'constraint.json'),'denominator_sha256':digest(HERE/'denominator.json'),
        'patches':delta,'live_code_modified':False,'deployed':False,'new_candidate_accepted':False,
        'new_matched_hour': assembly, 'runtime':runtime,'http':checks,
        'worker':{key:worker['worker'].get(key) for key in ('state','stage','first_loop_at','last_cycle_at',
            'loop_count','thread_alive','research_ready','last_bar_age_seconds','clock_measurement')},
        'evidence_hashes':{p.name:digest(p) for p in sorted(HERE.glob('*')) if p.is_file()
            and p.suffix in {'.py','.md','.json','.xml'} and not p.name.startswith('patch-snapshot-')}}
    output = HERE/('patch-snapshot-'+now.strftime('%Y%m%dT%H%M%SZ')+'.json')
    with output.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2,ensure_ascii=False)
    print(json.dumps({'evidence':str(output),'candidate':entry['candidate_id'],'patches':len(delta),
        'live_hashes_match':True,'runtime_state':runtime['state'],'http':checks},ensure_ascii=False))


if __name__ == '__main__':
    main()
