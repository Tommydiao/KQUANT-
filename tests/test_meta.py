import pandas as pd

from btc_eth_15m.meta import Rule, _apply_rule, _profit_factor, walk_forward_meta_filter


def test_rule_application_and_profit_factor():
    frame = pd.DataFrame({"feature": [1, 2, 3], "r_multiple": [1.0, -0.5, 2.0]})
    selected = _apply_rule(frame, Rule("feature", ">=", 2))
    assert len(selected) == 2
    assert round(_profit_factor(selected), 3) == 4.0


def test_walk_forward_meta_filter_returns_year_rows():
    rows = []
    for year in [2021, 2022, 2023]:
        for idx in range(30):
            rows.append(
                {
                    "entry_time": f"{year}-01-01 00:00:00+00:00",
                    "r_multiple": 1.0 if idx % 3 == 0 else -0.5,
                    "signal_rsi": idx,
                    "signal_atr_pct": idx / 1000,
                    "signal_regime_atr_pct": idx / 1000,
                    "signal_volume_ratio": 1 + idx / 100,
                    "signal_htf_gap_bps": idx * 2,
                    "signal_distance_ema_mid_atr": idx / 10,
                    "signal_hour_utc": idx % 24,
                }
            )
    result = walk_forward_meta_filter(pd.DataFrame(rows))
    assert set(result["test_year"]) == {2022, 2023}
