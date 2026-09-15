"""Bounded-memory common paths conditioned on historical BTC pre-block regime."""
import random
from .hybrid_mc_paths_v12 import audit_history,SYMBOLS,STEP,digest
from .strategy_dual_mode_v1 import Bar


def conditioned_paths(history,anchors,spec,regime):
    audit=audit_history(history,spec)
    eligible=[i for i in audit['eligible_block_starts'] if history[i].get('regime_before')==regime]
    if len(eligible)<30:
        raise ValueError('Fewer than30 regime-matched blocks; simulation unavailable')
    if set(anchors)!=set(SYMBOLS) or any(v<=0 for v in anchors.values()):
        raise ValueError('Complete positive anchors required')
    rng=random.Random(spec.seed)
    for path_id in range(spec.paths):
        previous=dict(anchors); batches=[]; starts=[]
        while len(batches)<spec.horizon_bars:
            index=rng.choice(eligible); starts.append(index)
            for offset in range(min(spec.block_bars,spec.horizon_bars-len(batches))):
                source=history[index+offset]; prior=history[index+offset-1]
                now=spec.as_of+len(batches)*STEP; bars={}
                for symbol in SYMBOLS:
                    b=source['bars'][symbol]
                    opening=previous[symbol]*b['open']/prior['bars'][symbol]['close']
                    closing=opening*b['close']/b['open']
                    # Valid source bounds can differ by an ULP after ratio
                    # reconstruction when source high equals open or close.
                    high=max(opening,closing,opening*b['high']/b['open'])
                    low=min(opening,closing,opening*b['low']/b['open'])
                    bars[symbol]=Bar(now,opening,high,low,closing,0)
                    previous[symbol]=bars[symbol].close
                batches.append(bars)
        yield {'path_id':path_id,'batches':batches,'block_starts':starts,
               'sampling_hash':digest([spec.seed,path_id,starts]),
               'eligible_blocks':len(eligible),'regime':regime,
               'limitation':'BTC pre-block regime conditioning; no calibrated transition model; volume unused proxy0'}
