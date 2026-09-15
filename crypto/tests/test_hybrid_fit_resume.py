import json

import pytest

from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_fit_resume import verify_resume, copy_verified_artifacts


def fixture(tmp_path):
    parent = tmp_path / 'parent'
    parent.mkdir()
    config = {'scope': 'DEV_ONLY', 'runtime_enabled': False, 'chains': 4,
              'draws': 1000, 'deadline': 'old', 'code_hash': 'old'}
    for name, value in [('preregistration.json', config), ('training_rows.json', [1]),
                        ('preprocessing.json', {'mean': [0]})]:
        write_json(parent / name, value)
    (parent / 'chain_0.nc').write_bytes(b'frozen trace')
    (parent / 'prior.nc').write_bytes(b'frozen prior')
    checkpoint = tmp_path / 'checkpoint.json'
    write_json(checkpoint, {'execution_enabled': False,
        'fit_status': {'status': 'DEADLINE_PARTIAL'}, 'completed_chain_files': 1,
        'fit_files': {p.name: sha(p) for p in parent.iterdir()},
        'verified_chain_hashes': {'0': sha(parent / 'chain_0.nc')}})
    return parent, checkpoint, config


def test_resume_preserves_completed_chain_and_operational_changes(tmp_path):
    parent, checkpoint, config = fixture(tmp_path)
    config = {**config, 'deadline': 'new', 'code_hash': 'new'}
    assert verify_resume(parent, checkpoint, config, [1], {'mean': [0]}) == 1
    out = tmp_path / 'new'
    out.mkdir()
    copy_verified_artifacts(parent, out, checkpoint, 1)
    assert sha(out / 'chain_0.nc') == sha(parent / 'chain_0.nc')
    assert json.loads((out / 'resume_provenance.json').read_text())['mid_chain_resume'] is False
    with pytest.raises(ValueError):
        copy_verified_artifacts(parent, out, checkpoint, 1)


@pytest.mark.parametrize('change', ['hash', 'rows', 'scaling', 'draws', 'runtime'])
def test_changed_evidence_or_model_rejected(tmp_path, change):
    parent, checkpoint, config = fixture(tmp_path)
    rows, preprocessing = [1], {'mean': [0]}
    if change == 'hash':
        (parent / 'chain_0.nc').write_bytes(b'changed')
    if change == 'rows':
        rows = [2]
    if change == 'scaling':
        preprocessing = {'mean': [1]}
    if change == 'draws':
        config['draws'] = 10
    if change == 'runtime':
        config['runtime_enabled'] = True
    with pytest.raises(ValueError):
        verify_resume(parent, checkpoint, config, rows, preprocessing)
