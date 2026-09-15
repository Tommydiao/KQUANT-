"""Numerical stability on saved common paths, not market risk calibration."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_mc_numerics_v12 import upper_event_probability


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();source=(ROOT/args.source).resolve();out=(ROOT/args.output).resolve()
    parent=ROOT/'outputs/hybrid_delivery'
    if not source.is_relative_to(parent) or not out.is_relative_to(parent):raise ValueError('Research paths required')
    report=json.loads((source/'report.json').read_text())
    if report['status']!='COMPLETED' or report['completed']!=5000:raise ValueError('Require completed5000 run')
    if sha(source/'path_results.jsonl')!=report['path_results_hash']:raise ValueError('Path hash mismatch')
    rows=[json.loads(s) for s in (source/'path_results.jsonl').read_text().splitlines()]
    if [r['path_id'] for r in rows]!=list(range(5000)):raise ValueError('Missing/duplicate path')
    out.mkdir(exist_ok=False)
    outputs={}
    for candidate in rows[0]['results']:
        values=np.asarray([r['results'][candidate]['net_change'] for r in rows])
        baseline=np.asarray([r['results']['ORIGINAL']['net_change'] for r in rows])
        drawdowns=np.asarray([r['results'][candidate]['max_drawdown_fraction'] for r in rows])
        if not np.isfinite(values).all() or not np.isfinite(drawdowns).all():raise ValueError('Nonfinite path results')
        delta=values-baseline
        outputs[candidate]={
            'mean_net_change':float(values.mean()),'mean_paired_change_vs_original':float(delta.mean()),
            'paired_numerical_standard_error':float(delta.std(ddof=1)/np.sqrt(len(delta))),
            'drawdown_quantiles':np.quantile(drawdowns,[.5,.9,.99]).tolist(),
            'prefix_stability':{str(n):{'net_change_quantiles':np.quantile(values[:n],[.1,.5,.9]).tolist(),
                'loss_fraction':float(np.mean(values[:n]<0))} for n in (1000,2500,5000)}}
        outputs[candidate]['numerical_event_bounds']={
            event:upper_event_probability(sum(bool(r['results'][candidate][event]) for r in rows),
                                          len(rows),family_alpha=.05,comparisons=15)
            for event in ('stop_hit','budget_exceeded','open_at_horizon')}
    result={'scope':'DEV_ONLY','market_snapshots':1,'simulated_paths':5000,
            'source_report_hash':sha(source/'report.json'),'code_hash':sha(Path(__file__)),
            'policy_results':outputs,'market_calibration':False,'candidate_selection':False,
            'event_error_budget':{'family_alpha':.05,'comparisons':15,'scope':'5 policies x3 events, conditional Monte Carlo only'},
            'limitation':'Numerical Monte Carlo error conditional on this empirical path law, not uncertainty about actual future market risk',
            'performance':'PERFORMANCE_UNPROVEN'}
    write_json(out/'report.json',result);print(json.dumps(result))


if __name__=='__main__':main()
