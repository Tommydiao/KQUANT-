import copy

import pytest

from kquant_crypto.hybrid_factor_ablation import FEATURES, train_ablation


def rows():
    return [{'symbol': symbol, 'as_of': day * 86400, 'available_at': day * 86400,
             'label_available_at': (day + 1) * 86400, 'partition': 'TRAIN',
             'exclusion_reason': None, 'exposure': 'EXPOSED_RESEARCH',
             'feature_order': list(FEATURES), 'x': [day % 9, day % 7, day % 5, day % 3],
             'y_log_percent': float(day % 9)}
            for day in range(100, 160) for symbol in ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')]


def test_ablation_fold_purge_and_no_active_selection():
    result = train_ablation(rows())
    lookup = {(r['symbol'], r['as_of']): r for r in rows()}
    for fold in result['folds']:
        assert all(lookup[tuple(key)]['label_available_at'] < fold['start'] - 86400
                   for key in fold['train_ids'])
        assert all(lookup[tuple(key)]['label_available_at'] < fold['end']
                   for key in fold['validation_ids'])
        assert len(fold['scores']) == 5
        assert fold['scores'][0]['mse_difference_from_full'] == 0
    assert result['automatic_selection'] is False
    assert result['runtime_enabled'] is False


def test_later_outcomes_cannot_change_earlier_fold_or_preprocessing():
    source = rows()
    original = train_ablation(source)
    altered = copy.deepcopy(source)
    for row in altered:
        if row['as_of'] >= original['folds'][0]['end']:
            row['y_log_percent'] += 1000
    changed = train_ablation(altered)
    assert changed['folds'][0] == original['folds'][0]
    assert [s['frozen_train_preprocessing'] for s in changed['folds'][1]['scores']] == [
        s['frozen_train_preprocessing'] for s in original['folds'][1]['scores']]


def test_diagnostic_partition_and_unavailable_labels_rejected():
    source = rows()
    source[0]['partition'] = 'DEVELOPMENT_DIAGNOSTIC'
    with pytest.raises(ValueError):
        train_ablation(source)
    source = rows()
    source[0]['y_log_percent'] = None
    with pytest.raises(ValueError):
        train_ablation(source)
