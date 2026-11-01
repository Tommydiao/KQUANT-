import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize('adapter,parent', [
    ('first_hour_minute_admission.py', '_first_hour_parent_admission'),
    ('first_hour_coverage.py', '_first_hour_parent_coverage'),
    ('first_hour_projection.py', '_first_hour_parent_projection'),
])
def test_runtime_parent_is_explicit_and_selected_by_assembly(adapter, parent):
    import importlib
    import bootstrap
    tree = ast.parse((Path(__file__).parent / adapter).read_text())
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert 'assembly' not in imports
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == 'spec_from_file_location' for n in ast.walk(tree))
    module = importlib.import_module('kquant.' + parent)
    finder = next(f for f in __import__('sys').meta_path if isinstance(f, bootstrap.FirstHourFinder))
    assert Path(module.__file__).resolve() == finder.mapping['kquant.' + parent].resolve()
