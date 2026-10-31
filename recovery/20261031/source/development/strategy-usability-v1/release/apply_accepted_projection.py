import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r'E:\kquant 1007\KQUANT-Resume-Latest')
BASE = ROOT / 'source/development/workspace'
HERE = Path(__file__).parent / 'local-candidate-6ac8a5653d14a392'
ENTRY = BASE / 'config/local_workspace_entry.json'
def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p, obj):
    p = Path(p)
    tmp = p.with_suffix(p.suffix + '.pending')
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=True), encoding='utf-8')
    os.replace(tmp, p)

projection = read(HERE / 'deployment-projection.json')
assert sha(HERE / 'deployment-projection.json') == 'af579d27c896211e2dba1c177b9f0dca2fa96bede5983bac8ad791d1dfeb129f'
assert sha(ENTRY) == projection['base_entry_sha256'], 'BASE_ENTRY_DRIFT'
assert sha(HERE / 'changed-files-and-rollback.zip') == '0ff7682db527f4eea1397cda36c43d2f4f5b984a7ea96267d7a215eb985c0964'
for proof in (projection['release_manifest'], projection['recovery_manifest']):
    assert sha(proof['path']) == proof['sha256']
for row in projection['changes']:
    target = (BASE / row['target']).resolve()
    assert target.is_relative_to(BASE.resolve())
    assert not any(p.is_symlink() for p in [target, *target.parents])
    assert sha(row['payload']) == row['sha256']
    assert (sha(target) if target.exists() else None) == row['previous_sha256'], str(target)
sys.path.insert(0, str(BASE))
from kquant.recovery_preflight import candidate_hash
recovery = read(HERE / 'recovery-manifest.json')
payload = candidate_hash(recovery)
assert payload == '918d56b36f7565c7d083b37e080d17c23ad5b48e1a0a3766edcf9b80c8d31077'
scope = HERE.parent.parent / 'O_LAUNCH_RESEARCH_DECISION_20261016.md'
receipt = {
    'status': 'APPROVED', 'approved_by': 'OWNER', 'gate': 'O-LAUNCH',
    'candidate_id': projection['candidate_id'], 'candidate_payload_sha256': payload,
    'runtime_root': str(ROOT / 'runtime'),
    'continuity_receipt_sha256': recovery['continuity']['receipt']['sha256'],
    'accepted_at': datetime.now(timezone.utc).isoformat(),
    'human_decision_evidence': {'source': 'DIRECT_USER_REPLY',
        'reference': '["request_user_input_async","call_633f35e5dd31435c97f88bee9b54ccc2",0]',
        'answer': '\u6279\u51c6\u6709\u9650\u7814\u7a76\u53d1\u5e03\uff0c\u4fdd\u7559\u4e0a\u8ff0\u9650\u5236',
        'scope_document': str(scope), 'scope_document_sha256': sha(scope)},
    'scope': 'SHADOW_STARTUP_RESEARCH_OBSERVATIONS_ONLY',
    'limitations_accepted': ['PERFORMANCE_NOT_PASSED', 'SOURCE_FACTS_PENDING', 'MARKET_ACCEPTANCE_PENDING'],
    'qualified_signal_authorized': False, 'source_facts_approved': False,
    'orders_authorized': False, 'system_clock_change_authorized': False,
    's1_manual_policy_authorized': False, 'system_autostart_authorized': False}
write(HERE / 'owner-shadow-acceptance.json', receipt)
recovery['final_runtime_accepted'] = True
recovery['acceptance_receipt'] = {'path': str(HERE / 'owner-shadow-acceptance.json'), 'sha256': sha(HERE / 'owner-shadow-acceptance.json')}
assert candidate_hash(recovery) == payload
write(HERE / 'recovery-manifest-shadow-accepted.json', recovery)
host = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
os.environ['PSModulePath'] = r'C:\Windows\System32\WindowsPowerShell\v1.0\Modules;C:\Program Files\WindowsPowerShell\Modules'
subprocess.run([host, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'Start-Local-KQUANT.ps1'), '-Stop'], check=True, timeout=90)
services = read(ROOT / 'runtime/work/option_foundation/runtime/services.json')
assert services.get('state', services.get('status')) == 'STOPPED', 'STOP_NOT_CONFIRMED'
for row in projection['changes']:
    target = BASE / row['target']
    assert (sha(target) if target.exists() else None) == row['previous_sha256']
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + '.deploy-pending')
    tmp.write_bytes(Path(row['payload']).read_bytes())
    assert sha(tmp) == row['sha256']
    os.replace(tmp, target)
entry = read(HERE / 'proposed-local-workspace-entry.json')
entry['recovery_manifest'] = {'path': str(HERE / 'recovery-manifest-shadow-accepted.json'), 'sha256': sha(HERE / 'recovery-manifest-shadow-accepted.json')}
entry['shadow_runtime_accepted'] = True
write(ENTRY, entry)
write(HERE / 'deployment-applied.json', {'candidate_id': projection['candidate_id'], 'applied_at': datetime.now(timezone.utc).isoformat(), 'changes': len(projection['changes']), 'business_databases_changed': False, 'entry_sha256': sha(ENTRY)})
subprocess.run([host, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'Start-Local-KQUANT.ps1')], check=True, timeout=60)
subprocess.run([host, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'Start-Local-KQUANT.ps1'), '-Start'], check=True, timeout=90)
