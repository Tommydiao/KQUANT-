"""One preregistered actual-history MC path smoke run, not risk admission."""
from dataclasses import asdict
from pathlib import Path
import argparse
import json
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_delivery import atomic_json, sha
from kquant_crypto.hybrid_mc_history_v12 import load_authorized, AUTHORIZED_END
from kquant_crypto.hybrid_mc_paths_v12 import generate_paths, SYMBOLS


def run(output):
    out=(ROOT/output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery'):raise ValueError('Independent output only')
    out.mkdir(parents=True,exist_ok=False)
    # Fixed before loading: last 30 authorized DEV days plus predecessor bar.
    start=AUTHORIZED_END-30*86400-300
    atomic_json(out/'preregistration.json',{'scope':'DEV_ONLY_PATH_INPUT_ENGINEERING',
        'start':start,'end':AUTHORIZED_END,'selection':'last_30_authorized_days_plus_predecessor_no_return_selection',
        'paths':32,'block_bars':12,'horizon_bars':72,'seed':20260906,'risk_admission':False,
        'source_hashes':{s:sha(ROOT/s) for s in ('kquant_crypto/hybrid_mc_history_v12.py','kquant_crypto/hybrid_mc_paths_v12.py','scripts/run_hybrid_mc_history_v12.py')}})
    t=time.monotonic();history,spec,audit=load_authorized(ROOT,start=start,end=AUTHORIZED_END)
    anchors={s:history[-1]['bars'][s]['close'] for s in SYMBOLS}
    paths=generate_paths(history,anchors,spec)
    repeated=generate_paths(history,anchors,spec)
    if paths!=repeated:raise ValueError('Non-reproducible common path bank')
    atomic_json(out/'paths.json',paths);atomic_json(out/'input_audit.json',audit)
    report={'scope':'ACTUAL_EXPOSED_HISTORY_INPUT_ENGINEERING','batches':len(history),'spec':asdict(spec),
            'path_bank_hash':paths['path_bank_hash'],'repeated_exact':True,'elapsed_seconds':time.monotonic()-t,
            'G4_passed':False,'risk_probabilities':None,'admission':'ABSTAIN','sizing_enabled':False,
            'limitations':['OHLC proxy, not simultaneous executable bid paths','Unconditional blocks; not calibrated regime risk',
                           'No current portfolio or actual pending risk simulated','32-path smoke, not 5000-path acceptance'],
            'files':{n:sha(out/n) for n in ('preregistration.json','paths.json','input_audit.json')}}
    atomic_json(out/'report.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();run(a.output)
