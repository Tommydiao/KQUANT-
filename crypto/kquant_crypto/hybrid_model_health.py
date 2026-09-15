"""Inspect artifact permission metadata without loading a model or making predictions."""
import hashlib
import json


def inspect_model_metadata(path):
    try:
        with path.open('rb') as stream:
            raw=stream.read(65537)
        if len(raw)>65536:
            raise ValueError('Oversize artifact metadata')
        metadata=json.loads(raw)
        if not isinstance(metadata,dict):
            raise ValueError('Metadata object required')
    except (OSError,ValueError):
        return {'state':'UNKNOWN','reason':'ARTIFACT_METADATA_UNAVAILABLE',
                'model_loaded':False,'execution_authorized':False}
    guarded=(metadata.get('scope')=='DEV_ONLY' and metadata.get('admission')=='ABSTAIN'
             and metadata.get('runtime_enabled') is False)
    return {'state':'WAITING' if guarded else 'FAILED',
            'reason':'DEV_ONLY_ABSTAIN' if guarded else 'ARTIFACT_PERMISSION_MISMATCH',
            'metadata_sha256':hashlib.sha256(raw).hexdigest(),
            'scope':'METADATA_ONLY_NOT_MODEL_VALIDATION',
            'model_loaded':False,'execution_authorized':False}
