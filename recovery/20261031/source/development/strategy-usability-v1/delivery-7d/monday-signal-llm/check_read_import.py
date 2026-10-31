"""Fresh-interpreter read-only dependency measurement, no DB/model/SDK calls."""
import argparse
import importlib
import json
import sys
from time import perf_counter
from bootstrap import activate

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--new',action='store_true')
args=parser.parse_args()
HERE,_,_=activate()
import kquant
if args.new:
    for directory in ('projection-followup','budget-followup','delivery-followup','read-followup'):
        kquant.__path__.insert(0,str(HERE/directory/'patches/kquant'))
import kquant.options_opening_trend_store
started=perf_counter()
module=importlib.import_module('kquant.options_research_ai_store')
report=dict(test_only=True, variant='READ_SPLIT' if args.new else 'FROZEN_868_BASELINE',
    module=str(module.__file__),elapsed_ms=(perf_counter()-started)*1000,
    imported_paid_client='kquant.options_research_ai' in sys.modules,
    imported_http_client='requests' in sys.modules,
    imported_legacy_copilot='kquant.options_signal_copilot' in sys.modules,
    sdk_calls=0,model_calls=0,production_writes=0)
if args.new:
    assert not any(report[key] for key in ('imported_paid_client','imported_http_client','imported_legacy_copilot'))
target=HERE/'evidence'/('read-import-new.json' if args.new else 'read-import-before.json')
with target.open('x',encoding='utf-8') as stream:
    json.dump(report,stream,indent=2)
print(json.dumps(report))
