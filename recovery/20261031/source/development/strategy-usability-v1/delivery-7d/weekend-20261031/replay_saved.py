"""Current isolated math on saved native inputs; never create current tasks."""
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
FIRST=HERE.parent/'opening-first-hour'
os.environ['KQUANT_TEST_WEEKEND_OVERLAY']=str(HERE)
spec=importlib.util.spec_from_file_location('weekend_replay_bootstrap',FIRST/'assembly/bootstrap.py')
bootstrap=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
bootstrap.activate()
sys.path.insert(0,str(FIRST))
import first_hour


def main():
    source=HERE.parent/'monday-signal-llm/evidence/real-btdr-input.json'
    raw=source.read_bytes()
    saved=json.loads(raw)
    results=first_hour.evaluate(**saved['arguments'])
    evidence=dict(recorded_at=datetime.now(timezone.utc).isoformat(),
        kind='REAL_SAVED_INPUT_RETROSPECTIVE_NEW_CANDIDATE',
        natural_signal=False, production_writes=0, sdk_requests=0, paid_api_calls=0,
        source=str(source), source_sha256=sha256(raw).hexdigest(),
        source_provenance='Existing saved native sample; historical acquisition assertions not recaptured.',
        results=results, contract_selection='NOT_EXECUTED_NO_SAME_CONTRACT_HISTORICAL_QUOTES',
        page_delivery=None, live_eleven_checkpoint_acceptance=False,
        summary=[dict(variant=r['variant'],right=r['right'],state=r['state'],reasons=r['reasons']) for r in results])
    out=HERE/'evidence'/('saved-real-replay-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
    with out.open('x',encoding='utf-8') as stream:
        json.dump(evidence,stream,ensure_ascii=True,indent=2)
    print(json.dumps(dict(evidence=str(out),summary=evidence['summary'])))


if __name__=='__main__':
    main()
