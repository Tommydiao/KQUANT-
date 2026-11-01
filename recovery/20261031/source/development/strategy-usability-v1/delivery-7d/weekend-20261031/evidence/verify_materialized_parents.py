"""Import explicit parent bindings from a code-only temporary release tree."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import argparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
parser = argparse.ArgumentParser()
parser.add_argument('--mapping', default='iteration-parent-bound-source-map-20261101.json')
parser.add_argument('--output', default='iteration-materialized-parent-imports-20261101.json')
parser.add_argument('--agent', action='store_true')
args = parser.parse_args()
mapping = json.loads((HERE/args.mapping).read_text())
with tempfile.TemporaryDirectory(prefix='kquant-parent-import-') as temporary:
    target = Path(temporary)
    for row in mapping['sources']:
        source = ROOT / row['source']['path']
        if sha256(source.read_bytes()).hexdigest() != row['source']['sha256']:
            raise RuntimeError('SOURCE_DRIFT:' + row['target'])
        destination = target / row['target']
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    child = '''
import importlib.abc, sys
class NoAssembly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'assembly' or fullname.startswith('assembly.') or fullname == 'bootstrap':
            raise RuntimeError('TEST_BOOTSTRAP_FORBIDDEN')
sys.meta_path.insert(0, NoAssembly())
from kquant import options_minute_admission, options_opening_trend_coverage, options_opening_trend_projection
assert options_minute_admission.parent.__name__ == 'kquant._first_hour_parent_admission'
assert options_opening_trend_coverage.parent.__name__ == 'kquant._first_hour_parent_coverage'
assert options_opening_trend_projection.parent.__name__ == 'kquant._first_hour_parent_projection'
print('EXPLICIT_PARENT_IMPORTS_PASS')
'''
    if args.agent:
        child += '''
from kquant import options_research_ai, options_research_ai_store
from kquant.research_review_v2 import VERSION
from kquant.agent_task_contract import CAPABILITIES
assert VERSION == 'research_review_v2'
assert not CAPABILITIES['real_trading']
print('AGENT_RUNTIME_IMPORTS_PASS_NO_CALLS')
'''
    run = subprocess.run([sys.executable, '-c', child], cwd=target,
                         capture_output=True, text=True, timeout=30)
report = dict(observed_at=datetime.now(timezone.utc).isoformat(),
              returncode=run.returncode, stdout=run.stdout, stderr=run.stderr,
              copied_python_files=len(mapping['sources']), business_databases_opened=False,
              limitation='Code-only cold imports, not Supervisor/Worker or release acceptance.')
(HERE/args.output).write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report))
sys.exit(run.returncode)
