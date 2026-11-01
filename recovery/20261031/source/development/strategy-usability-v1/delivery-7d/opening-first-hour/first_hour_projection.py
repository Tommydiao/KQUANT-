"""Existing delta/watermark/rebuild contract with one grade per immutable row."""
from kquant import _first_hour_parent_projection as parent
from kquant.options_opening_trend_coverage import PreparedCoverageRow



class ProjectionCache(parent.ProjectionCache):
    def apply(self, delta, **kwargs):
        # Transform only this bounded delta. Source identity changes, restarts,
        # gaps and count regressions still follow the parent's rebuild rules.
        value = {**delta, 'rows': [(rowid, PreparedCoverageRow(record))
                                  for rowid, record in delta['rows']]}
        return super().apply(value, **kwargs)


for _name in dir(parent):
    if not _name.startswith('_') and _name not in globals():
        globals()[_name] = getattr(parent, _name)
