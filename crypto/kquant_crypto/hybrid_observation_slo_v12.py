"""Durable predeclared observation-seconds denominator, independent of labels."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from .hybrid_delivery import encoded, lock
from .hybrid_quote_contract_v12 import SYMBOLS, describe_quote, covered_seconds


class ObservationSLO:
    def __init__(self, path, *, window_start, window_end, registered_before, policy_hash):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if not all(type(t) in (int,float) and math.isfinite(t) for t in (window_start,window_end,registered_before)):
            raise ValueError('Finite planned observation bounds required')
        if not 0 < registered_before <= window_start < window_end or len(policy_hash)!=64:
            raise ValueError('Preregister before observation with frozen policy hash')
        self.window_start,self.window_end=window_start,window_end
        self.binding=encoded(dict(start=window_start,end=window_end,registered_before=registered_before,policy_hash=policy_hash))
        self.db=sqlite3.connect(self.path)
        existing={x[0] for x in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if existing-{'slo_binding','slo_quotes'}:
            self.db.close();raise ValueError('Independent SLO database only')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS slo_binding(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS slo_quotes(identity TEXT PRIMARY KEY,hash TEXT NOT NULL,symbol TEXT NOT NULL,
              receipt REAL NOT NULL,expires REAL,eligible INTEGER NOT NULL,reason TEXT NOT NULL);
        ''')
        old=self.db.execute('SELECT body FROM slo_binding WHERE id=1').fetchone()
        if old and old[0]!=self.binding:
            self.db.close();raise ValueError('Cannot alter observation denominator after registration')
        self.db.execute('INSERT OR IGNORE INTO slo_binding VALUES(1,?)',(self.binding,));self.db.commit()

    def close(self):self.db.close()

    def record(self, identity, quote):
        payload=encoded(quote);digest=hashlib.sha256(payload.encode()).hexdigest()
        receipt=quote.get('received_at_upper')
        if not identity or type(receipt) not in (int,float) or not math.isfinite(receipt):
            raise ValueError('Explicit identity and receiver upper bound required')
        detail=describe_quote(quote)
        eligible=detail['eligible_sample']
        # The sample becomes available at the conservative receipt upper bound;
        # source event + freshness is its expiry, not receipt + freshness.
        expiry=quote['source_time']+30 if eligible else None
        with lock(self.path.with_suffix('.lock')),self.db:
            old=self.db.execute('SELECT hash FROM slo_quotes WHERE identity=?',(identity,)).fetchone()
            if old:
                if old[0]!=digest:raise ValueError('Immutable sample changed')
                return False
            self.db.execute('INSERT INTO slo_quotes VALUES(?,?,?,?,?,?,?)',
                            (identity,digest,quote.get('symbol','UNKNOWN'),receipt,expiry,int(eligible),encoded(detail['reasons'])))
        return True

    def report(self, *, observed_until):
        if type(observed_until) not in (int,float) or not math.isfinite(observed_until) or observed_until<self.window_start:
            raise ValueError('Explicit elapsed observation boundary required')
        end=min(observed_until,self.window_end)
        rows=self.db.execute('SELECT symbol,receipt,expires,eligible FROM slo_quotes ORDER BY receipt').fetchall()
        counts={s:{'accepted':0,'rejected':0} for s in SYMBOLS}
        intervals={s:[] for s in SYMBOLS}
        for s,t,expiry,ok in rows:
            if s not in counts or t>end:continue
            if self.window_start <= t < end:
                counts[s]['accepted' if ok else 'rejected']+=1
            if ok and t<end and expiry>t: intervals[s].append((t,min(end,expiry)))
        per_symbol={s:covered_seconds(v,self.window_start,self.window_end) for s,v in intervals.items()}
        # Merge overlapping samples first: cost grows linearly after sorting,
        # not quadratically with the number of messages in a 72h window.
        edges=[]
        for s,parts in intervals.items():
            merged=[]
            for a,b in sorted(parts):
                a,b=max(a,self.window_start),min(b,end)
                if a>=b:continue
                if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
                else:merged.append((a,b))
            edges.extend((a,s,1) for a,b in merged)
            edges.extend((b,s,-1) for a,b in merged)
        joint=[];active={s:0 for s in SYMBOLS};previous=self.window_start
        for at,s,delta in sorted(edges):
            if at>previous and all(v>0 for v in active.values()):joint.append((previous,at))
            active[s]+=delta;previous=at
        return {'binding':json.loads(self.binding),'counts':counts,'per_symbol':per_symbol,
                'all_symbols':covered_seconds(joint,self.window_start,self.window_end),
                'observed_until':end,'window_complete':observed_until>=self.window_end,
                'minimum_72h_window':self.window_end-self.window_start>=72*3600,
                'denominator':'FULL_PREREGISTERED_REQUIRED_SECONDS_INCLUDING_GAPS_AND_NOT_YET_OBSERVED',
                'count_scope':'RECEIPTS_IN_HALF_OPEN_OBSERVED_WINDOW',
                'coverage_scope':'VALID_INTERVAL_INTERSECTION_WITH_REGISTERED_WINDOW',
                'protection_availability':None,'protection_reason':'Separate protection acknowledgement/timing evidence required',
                'G3_passed':False,'natural_labels_not_inferred_from_quotes':True}
