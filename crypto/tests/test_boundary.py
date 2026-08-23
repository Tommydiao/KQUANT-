from __future__ import annotations

import runpy
from pathlib import Path


def test_read_only_boundary_script_passes():
    result = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / "verify_read_only_boundary.py"), run_name="not_main")
    assert "FORBIDDEN_SEGMENTS" in result
