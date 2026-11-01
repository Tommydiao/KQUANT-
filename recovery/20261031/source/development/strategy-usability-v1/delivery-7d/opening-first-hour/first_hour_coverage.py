"""Reuse immutable record grades without caching time-sensitive reconciliation."""
import importlib.util

from assembly import bootstrap
from prepared_minutes import FrozenDict, freeze, _readonly

_path = bootstrap.inherited.selected_overrides().get('options_opening_trend_coverage',
    bootstrap.BASE/'kquant/options_opening_trend_coverage.py')
_spec = importlib.util.spec_from_file_location('kquant._coverage_parent', _path)
parent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(parent)
_factor_grade = parent.factor_grade
_numeric = parent.complete_numeric_factor


class PreparedCoverageRow(FrozenDict):
    __slots__ = ('_grade', '_numeric', '_validators')
    __setattr__ = _readonly

    def __init__(self, record):
        dict.__init__(self, ((key, freeze(value)) for key, value in record.items()))
        object.__setattr__(self, '_grade', _factor_grade(record))
        object.__setattr__(self, '_numeric', tuple(_numeric(record, momentum=m) for m in (False, True)))
        object.__setattr__(self, '_validators', (_factor_grade, _numeric, parent.common.finite))


def factor_grade(row):
    if isinstance(row, PreparedCoverageRow) and row._validators == (_factor_grade, _numeric, parent.common.finite):
        return row._grade
    return _factor_grade(row)


def complete_numeric_factor(row, *, momentum):
    if isinstance(row, PreparedCoverageRow) and row._validators == (_factor_grade, _numeric, parent.common.finite):
        return row._numeric[bool(momentum)]
    return _numeric(row, momentum=momentum)


# The private parent keeps the original reconcile/audit/qualification code.
# Only content-only predicates recognize our own immutable projection rows.
parent.factor_grade = factor_grade
parent.complete_numeric_factor = complete_numeric_factor
for _name in dir(parent):
    if not _name.startswith('_') and _name not in globals():
        globals()[_name] = getattr(parent, _name)
