"""Evidence index only. No SDK, credentials, database connections or service start."""
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent
FIRST=HERE.parent/'opening-first-hour'
ROOT=HERE.parents[4]


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    sources={}
    selected=[*FIRST.glob('*.py'),*FIRST.glob('assembly/*'),
        FIRST/'lifecycle-candidate/start_kquant_workspace.ps1',
        FIRST/'lifecycle-candidate/scripts/FoundationLifecycle.ps1',
        *FIRST.glob('patches/**/*'),*FIRST.glob('build/unified/**/*'),*FIRST.glob('build/stock/**/*'),
        *HERE.glob('*.py'),*HERE.glob('*.cjs'),*HERE.glob('patches/**/*'),
        *HERE.glob('calendar/*.py'),*HERE.glob('config/*.json')]
    for path in selected:
        if path.is_file() and '__pycache__' not in path.parts:
            sources[str(path.relative_to(HERE.parent))]=digest(path)
    tests=[]
    for path in sorted((HERE/'evidence').glob('*.xml')):
        root=ET.parse(path).getroot()
        suites=[root] if root.tag=='testsuite' else list(root.findall('testsuite'))
        tests.append(dict(path=str(path.relative_to(HERE)),sha256=digest(path),
            **{key:sum(int(s.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')}))
    evidence=[]
    for directory in (HERE/'evidence',HERE/'C-evidence'):
        for path in sorted(directory.rglob('*')):
            if not path.is_file() or path.suffix not in {'.json','.xml','.png','.md','.txt'}:
                continue
            if path.name in {'browser-config.json','clock-control.json'}:
                continue
            evidence.append(dict(path=str(path.relative_to(HERE)),sha256=digest(path),bytes=path.stat().st_size))
    topologies=[]
    evidence_root=ROOT/'source/evidence/new-machine-20261008'
    reports=[*evidence_root.glob('weekend-*-20261031*/topology_report.json'),
             *evidence_root.glob('sunday-*-20261101/topology_report.json'),
             *evidence_root.glob('iteration-*-20261101/topology_report.json'),
             *evidence_root.glob('agent-*-20261101/topology_report.json')]
    for path in sorted(reports):
        report=json.loads(path.read_text())
        topologies.append(dict(path=str(path),sha256=digest(path),
            duration_seconds=report.get('duration_seconds'),errors=report.get('errors'),
            admission_diagnostic_profile=report.get('admission_diagnostic_profile'),
            tested_sources_unchanged=report.get('tested_sources_unchanged'),
            performance_pass=report.get('performance_pass'),
            limited_research_performance_pass=report.get('limited_research_performance_pass'),
            child_processes_alive=report.get('child_processes_alive'),
            queue_p95=[p.get('segments',{}).get('enqueue_to_commit_seconds',{}).get('p95_seconds')
                for p in report.get('checkpoints',[])],
            query_accounting=report.get('legacy_included_transport_accounting')))
    api=[json.loads(p.read_text()) for p in (HERE/'evidence').glob('real-*.json')]
    sent=[row for row in api if row.get('paid_call') is True]
    unknown=any((row.get('result') or {}).get('actual_cost_usd') is None for row in sent)
    known_cost=sum((Decimal((row.get('result') or {})['actual_cost_usd']) for row in sent
                   if (row.get('result') or {}).get('actual_cost_usd') is not None),Decimal(0))
    value=dict(schema='WEEKEND_EXECUTION_EVIDENCE_INDEX_V1',captured_at=datetime.now(timezone.utc).isoformat(),
        old_seven_day_verdict='FAIL_UNCHANGED',candidate_accepted=False,production_started=False,
        real_api_tasks_sent=len(sent),real_api_unknown_cost=unknown,known_api_cost_usd=str(known_cost),
        real_api_states=[dict(role=r.get('role'),case=r.get('case'),state=r.get('state')) for r in api],
        external_capability_gate_pass=None,tests=tests,topologies=topologies,evidence=evidence,
        sources=sources,source_identity=digest_bytes(sources),
        consistency='Sequential file observations, not an atomic runtime or database snapshot.')
    target=HERE/'EXECUTION_EVIDENCE.json'
    target.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(path=str(target),source_identity=value['source_identity'],sources=len(sources),
        evidence=len(evidence),topologies=len(topologies))))


def digest_bytes(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


if __name__=='__main__':
    main()
