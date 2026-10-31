"""Retain unresolved asset references without treating missing originals as facts."""
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import prepare_local_entry as entry
from kquant.options_opening_trend_reference import source_review


def main():
    config = entry.CODE / 'config/review_acceptances/options_opening_trend_reference_sources.json'
    before = config.read_bytes()
    value = json.loads(before)
    reasons = {'DLR': 'ASSET_CLASS_REVIEW_REQUIRED', 'DXYZ': 'ASSET_CLASS_REVIEW_REQUIRED',
               'EQIX': 'ASSET_CLASS_REVIEW_REQUIRED', 'IRM': 'ASSET_CLASS_REVIEW_REQUIRED',
               'GWH': 'SOURCE_IDENTITY_UNCONFIRMED', 'ASTX': 'SOURCE_ORIGINAL_MISSING'}
    _, issues = entry.source_inventory(entry.configuration_files())
    expected = {'/instrument_facts/' + symbol for symbol in reasons}
    if {row['json_pointer'] for row in issues} != expected or any(row['code'] != 'FileNotFoundError' for row in issues):
        raise ValueError('REMAINING_ISSUES_CHANGED')
    now = datetime.now(UTC)
    changes = []
    for symbol, reason in reasons.items():
        original = value['instrument_facts'][symbol]
        unavailable = {'status': 'UNAVAILABLE', 'underlying': symbol, 'unavailable_reason': reason,
                       'declared_at': now.isoformat(), 'declared_by': 'KQUANT_SOURCE_RECOVERY_AUDIT',
                       'source_path': original['source_path'], 'source_sha256': original['source_sha256'],
                       'source_url': original['source_url'], 'asset_type': 'UNKNOWN',
                       'assertion_limits': ['NO_VALID_SOURCE_FACT', 'NOT_OWNER_APPROVAL']}
        assert source_review(unavailable, root=entry.CODE, now=now) is None
        changes.append({'symbol': symbol, 'old_fact': original, 'unavailable': unavailable})
        value['instrument_facts'][symbol] = unavailable
    out = entry.ROOT / 'source/evidence/new-machine-20261008/unavailable-assets-20261010'
    out.mkdir(exist_ok=False)
    with (out / 'reference-config-before.json').open('xb') as handle:
        handle.write(before)
    data = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    entry.save(out / 'declaration.json', {'before_sha256': sha256(before).hexdigest(),
               'after_sha256': sha256(data).hexdigest(), 'changes': changes, 'owner_approval': False})
    fd, temporary = tempfile.mkstemp(dir=config.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if config.read_bytes() != before:
            raise ValueError('CONFIG_CHANGED_DURING_DECLARATION')
        os.replace(temporary, config)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()
    facts, issues = entry.source_inventory(entry.configuration_files())
    result = {'verified_originals': len(facts), 'unavailable_assets': issues,
              'blocking_issues': [i for i in issues if i['code'] != 'DECLARED_ASSET_UNAVAILABLE'],
              'owner_approval': False, 'production_started': False}
    entry.save(out / 'consumer-verification.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
