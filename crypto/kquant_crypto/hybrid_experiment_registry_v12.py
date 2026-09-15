"""Preregistered prospective experiment identity; no outcome selection or trading."""
from __future__ import annotations
from datetime import datetime, UTC
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from .hybrid_delivery import encoded, lock

ARMS=('T','T_latency','T+B','T+M','T+B+M','T_exposure_control','Cash')


def validate_protocol(p):
    if p.get('scope') != 'SIMULATION_RESEARCH' or p.get('primary_arm') != 'T+B+M':
        raise ValueError('Fixed research release target required')
    if p.get('arms') != list(ARMS) or p.get('symbols') != ['BTCUSDT','ETHUSDT','SOLUSDT']:
        raise ValueError('Experiment population changed')
    if p.get('execution_target') not in ('LEGACY_BAR_PROXY_BASE_10_5','QUOTE_AWARE_SAMPLED_SIMULATION'):
        raise ValueError('Execution target must be explicit and isolated')
    for key in ('strategy_hash','cost_hash','feature_hash','risk_hash'):
        value=p.get(key)
        if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('Frozen hash required: '+key)
    if p.get('minimum_days') != 28 or p.get('maximum_days') != 84 or p.get('decision_checkpoint') != 'FINAL_DAY_84_ONLY':
        raise ValueError('Prospective inspection budget changed')
    if p.get('weekly_performance_promotion') is not False or p.get('outcome_selected_end_date') is not False:
        raise ValueError('Optional stopping not allowed')
    if p.get('historical_qualification') != 'EXPOSED_RESEARCH' or p.get('purge_overlap') is not True or p.get('embargo_seconds') != 21600:
        raise ValueError('Exposure/purge contract required')
    if p.get('new_entry_filter_enabled') is not False or p.get('live_enabled') is not False:
        raise ValueError('Registry cannot enable consumers')
    expected={'payoff':1.8,'base_pf':1.3,'double_cost_pf':1.05,'mean_net_r_gt':0,
              'portfolio_drawdown_max':.05,'total_trades_min':200,'per_mode_min':50,'per_claimed_cell_min':30}
    if p.get('inherited_targets') != expected:
        raise ValueError('Inherited target drift')
    if not p.get('ten_r_resolution'):
        if 'TEN_R_UNRESOLVED' not in p.get('performance_blockers',[]):
            raise ValueError('10R uncertainty must remain visible')
    return p


class Registry:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path)
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS experiments(id TEXT PRIMARY KEY, hash TEXT NOT NULL, body TEXT NOT NULL,
              registered_lower REAL NOT NULL, registered_upper REAL NOT NULL, clock_segment TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS starts(id TEXT PRIMARY KEY, d0 REAL NOT NULL, event_hash TEXT NOT NULL);
        ''')
        self.db.commit()

    def close(self): self.db.close()

    def register(self,identity,protocol,clock):
        validate_protocol(protocol)
        lo,hi=clock['received_at_lower'],clock['received_at_upper']
        if not all(type(x) in (int,float) and math.isfinite(x) for x in (lo,hi)) or not 0<lo<=hi or hi-lo>1 or not clock['clock_segment_id']:
            raise ValueError('Bounded observation clock required')
        body=encoded(protocol); digest=hashlib.sha256(body.encode()).hexdigest()
        with lock(self.path.with_suffix('.lock')),self.db:
            old=self.db.execute('SELECT hash FROM experiments WHERE id=?',(identity,)).fetchone()
            if old:
                if old[0]!=digest: raise ValueError('Frozen experiment cannot be revised in place')
                return digest
            self.db.execute('INSERT INTO experiments VALUES (?,?,?,?,?,?)',
                            (identity,digest,body,lo,hi,clock['clock_segment_id']))
        return digest

    def start(self,identity,event):
        """Only an already registered future data event can start observation.

        This establishes timing, not G2/G3 validity or probability permission.
        Caller evidence is retained; the registry never marks a financial gate.
        """
        row=self.db.execute('SELECT registered_upper,body FROM experiments WHERE id=?',(identity,)).fetchone()
        if not row: raise ValueError('Unregistered experiment')
        policy=json.loads(row[1])
        t=event['available_at']
        if type(t) not in (float,int) or not math.isfinite(t) or t<=row[0]:
            raise ValueError('Future post-registration data required')
        if event.get('execution_target')!=policy['execution_target'] or event.get('qualified') is not True:
            raise ValueError('Target mismatch or unavailable data')
        # Full UTC day after first qualified event; cannot choose a profitable tail.
        d0=(int(t)//86400+1)*86400
        digest=hashlib.sha256(encoded(event).encode()).hexdigest()
        with lock(self.path.with_suffix('.lock')),self.db:
            old=self.db.execute('SELECT d0,event_hash FROM starts WHERE id=?',(identity,)).fetchone()
            if old:
                if old!=(d0,digest): raise ValueError('Observation start already frozen')
                return d0
            self.db.execute('INSERT INTO starts VALUES (?,?,?)',(identity,d0,digest))
        return d0

    def report(self,identity):
        p=self.db.execute('SELECT hash,body FROM experiments WHERE id=?',(identity,)).fetchone()
        if not p: raise ValueError('Unknown experiment')
        start=self.db.execute('SELECT d0 FROM starts WHERE id=?',(identity,)).fetchone()
        policy=json.loads(p[1]); d0=start[0] if start else None
        return {'id':identity,'policy_hash':p[0],'d0':d0,
                'minimum_observation_end':d0+28*86400 if d0 else None,
                'final_decision_at':d0+84*86400 if d0 else None,
                'status':'REGISTERED_WAIT_FUTURE_DATA' if d0 is None else 'OBSERVATION_CLOCK_STARTED_NOT_GATES_PASSED',
                'performance_blockers':policy['performance_blockers'],
                'new_entry_filter_enabled':False,'live_enabled':False}
