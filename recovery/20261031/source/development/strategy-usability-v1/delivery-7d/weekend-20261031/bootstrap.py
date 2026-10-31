"""Explicit weekend development overlay; never used by the accepted entry."""
from pathlib import Path
import importlib.abc
import importlib.util
import sys

HERE=Path(__file__).resolve().parent
BASE=HERE.parents[2]/'workspace'


class WeekendFinder(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith('kquant.'):
            candidate=(HERE/'patches'/Path(*fullname.split('.'))).with_suffix('.py')
            if candidate.is_file():
                return importlib.util.spec_from_file_location(fullname,candidate)


def activate():
    if str(BASE) not in sys.path:
        sys.path.insert(0,str(BASE))
    if not any(isinstance(item,WeekendFinder) for item in sys.meta_path):
        sys.meta_path.insert(0,WeekendFinder())
