"""Read only the known copilot schema; never load credentials or business payloads."""
from contextlib import closing
from datetime import UTC,datetime
import json
from pathlib import Path
import sqlite3
from time import monotonic
from bootstrap import activate
HERE,_,ROOT=activate()
roles=json.loads((ROOT/'runtime/config/new-epoch-store-paths.json').read_text(encoding='utf-8-sig'))['stores']
path=Path(roles['signal_copilot'])
with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
    until=monotonic()+.3
    db.set_progress_handler(lambda:int(monotonic()>until),1000)
    schema=db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name LIKE 'llm_%' OR name LIKE 'idx_llm_%' OR name='ai_assessments' ORDER BY type,name").fetchall()
    reservations=db.execute('SELECT count(*) FROM llm_budget_reservations').fetchone()[0] if any(r[1]=='llm_budget_reservations' for r in schema) else None
value={'observed_at':datetime.now(UTC).isoformat(),'path':str(path),'schema':schema,'reservation_count':reservations,'read_only':True,'credentials_read':False}
(HERE/'evidence/copilot-ai-schema.json').write_text(json.dumps(value,indent=2),encoding='utf-8')
print(json.dumps({'schema_objects':[r[1] for r in schema],'reservations':reservations,'read_only':True}))
