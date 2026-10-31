"""Bounded saved-evidence inspection, no SDK, credentials or database writes."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
D7 = HERE.parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    review = ROOT / 'review/KQUANT_GPT_Review_20261020'
    result = {'captured_at': datetime.now(timezone.utc).isoformat(),
              'deadline': read(D7/'constraint.json'), 'archive_evidence': []}
    with zipfile.ZipFile(review/'KQUANT_GPT_Review_20261020_CORE.zip') as core:
        for name in ('GPT_REVIEW_REPORT_20261020.md', 'CURRENT_STATE.json', 'VERSION_FILES.json'):
            data = core.read(name)
            result['archive_evidence'].append({'entry': name, 'sha256': hashlib.sha256(data).hexdigest()})
        manifest = json.loads(core.read('FILE_MANIFEST.json'))
        result['manifest_structure'] = type(manifest).__name__
    with zipfile.ZipFile(review/'KQUANT_GPT_Review_20261020_FILES_01.zip') as files:
        matches = [n for n in files.namelist() if n.endswith(('TODAY_OPENING_INCIDENT_20261020.md',
                     'independent-hour-scope-7896-20261020.json', 'audit-20261020T140022Z.json'))]
        for name in matches:
            data = files.read(name)
            result['archive_evidence'].append({'entry': name, 'sha256': hashlib.sha256(data).hexdigest(),
                                               'text': data.decode('utf-8-sig')})
    result['services'] = read(ROOT/'runtime/work/option_foundation/runtime/services.json')
    try:
        with urllib.request.urlopen('http://127.0.0.1:8001/api/health/live', timeout=2) as response:
            result['live'] = json.load(response)
    except Exception as exc:
        result['live_error'] = type(exc).__name__
    audit = read(D7/'audit-20261021T143716Z.json')
    result['last_completed_window'] = {'session': audit['session'], 'captured_at': audit['captured_at'],
        'metrics': audit['metrics'], 'journal': audit.get('journal_states'),
        'selection_started': None, 'qualification_passed': None, 'invalidations': None,
        'missing_stage_reason': 'NOT_ESTABLISHED_BY_EXISTING_AUDIT',
        'largest_proven_loss': '1000_EXPECTED_TO_ZERO_RECORDED_EVALUATIONS_PER_VARIANT',
        'root_cause': 'NOT_FULLY_ATTRIBUTED'}
    result['today'] = {'session': '2026-10-22', 'verdict': 'NOT_YET_AUDITED_NO_ZERO_INFERENCE'}
    result['deployment_changes'] = 0
    output = HERE/'baseline-20261022.json'
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'path': str(output), 'archive_entries': len(result['archive_evidence']),
                      'live_error': result.get('live_error'),
                      'release': result.get('live', {}).get('backend_release')}))


if __name__ == '__main__':
    main()
