from kquant_crypto.strategy_dual_mode_v1 import Bar
from kquant_crypto.hybrid_exit_bar import exit_on_bar, realized_net_r
import pytest


def test_gap_before_pending_and_stop_first():
    assert exit_on_bar(Bar(300,90,110,89,100),95,105,'structure')[2]=='gap_stop'
    assert exit_on_bar(Bar(300,100,110,90,101),95,105)[2]=='stop'
    assert exit_on_bar(Bar(300,100,110,90,101),95,105,'structure')==(100,300,'structure')


def test_no_profit_cap_and_costs():
    assert exit_on_bar(Bar(300,100,200,99,150),95) is None
    assert realized_net_r(100,110,2)==pytest.approx((110*.9995-100-.001*(100+110*.9995))/2)
