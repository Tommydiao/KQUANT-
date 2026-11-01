"""Existing delta/watermark/rebuild contract with one grade per immutable row."""
import importlib.util

from assembly import bootstrap
from kquant.options_opening_trend_coverage import PreparedCoverageRow

_path = bootstrap.inherited.selected_overrides().get('options_opening_trend_projection',
    bootstrap.BASE/'kquant/options_opening_trend_projection.py')
_spec = importlib.util.spec_from_file_location('kquant._projection_parent', _path)
parent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(parent)


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
