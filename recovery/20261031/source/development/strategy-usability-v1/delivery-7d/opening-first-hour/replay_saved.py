"""Real historical input, current isolated window math; never publish replay."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import first_hour

here = Path(__file__).resolve().parent
source = here.parent/'monday-signal-llm/evidence/real-btdr-input.json'
raw = source.read_bytes()
saved = json.loads(raw)
args = saved['arguments']
results = first_hour.evaluate(**args)
value = dict(captured_at=datetime.now(timezone.utc).isoformat(),
    kind='REAL_SAVED_INPUT_RETROSPECTIVE_NEW_WINDOW', natural_signal=False,
    production_writes=0, sdk_requests=0, source=str(source),
    source_sha256=hashlib.sha256(raw).hexdigest(), results=results,
    contract_selection='NOT_EXECUTED_NO_HISTORICAL_QUOTE_SUBSTITUTION',
    page_delivery=None, live_eleven_checkpoint_acceptance=False)
with (here/'saved-real-replay.json').open('x', encoding='utf-8') as stream:
    json.dump(value, stream, ensure_ascii=False, indent=2)
print(json.dumps([{'variant': r['variant'], 'right': r['right'], 'state': r['state'],
                   'reasons': r['reasons']} for r in results]))
