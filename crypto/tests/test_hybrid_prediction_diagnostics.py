import copy

import pytest

from kquant_crypto.hybrid_prediction_diagnostics import diagnostic_breakdown


def data(days=21):
    rows = []
    for date in range(100, 100 + days):
        for symbol in ('BTCUSDT', 'ETHUSDT', 'SOLUSDT'):
            rows.append({'symbol': symbol, 'mode': 'RANGE', 'as_of': date * 86400,
                'available_at': date * 86400, 'dependency_group': date,
                'partition': 'DEVELOPMENT_DIAGNOSTIC', 'exclusion_reason': None,
                'exposure': 'EXPOSED_RESEARCH', 'y_log_percent': 1.0})
    return rows


def run(rows):
    n = len(rows)
    return diagnostic_breakdown(rows, [1.] * n, [1.] * n, [0.] * n, [2.] * n,
        training_mean=0., training_positive_fraction=.5, replicates=100)


def test_paired_errors_keep_three_coins_in_one_date_block():
    report = run(data())
    block = report['paired_date_block_comparison']
    assert report['overall']['dependency_dates'] == 21
    assert report['overall']['rows'] == 63
    assert block['paired_mse_difference_interval95'] == [-1., -1.]
    assert block['paired_brier_difference_interval95'] == [-.25, -.25]
    assert block['stable_block_count'] is False
    assert report['strata']['symbol']['BTCUSDT']['rows'] == 21
    assert report == run(data())
    assert report['runtime_enabled'] is False
    assert report['probability_calibrated'] is False


def test_date_gap_is_not_interpolated():
    rows = [r for r in data() if r['dependency_group'] != 110]
    assert run(rows)['paired_date_block_comparison']['status'] == 'UNAVAILABLE'


def test_interval_score_penalizes_miss_and_thirds_keep_dates_together():
    rows = data()
    rows[0]['y_log_percent'] = 3.0
    result = run(rows)
    assert result['overall']['mean_interval_score90_log_percent'] == pytest.approx(2 + 20 / 63)
    assert [v['rows'] for v in result['calendar_thirds_descriptive_only'].values()] == [21, 21, 21]
    assert run(data(1))['calendar_thirds_descriptive_only']['2']['rows'] == 0


@pytest.mark.parametrize('problem', ['duplicate', 'unfilled', 'future', 'train', 'unknown_label'])
def test_invalid_research_observation_rejected(problem):
    rows = copy.deepcopy(data())
    if problem == 'duplicate':
        rows.append(rows[0])
    if problem == 'unfilled':
        rows[0]['exclusion_reason'] = 'UNFILLED'
    if problem == 'future':
        rows[0]['available_at'] += 1
    if problem == 'train':
        rows[0]['partition'] = 'TRAIN'
    if problem == 'unknown_label':
        rows[0]['y_log_percent'] = None
    with pytest.raises(ValueError):
        run(rows)
