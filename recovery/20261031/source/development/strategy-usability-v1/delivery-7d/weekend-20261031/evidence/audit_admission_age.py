"""Separate checkpoint age from active notification wait; never re-grade old runs."""
import argparse
from collections import defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5] / 'source/evidence/new-machine-20261008'


def stats(values):
    known = sorted(v for v in values if isinstance(v, (int, float)))
    return dict(total=len(values), measured=len(known), missing=len(values)-len(known),
                p95=known[math.ceil(.95*len(known))-1] if known else None,
                maximum=max(known) if known else None)


def main(name):
    if Path(name).name != name:
        raise ValueError('RUN_NAME_REQUIRED')
    root = ROOT / name
    if not (root/'TEST_ONLY.json').is_file():
        raise ValueError('TEST_ONLY_REQUIRED')
    report = json.loads((root/'topology_report.json').read_text())
    if report['child_processes_alive']:
        raise ValueError('COMPLETED_RUN_REQUIRED')
    sources, groups = {}, defaultdict(list)
    for path in sorted(root.glob('TEST_ONLY-progress-*.jsonl')):
        raw = path.read_bytes()
        sources[path.name] = sha256(raw).hexdigest()
        for line in raw.decode().splitlines():
            row = json.loads(line)
            if row.get('research_strategy') == 'opening_momentum':
                groups[row['bar_end']].append(row['runtime_timing'])
    metrics = ('admission_queue_seconds', 'original_enqueue_age_at_preparation_seconds',
               'active_admission_wait_seconds', 'enqueue_to_commit_seconds')
    result = dict(test_only=True, run=name, original_verdict_unchanged=True,
        report_sha256=sha256((root/'topology_report.json').read_bytes()).hexdigest(),
        sources=sources, checkpoints=[dict(checkpoint=point,
            metrics={key: stats([row.get(key) for row in rows]) for key in metrics})
            for point, rows in sorted(groups.items())],
        limitation='Active wait excludes idle time before this notification; original age, deadlines and performance verdicts are retained.')
    target = HERE / (name+'-admission-age.json')
    target.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(path=str(target), checkpoints=len(groups), last=result['checkpoints'][-1])))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    main(parser.parse_args().run)
