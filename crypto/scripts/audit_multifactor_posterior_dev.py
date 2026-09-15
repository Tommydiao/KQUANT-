"""Saved-draw economic-support audit. Never refits or grants prediction validity."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_multifactor_artifact import inspect_artifact
from kquant_crypto.hybrid_dev_fit import audit, CONFIG, sha, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifact', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source, out = (ROOT/args.artifact).resolve(), (ROOT/args.output).resolve()
    allowed = ROOT/'outputs/hybrid_delivery'
    if not source.is_relative_to(allowed) or not out.is_relative_to(allowed):
        raise ValueError('Independent research paths required')
    meta = inspect_artifact(source,purpose='DEV_ONLY')
    out.mkdir(exist_ok=False)
    write_json(out/'audit_contract.json',{
        'method':'Saved draws only, empirical predictive mass below zero-exit economic bound',
        'scope':'DEV_ONLY','new_gate':False,'refit':False,
        'source_posterior_hash':meta['posterior_sha256'],'code_hash':sha(Path(__file__)),
        'warning':'Empirical zero impossible draws does not prove zero tail mass or calibration'})
    import arviz as az
    import numpy as np
    selected, checks = audit(json.loads(CONFIG.read_text()))
    lower = {r['label']['economic_signal_id']:r['lower_r'] for r in selected}
    rows = json.loads((source/'training_rows.json').read_text())
    if len(rows)!=27 or len({r['economic_signal_id'] for r in rows})!=27:
        raise ValueError('Unexpected model row identity')
    floor = np.asarray([lower[r['economic_signal_id']] for r in rows])
    trace = az.from_netcdf(source/'posterior.nc')
    groups = defaultdict(list)
    for i,row in enumerate(rows):
        groups[row['symbol']+':'+row['mode']].append(i)
    result = {'scope':'DEV_ONLY','refit':False,'source_audit':checks,
        'bound':'R >= -actual_entry*(1+fee)/frozen_BASE_unit_risk, exit price >=0',
        'independent_oos':False,'mean_validated':False,
        'profit_probability_validated':False,'tail_validated':False,'groups':{}}
    for kind in ('prior','posterior'):
        values = np.asarray(getattr(trace,kind+'_predictive')['outcome'])
        values = values.reshape(-1,len(rows))
        if not np.isfinite(values).all():
            raise ValueError('Nonfinite saved predictive draw')
        mass = np.mean(values<floor,axis=0)
        result[kind] = {'max_row_impossible_mass':float(mass.max()),
            'pooled_impossible_mass':float(mass.mean()),'per_row_impossible_mass':mass.tolist(),
            'draws_per_row':len(values)}
        for group, index in groups.items():
            entry = result['groups'].setdefault(group,{
                'observed_trades':len(index),
                'observed_mean_net_r':float(np.mean([rows[i]['net_r'] for i in index]))})
            entry[kind+'_predictive_quantiles'] = np.quantile(values[:,index],[.01,.5,.99]).tolist()
    result['posterior_hash_unchanged'] = sha(source/'posterior.nc') == meta['posterior_sha256']
    write_json(out/'report.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_audit','prior','posterior')}))


if __name__ == '__main__':
    main()
