"""Reuse immutable record grades without caching time-sensitive reconciliation."""
from kquant import _first_hour_parent_coverage as parent
from prepared_minutes import FrozenDict, freeze, _readonly

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
