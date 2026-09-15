import importlib.util
from pathlib import Path
import pytest


def module():
    spec = importlib.util.spec_from_file_location('rx06_audit',Path(__file__).resolve().parents[1]/'scripts/audit_rx06_prospective_pair_dev.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_quantile_definition():
    m = module()
    assert m.quantile([3,1,2],.5) == 2
    assert m.quantile([0,10],.9) == 9
    with pytest.raises(ValueError): m.quantile([], .5)


def test_partial_run_never_accepted(tmp_path):
    with pytest.raises(ValueError,match='Terminal report missing'):
        module().audit(tmp_path,tmp_path/'out')
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('bad', ['count','mean','fills','open'])
def test_inconsistent_summaries_rejected(bad):
    value = dict(net_change=1, target_plan_fills=1, open_at_horizon=0,
                 booked_risk_ratio_exceeded=False, max_incremental_nav_drawdown=.01)
    rows = [dict(paired_net_change=0,results=dict(WITH_PLAN=value,WITHOUT_PLAN=value))]
    summary = dict(paths=1,mean_paired_net_change=0,target_plan_fills=dict(WITH_PLAN=1,WITHOUT_PLAN=1),
                   horizon_open_paths=dict(WITH_PLAN=0,WITHOUT_PLAN=0))
    if bad == 'count': summary['paths'] = 2
    if bad == 'mean': summary['mean_paired_net_change'] = 1
    if bad == 'fills': summary['target_plan_fills']['WITH_PLAN'] = 2
    if bad == 'open': summary['horizon_open_paths']['WITH_PLAN'] = 1
    with pytest.raises(ValueError): module().numeric_audit(rows,summary,1)
