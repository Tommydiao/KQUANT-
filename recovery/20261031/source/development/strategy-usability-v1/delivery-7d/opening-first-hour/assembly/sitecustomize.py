"""Fail closed if the explicitly isolated child cannot load its exact overlay."""
import os
from pathlib import Path
if os.environ.get('KQUANT_TEST_LEGACY_OVERLAY'):
    from bootstrap import activate, HERE
    if os.environ['KQUANT_TEST_LEGACY_OVERLAY'] != str(HERE):
        raise SystemExit('FIRST_HOUR_UNEXPECTED_OVERLAY')
    root = Path(os.environ['KQUANT_RUNTIME_DATA_ROOT']).resolve()
    if not (root/'TEST_ONLY.json').is_file() or not root.is_relative_to(HERE.parents[4]/'source/evidence'):
        raise SystemExit('FIRST_HOUR_TEST_ROOT_REQUIRED')
    activate()
