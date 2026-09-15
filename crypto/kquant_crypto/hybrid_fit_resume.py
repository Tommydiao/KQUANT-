"""Immutable completed-chain recovery for an explicitly resumed DEV fit."""
import json
import shutil
from pathlib import Path

from .hybrid_dev_fit import sha, write_json


def verify_resume(parent, checkpoint, config, rows, preprocessing):
    parent, checkpoint = Path(parent), Path(checkpoint)
    audit = json.loads(checkpoint.read_text())
    old = json.loads((parent / 'preregistration.json').read_text())
    if audit['execution_enabled'] or old['runtime_enabled'] or old['scope'] != 'DEV_ONLY':
        raise ValueError('DEV-only checkpoint required')
    if audit['fit_status']['status'] != 'DEADLINE_PARTIAL':
        raise ValueError('Only interrupted fits may resume')
    operational = {'deadline', 'code_hash', 'command', 'interpreter'}
    if {k: v for k, v in old.items() if k not in operational} != {
            k: v for k, v in config.items() if k not in operational}:
        raise ValueError('Frozen statistical contract changed')
    for name, digest in audit['fit_files'].items():
        if Path(name).name != name or sha(parent / name) != digest:
            raise ValueError('Checkpoint file hash mismatch: ' + name)
    if json.loads((parent / 'training_rows.json').read_text()) != rows:
        raise ValueError('Frozen training rows changed')
    if json.loads((parent / 'preprocessing.json').read_text()) != preprocessing:
        raise ValueError('Frozen preprocessing changed')
    count = audit['completed_chain_files']
    hashes = audit['verified_chain_hashes']
    if not 0 < count < old['chains'] or set(hashes) != {str(i) for i in range(count)}:
        raise ValueError('Noncontiguous or invalid completed chains')
    for i in range(count):
        if sha(parent / f'chain_{i}.nc') != hashes[str(i)]:
            raise ValueError('Completed chain hash mismatch')
    return count


def copy_verified_artifacts(parent, output, checkpoint, count):
    parent, output = Path(parent), Path(output)
    for name in ['prior.nc'] + [f'chain_{i}.nc' for i in range(count)]:
        target = output / name
        if target.exists():
            raise ValueError('Refusing to replace resume artifact')
        shutil.copyfile(parent / name, target)
        if sha(target) != sha(parent / name):
            raise ValueError('Copied artifact hash mismatch')
    write_json(output / 'resume_provenance.json', {
        'parent': str(parent), 'checkpoint': str(checkpoint),
        'checkpoint_hash': sha(Path(checkpoint)), 'reused_chains': count,
        'unfinished_chain_restarts_from_registered_seed': True,
        'mid_chain_resume': False, 'runtime_enabled': False,
    })
