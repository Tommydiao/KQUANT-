import numpy as np

from kquant_crypto.math_action_mc import _outcome_from_close_paths, _outcome_from_ohlc_paths


def test_mc_stop_wins_same_step_collision():
    paths = np.asarray([[100.0, 98.0, 103.0], [100.0, 101.0, 102.5]])
    net_r, outcome = _outcome_from_close_paths(
        paths,
        entry_reference=100.0,
        stop=99.0,
        target=102.0,
        fee=0.001,
        slippage=0.0005,
    )
    assert outcome.tolist() == [-1, 1]
    assert net_r[0] < 0 < net_r[1]


def test_mc_is_deterministic_for_identical_paths():
    paths = np.full((3, 12), 100.5)
    first = _outcome_from_close_paths(paths, entry_reference=100.0, stop=99.0, target=102.0, fee=0.001, slippage=0.0005)
    second = _outcome_from_close_paths(paths, entry_reference=100.0, stop=99.0, target=102.0, fee=0.001, slippage=0.0005)
    assert np.array_equal(first[0], second[0])
    assert np.array_equal(first[1], second[1])
    assert first[1].tolist() == [0, 0, 0]
    assert np.all(first[0] > 0)


def test_mc_no_barrier_hit_exits_at_last_close():
    paths = np.asarray([[100.25, 100.50], [99.75, 100.10]])
    net_r, outcome = _outcome_from_close_paths(
        paths,
        entry_reference=100.0,
        stop=99.0,
        target=102.0,
        fee=0.001,
        slippage=0.0005,
    )
    assert outcome.tolist() == [0, 0]
    assert net_r[0] > net_r[1]


def test_ohlc_mc_uses_stop_first_and_preserves_time_exit():
    opens = np.asarray([[100.0], [100.0]])
    highs = np.asarray([[103.0], [100.8]])
    lows = np.asarray([[98.0], [99.5]])
    closes = np.asarray([[101.0], [100.5]])
    net_r, outcome = _outcome_from_ohlc_paths(
        opens,
        highs,
        lows,
        closes,
        entry_reference=100.0,
        stop=99.0,
        target=102.0,
        fee=0.001,
        slippage=0.0005,
    )
    assert outcome.tolist() == [-1, 0]
    assert net_r[0] < 0 < net_r[1]
