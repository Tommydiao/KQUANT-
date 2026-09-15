"""Pure research-only exit instructions shared by future replay/MC consumers."""
import math


def net_target_reference(actual_entry, base_unit_risk, multiple, fee=.001, slip=.0005):
    if not all(math.isfinite(v) and v>0 for v in (actual_entry,base_unit_risk,multiple)):
        raise ValueError('Invalid target inputs')
    if not 0<=fee<1 or not 0<=slip<1:
        raise ValueError('Invalid execution costs')
    return (actual_entry*(1+fee)+multiple*base_unit_risk)/((1-fee)*(1-slip))


def structural_exit(candidate, mode, hours, as_of, previous_stop, atr14):
    if candidate not in ('T1','T2'):
        raise ValueError('Unregistered exit candidate')
    if not math.isfinite(previous_stop) or previous_stop<=0:
        raise ValueError('Invalid initial protection')
    result = {'candidate':candidate,'scope':'DEV_ONLY','execution_enabled':False,
              'as_of':as_of,'effective_at':as_of,'exit_next_bar':False,
              'stop_next_bar':previous_stop,'status':'UNCHANGED'}
    if mode != 'UP_TREND':
        result['reason'] = 'PRESERVE_ORIGINAL_NON_TREND_POLICY'
        return result
    closed = [b for b in hours if b.start+3600<=as_of][-7:]
    if (len(closed)!=7 or closed[-1].start+3600!=as_of
            or any(b.start-a.start!=3600 for a,b in zip(closed,closed[1:]))):
        result.update(status='UNAVAILABLE',reason='CONTIGUOUS_CLOSED_HOURS_REQUIRED')
        return result
    floor = min(b.low for b in closed[:-1])
    result.update(status='AVAILABLE',structure_floor=floor,
                  exit_next_bar=closed[-1].close<floor,
                  reason='STRUCTURE_LOST' if closed[-1].close<floor else 'STRUCTURE_INTACT')
    if candidate=='T2':
        if atr14 is None or not math.isfinite(atr14) or atr14<=0:
            result.update(status='UNAVAILABLE',reason='ATR_UNAVAILABLE_KEEP_OLD_PROTECTION')
            return result
        result['stop_next_bar'] = max(previous_stop,floor-.25*atr14)
    return result
