"""Small existing-live-memory check, no database or SDK access and no credentials."""
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
from time import sleep
import requests

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[4]
entry_path=ROOT/'source/development/workspace/config/local_workspace_entry.json'
entry=json.loads(entry_path.read_text(encoding='utf-8-sig'))
report=dict(observed_at=datetime.now(UTC).isoformat(),candidate_id=entry['candidate_id'],
    read_only=True, sdk_connections=0, production_writes=0, no_continuous_uptime_claim=True,
    manifest_proofs={}, samples=[])
for key in ('runtime_manifest','recovery_manifest'):
    proof=entry[key]
    path=Path(proof['path'])
    assert path.is_relative_to(ROOT)
    actual=sha256(path.read_bytes()).hexdigest()
    report['manifest_proofs'][key]=dict(path=str(path),sha256=actual,matches=actual==proof['sha256'])
with requests.Session() as client:
    for number in range(3):
        observed=datetime.now(UTC).isoformat()
        try:
            response=client.get('http://127.0.0.1:8001/api/health/live',timeout=(1,3))
            body=response.json()
            observation=body.get('service_observation',{})
            worker=observation.get('research_worker',{})
            report['samples'].append(dict(observed_at=observed,http=response.status_code,
                backend_release=body.get('backend_release'),backend_manifest_sha256=body.get('backend_manifest_sha256'),
                service_state=observation.get('state'),heartbeat_age_seconds=observation.get('heartbeat_age_seconds'),
                process_identity_verified=observation.get('process_identity_verified'),
                listeners=observation.get('listeners'),run_session_id=observation.get('run_session_id'),
                snapshot=observation.get('snapshot'),worker=worker))
        except (requests.RequestException,ValueError) as exc:
            report['samples'].append(dict(observed_at=observed,error_type=type(exc).__name__))
        if number<2:
            sleep(5)
output=HERE/'evidence'/('live-preserved-'+datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')+'.json')
output.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'path':str(output),'report':report},indent=2))
