"""Read-only actual main-role metadata comparison, not launch authorization."""
from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
from time import monotonic

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
spec = importlib.util.spec_from_file_location('real_metadata_probe',
    HERE/'metadata-followup/patches/kquant/recovery_runtime_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
baseline = json.loads((ROOT/'source/evidence/new-machine-20261008/portable-activation/bound-9cecac4ccc5f768e/main-activation.json').read_bytes())
request = dict(role='main', path=baseline['database_path'], watermarks=baseline['watermarks'],
    metadata_baseline=dict(path=baseline['baseline_snapshot'], file_identity=baseline['baseline_file_identity']))
tracker = {'database_opens': 0, 'metadata_baseline_opens': 0}
actual = probe.observe_database(request, [str(ROOT)], monotonic()+2, tracker)
assert actual['file_identity'] == baseline['file_identity']
assert actual['schema_sha256'] == baseline['schema_sha256']
for got, expected in zip(actual['watermarks'], baseline['watermarks']):
    assert got['current'] >= expected['minimum']
    assert got['prefix_rows'] == expected['prefix_rows']
    if got['table'] == 'stock_watchlist_members':
        assert got['watchlist_timestamp_metadata_compatible'] is True
    else:
        assert got['prefix_sha256'] == expected['prefix_sha256']
result = dict(observed_at=datetime.now(UTC).isoformat(), real_main_role=actual,
    tracker=tracker, read_only=True, business_writes=0, database_copies=0,
    owner_approval_created=False, full_five_role_launch_gate_pass=False,
    scope='Actual narrow timestamp compatibility only; launch still requires exact candidate acceptance')
with (HERE/'evidence/real-restart-metadata-20261018.json').open('x', encoding='utf-8') as stream:
    json.dump(result, stream, indent=2)
print(json.dumps(result))
