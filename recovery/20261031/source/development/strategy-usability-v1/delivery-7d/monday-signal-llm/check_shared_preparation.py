"""Compare the unchanged accepted model against local preparation optimization."""
import importlib.util
import json
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from time import perf_counter
from bootstrap import activate
HERE, BASE, _=activate()
from kquant import options_intraday_comparison as changed
from kquant import options_one_minute as common
spec=importlib.util.spec_from_file_location('kquant._accepted_comparison',BASE/'kquant/options_intraday_comparison.py')
old=importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
saved=json.loads((HERE/'evidence/real-btdr-input.json').read_text(encoding='utf-8'))
original=saved['arguments']
scenarios={}
for name in ('real_original','missing_minute','expired','reference_missing','currency_invalid'):
    args=deepcopy(original)
    for key in ('opening','closing','now','checkpoint'):
        args[key]=common.timestamp(args[key])
    if name=='missing_minute':
        slot=args['bars'][0]['open_at']
        args['bars']=[x for x in args['bars'] if x['open_at']!=slot]
    elif name=='expired':
        args['now']=args['checkpoint']+timedelta(seconds=301)
    elif name=='reference_missing':
        args['reference']={}
    elif name=='currency_invalid':
        args['reference']['raw_quote']['currency']='UNKNOWN'
    before=old.evaluate_comparison_pair(**args)
    after=changed.evaluate_comparison_pair(**args)
    assert before==after, name
    timings={}
    for label,model in (('accepted',old),('local',changed)):
        start=perf_counter()
        for _ in range(30):
            model.evaluate_comparison_pair(**args)
        timings[label]=(perf_counter()-start)*1000/30
    scenarios[name]={'equal':True,'mean_ms':timings,'s1_states':[x['strategy_comparison']['s1']['state'] for x in after]}
result={'real_input_hash':sha256((HERE/'evidence/real-btdr-input.json').read_bytes()).hexdigest(),
    'scenarios':scenarios,'live_writes':0,'scope':'Single-symbol saved-input CPU comparison, not full pipeline P95.'}
(HERE/'evidence/shared-preparation-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
