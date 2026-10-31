import os
from pathlib import Path
if os.environ.get('KQUANT_TEST_LEGACY_OVERLAY')==str(Path(__file__).resolve().parents[1]):
    from bootstrap import activate
    activate()
