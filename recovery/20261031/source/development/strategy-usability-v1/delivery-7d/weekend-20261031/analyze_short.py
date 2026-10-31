"""Bounded readonly diagnosis of explicitly isolated topology artifacts."""
import argparse
from collections import Counter
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    args = parser.parse_args()
    out = (ROOT/'source/evidence/new-machine-20261008'/args.run).resolve()
    if not out.is_relative_to(ROOT/'source/evidence/new-machine-20261008') or not (out/'TEST_ONLY.json').is_file():
        raise ValueError('TEST_ONLY_RUN_REQUIRED')
    raw = (out/'topology_report.json').read_bytes()
    report = json.loads(raw)
    rows = []
    with closing(sqlite3.connect((out/'TEST_ONLY-research.sqlite3').as_uri()+'?mode=ro', uri=True, timeout=.2)) as db:
        db.execute('PRAGMA query_only=ON')
        rows = db.execute("SELECT payload_json FROM evaluations WHERE session=? ORDER BY rowid", ('2026-10-22',)).fetchall()
    latest = {}
    for raw_row, in rows:
        value = json.loads(raw_row)
        if value.get('window_id') != 'OPENING_FIRST_HOUR_RESEARCH_V1':
            continue
        latest[(value['policy_id'], value['symbol'], value['right'], value.get('calculation_bar_end'))] = value
    incomplete = [dict(policy_id=v['policy_id'], symbol=v['symbol'], right=v['right'],
        point=v.get('calculation_bar_end'), state=v['state'], reasons=v.get('reasons'),
        generation=v.get('runtime_inputs', {}).get('input_generation'), input_checks=v.get('input_checks'))
        for v in latest.values() if v['state']=='INCOMPLETE']
    browser = report.get('real_browser') or {}
    failures = next((value for key, value in browser.items() if key in ('api_failure_observations', 'api_failures', 'api_failure_details', 'api_issues') and isinstance(value, list)), [])
    result = dict(test_only=True, report_sha256=sha256(raw).hexdigest(), run=args.run,
        errors=report.get('errors'), performance_pass=report.get('performance_pass'),
        children_alive=report.get('child_processes_alive'),
        http_failure_groups=dict(Counter(str((r.get('path'),r.get('status'),r.get('error'),r.get('response_error_code')))
            for r in report.get('http_failure_classification', []))),
        browser_keys=list(browser), browser_unexplained=[r for r in failures if r.get('classification')!='TEST_ONLY_UNMOUNTED'],
        background=report.get('legacy_included_transport_accounting', {}).get('totals'),
        points=[dict(checkpoint=r['checkpoint'], variants=r['variants'], segments=r['segments']) for r in report.get('checkpoints',[])],
        latest_position_count=len(latest), incomplete=incomplete)
    target = HERE/'evidence'/(args.run+'-analysis.json')
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(path=str(target),errors=result['errors'],background=result['background'],
        incomplete_reasons=dict(Counter(str((r['policy_id'],r['point'],r['symbol'],r['reasons'])) for r in incomplete)))))


if __name__=='__main__':
    main()
