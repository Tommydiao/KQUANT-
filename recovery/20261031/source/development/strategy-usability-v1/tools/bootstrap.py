"""Load only this small development overlay; the running accepted tree stays untouched."""
import sys
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]
BASE = DEV.parent / "workspace"


def activate():
    sys.path.insert(0, str(BASE))
    import kquant
    kquant.__path__.insert(0, str(DEV / "kquant"))
    return DEV, BASE
