"""Explain native-basis failures from original as-of bar versions; read-only."""
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, UTC, datetime
import json
from pathlib import Path
import sqlite3
from time import monotonic
from bootstrap import activate
HERE, BASE, ROOT = activate()
from kquant import options_one_minute as common
from kquant.options_opening_trend import complete_minutes
from kquant.options_minute_admission import classify
from kquant.market_clock import session_bounds_utc

replay = HERE.parents[1]/'evidence/replay-2026-10-15-145659'
positions = json.loads((replay/'positions.json').read_text(encoding='utf-8'))
samples = {(r['symbol'],r['checkpoint']):r for r in positions
    if 'INTRADAY_NATIVE_PRICE_BASIS_UNVERIFIED' in r.get('reasons',[])}
by_symbol = defaultdict(list)
for key,row in samples.items():
    by_symbol[key[0]].append(row)
mapping = json.loads((ROOT/'runtime/config/new-epoch-store-paths.json').read_text())
minute = Path(mapping['stores']['minute'])
opening,closing_at = session_bounds_utc(date(2026,10,15))
report,counts = [],Counter()
with closing(sqlite3.connect(minute.as_uri()+'?mode=ro',uri=True,timeout=.2)) as db:
    db.execute('PRAGMA query_only=ON')
    for symbol,rows in by_symbol.items():
        end = monotonic()+3
        db.set_progress_handler(lambda:int(monotonic()>end),1000)
        raw=db.execute('''SELECT payload_json FROM one_minute_bars WHERE session=? AND symbol=?
            AND open_at>=? AND open_at<? ORDER BY received_at LIMIT 2001''',
            ('2026-10-15',symbol,opening.isoformat(),'2026-10-15T14:00:00+00:00')).fetchall()
        if len(raw)>2000:
            raise ValueError('VERSION_BOUND_EXCEEDED')
        bars=[json.loads(r[0]) for r in raw]
        for row in rows:
            now=common.timestamp(row['comparison']['s1']['evaluated_at'])
            until=common.timestamp(row['checkpoint'])
            selected,missing=complete_minutes(bars,symbol=symbol,opening=opening,until=until,now=now,price_only=True)
            bad=[]
            for bar in selected:
                evidence=bar.get('sdk_evidence',{})
                native=lambda b: b.get('sdk_evidence',{}).get('adjustment')=='NoAdjust' and b.get('sdk_evidence',{}).get('interface') in {'QuoteContext.candlesticks','QuoteContext.history_candlesticks_by_offset'}
                if native(bar):
                    continue
                alternatives=[]
                for candidate in bars:
                    if candidate.get('open_at')!=bar['open_at'] or not native(candidate):
                        continue
                    _,reason=classify(candidate,symbol=symbol,opening=opening,until=until,now=now,price_only=True)
                    if not reason and all(candidate[k]==bar[k] for k in ('open','high','low','close')):
                        alternatives.append(common.digest(candidate))
                bad.append(dict(open_at=bar['open_at'],selected_interface=evidence.get('interface'),
                    selected_adjustment=evidence.get('adjustment'),selected_hash=common.digest(bar),
                    equal_price_legal_native_alternatives=alternatives))
            affected=bool(bad) and all(b['equal_price_legal_native_alternatives'] for b in bad) and not missing
            counts['EQUAL_PRICE_NATIVE_AVAILABLE_BUT_NOT_SELECTED' if affected else 'NO_COMPLETE_NATIVE_ALTERNATIVE']+=2
            report.append(dict(symbol=symbol,checkpoint=row['checkpoint'],original_asof=now.isoformat(),
                all_missing_basis_recoverable_without_new_data=affected,bad_slots=bad,missing_slots=missing))
out=dict(observed_at=datetime.now(UTC).isoformat(),direction_counts=dict(counts),
    original_native_failure_directions=654,positions=report,production_writes=0,sdk_calls=0,
    source_decision_replay='NO_CONFLICT_DECISIONS_USED_DIAGNOSTIC_ONLY')
target=HERE/'evidence/native-selection-audit.json'
with target.open('x',encoding='utf-8') as stream:json.dump(out,stream,indent=2)
print(json.dumps(dict(direction_counts=dict(counts),symbol_checkpoint_positions=len(report))))
