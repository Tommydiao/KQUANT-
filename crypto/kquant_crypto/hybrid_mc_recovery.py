"""Validate immutable MC prefixes before resuming in a new output directory."""
import json
import math


def read_prefix(path, candidates, maximum):
    if not path.exists():
        return [], b''
    raw = path.read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise ValueError('Incomplete final record retained; manual audit required')
    rows = []
    for index, line in enumerate(raw.splitlines()):
        row = json.loads(line)
        if row['path_id'] != index or index >= maximum or set(row['results']) != set(candidates):
            raise ValueError('Noncontiguous or incompatible path prefix')
        if not isinstance(row['sampling_hash'], str) or len(row['sampling_hash']) != 64:
            raise ValueError('Invalid sampling hash')
        for result in row['results'].values():
            for key in ('net_change', 'max_incremental_nav_drawdown', 'max_historical_nav_drawdown'):
                if type(result[key]) not in (int, float) or not math.isfinite(result[key]):
                    raise ValueError('Invalid path metric')
            if not 0 <= result['max_incremental_nav_drawdown'] <= result['max_historical_nav_drawdown'] < 1:
                raise ValueError('Invalid drawdown bases')
            if result['terminal_mark_only'] is not True or type(result['budget_exceeded']) is not bool:
                raise ValueError('Invalid path semantics')
        rows.append(row)
    return rows, raw


def read_pair_prefix(path, maximum):
    """Validate paired pending-risk rows while preserving original bytes."""
    if not path.exists():return [],b''
    raw=path.read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise ValueError('Incomplete final record retained; manual audit required')
    rows=[]
    for index,line in enumerate(raw.splitlines()):
        row=json.loads(line)
        if row['path_id']!=index or index>=maximum or set(row['results'])!={'WITH_PLAN','WITHOUT_PLAN'}:
            raise ValueError('Incompatible paired prefix')
        sampling=row['sampling_hash']
        if not isinstance(sampling,str) or len(sampling)!=64 or any(c not in '0123456789abcdef' for c in sampling):
            raise ValueError('Invalid sampling identity')
        if row['runtime_enabled'] is not False or row['calibrated_risk'] is not False:
            raise ValueError('Unexpected paired permissions')
        for name,r in row['results'].items():
            for key in ('net_change','max_incremental_nav_drawdown'):
                if type(r[key]) not in (int,float) or not math.isfinite(r[key]):raise ValueError('Nonfinite pair')
            if not 0<=r['max_incremental_nav_drawdown']<1:raise ValueError('Invalid drawdown')
            for key in ('open_at_horizon','pending_at_horizon','target_plan_fills'):
                if type(r[key]) is not int or r[key]<0:raise ValueError('Invalid event count')
            if r['target_plan_fills']>(1 if name=='WITH_PLAN' else 0):raise ValueError('Illegal target fill')
            if type(r['booked_risk_ratio_exceeded']) is not bool or r['terminal_mark_only'] is not True:
                raise ValueError('Invalid paired semantics')
            if any(type(v) is not int or v<0 for v in r['exit_reasons'].values()):raise ValueError('Invalid exits')
        difference=row['paired_net_change']
        if type(difference) not in (int,float) or not math.isfinite(difference) or not math.isclose(
                difference,row['results']['WITH_PLAN']['net_change']-row['results']['WITHOUT_PLAN']['net_change'],
                rel_tol=1e-12,abs_tol=1e-9):raise ValueError('Paired difference mismatch')
        rows.append(row)
    return rows,raw
