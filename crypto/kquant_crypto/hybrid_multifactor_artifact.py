"""Explicit development-only artifact access, never an admission grant."""
import hashlib
import json
from pathlib import Path


def inspect_artifact(path, *, purpose):
    if purpose != 'DEV_ONLY':
        raise ValueError('Multifactor research artifact cannot serve formal consumers')
    root = Path(path)
    meta = json.loads((root/'artifact.json').read_text())
    if meta.get('scope') != 'DEV_ONLY' or meta.get('runtime_enabled') is not False:
        raise ValueError('Unsafe research scope')
    if meta.get('exposure') != 'EXPOSED_RESEARCH':
        raise ValueError('Unrecognized exposure policy')
    posterior = root/'posterior.nc'
    actual = hashlib.sha256(posterior.read_bytes()).hexdigest()
    if actual != meta.get('posterior_sha256'):
        raise ValueError('Posterior integrity mismatch')
    return meta
