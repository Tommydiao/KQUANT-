"""Research exit wrapper; original portfolio/risk implementation stays unchanged."""
from .candidate_simulation import CandidatePortfolio
from .hybrid_exit_research import structural_exit,net_target_reference
from .candidate_policy import digest
from .strategy_dual_mode_v1 import Bar
from copy import deepcopy
from dataclasses import asdict


class ResearchPortfolio(CandidatePortfolio):
    def __init__(self, policy, rules, *, exit_candidate, cost_multiplier=1):
        if exit_candidate not in ('ORIGINAL','FIXED_2_5R','FIXED_3R','T1','T2'):
            raise ValueError('Unregistered research exit policy')
        policy=deepcopy(policy)
        policy['original_policy_hash']=policy['policy_hash']
        policy['strategy_version']='hybrid_exit_research_dev_v1:'+exit_candidate
        policy['policy_hash']=digest([policy['original_policy_hash'],policy['strategy_version']])
        super().__init__(policy,rules,execution='ohlcv',cost_multiplier=cost_multiplier)
        self.exit_candidate=exit_candidate
        self.research_hours={s:[] for s in policy['symbols']}

    def _enter(self,symbol,reference,time,exit_reference=None):
        pending=self.pending[symbol]
        if pending['mode']=='UP_TREND' and self.exit_candidate.startswith('FIXED'):
            pending['target']=net_target_reference(reference*1.0005,pending['unit_net_risk'],
                2.5 if self.exit_candidate=='FIXED_2_5R' else 3.)
        super()._enter(symbol,reference,time,exit_reference)

    def _exit(self,symbol,reference,time,reason):
        position=self.positions.get(symbol)
        if (position and position['mode']=='UP_TREND' and self.exit_candidate in ('T1','T2')
                and reason in ('target','gap_target','entry_gap_target','timeout','mode_invalidated')):
            # Ignore only the explicitly replaced trend exits. Stops, data gaps,
            # daily risk and terminal exits always retain the inherited path.
            if self.exits.get(symbol)==reason:
                self.exits.pop(symbol)
            return
        super()._exit(symbol,reference,time,reason)

    def on_closed_batch(self,bars,hourly,now,allow_entries=True):
        super().on_closed_batch(bars,hourly,now,allow_entries)
        for symbol,hour in hourly.items():
            history=self.research_hours[symbol]
            if history and hour.start<=history[-1].start:
                continue
            if history and hour.start!=history[-1].start+3600:
                history=[]
            self.research_hours[symbol]=(history+[hour])[-7:]
        if self.exit_candidate not in ('T1','T2'):
            return
        for symbol,position in self.positions.items():
            if position['mode']!='UP_TREND':
                continue
            position['profit_target_enabled']=False
            position['timeout_enabled']=False
            position['research_exit_policy']=self.exit_candidate
            position['bars_held']=max(0,(now-position['entry_time'])//300)
            if self.exits.get(symbol) in ('timeout','mode_invalidated'):
                self.exits.pop(symbol)
            if symbol in hourly:
                decision=structural_exit(self.exit_candidate,'UP_TREND',
                    self.research_hours[symbol],now,position['stop'],self.kernels[symbol].hour.atr)
                position['stop']=decision['stop_next_bar']
                if decision['exit_next_bar'] and symbol not in self.exits:
                    self.exits[symbol]='structure_invalidated'
            # Structural replacement cannot clear an existing daily-risk pause.
            if self.day_paused:
                self.exits[symbol]='daily_loss'

    def on_quote(self,*args,**kwargs):
        raise ValueError('Research OHLC portfolio cannot impersonate quote execution')

    def snapshot(self):
        return {**super().snapshot(),'research_exit_candidate':self.exit_candidate,
                'research_hours_serialized':{s:[asdict(b) for b in rows] for s,rows in self.research_hours.items()}}

    def restore(self,state):
        if state.get('research_exit_candidate')!=self.exit_candidate:
            raise ValueError('Research policy mismatch')
        base={k:v for k,v in state.items() if k not in ('research_exit_candidate','research_hours_serialized')}
        super().restore(base)
        self.research_hours={s:[Bar(**b) for b in rows] for s,rows in state['research_hours_serialized'].items()}
