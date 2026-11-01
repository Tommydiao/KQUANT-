"""Transport summary: select before copying, without mutating source evidence."""
from collections import Counter
from copy import deepcopy
import json

DETAIL_FIELDS = frozenset({
    'policy_snapshot', 'factor_evidence', 'reference_evidence', 'input_checks',
    'event_coverage', 'contract_qualification', 'initial_eligibility',
})


def compact_record(row):
    result = {**{key: deepcopy(value) for key, value in row.items()
                 if key not in DETAIL_FIELDS and key != 'strategy_comparison'}, 'evidence_deferred': True}
    if isinstance(row.get('strategy_comparison'), dict):
        from kquant.options_intraday_comparison import compact_comparison
        result['strategy_comparison'] = compact_comparison(row['strategy_comparison'])
    elif 'strategy_comparison' in row:
        result['strategy_comparison'] = deepcopy(row['strategy_comparison'])
    return result


def compact_coverage(value):
    if not isinstance(value, dict):
        return deepcopy(value)
    result = {key: deepcopy(item) for key, item in value.items() if key not in {'items', 'checkpoints'}}
    if 'items' in value:
        result.update(items_total=value.get('items_total', len(value['items'])), items_deferred=True)
    if 'checkpoints' in value:
        result['checkpoints'] = []
        for point in value['checkpoints']:
            copied = {key: deepcopy(item) for key, item in point.items() if key != 'items'}
            if 'items' in point:
                items = point['items']
                copied.update(items_total=len(items), items_deferred=True,
                    reason_counts=dict(Counter(reason for row in items for reason in set(row.get('reasons', [])))))
            result['checkpoints'].append(copied)
    return result


def compact_status(payload):
    result = {key: deepcopy(value) for key, value in payload.items()
              if key not in {'evaluations', 'candidates', 'checkpoint_coverage', 'registered_items'}}
    if 'checkpoint_coverage' in payload:
        result['checkpoint_coverage'] = compact_coverage(payload['checkpoint_coverage'])
    if 'registered_items' in payload:
        result['registered_items'] = [{key: deepcopy(row[key]) for key in ('symbol', 'identity_status', 'identity_reason')
                                       if key in row} for row in payload['registered_items']]
    for name in ('evaluations', 'candidates'):
        rows = payload.get(name, [])
        result[name] = [compact_record(row) for row in rows[:8]]
        result[name + '_total'] = payload.get(name + '_total', len(rows))
        result[name + '_deferred'] = result[name + '_total'] > len(result[name])
    result['response_format'] = 'COMPACT_V2'
    for name in ('evaluations', 'candidates'):
        while result[name] and len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 32768:
            result[name].pop()
            result[name + '_deferred'] = True
    if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 32768:
        for name in ('worker', 'reference_collection'):
            value = result.get(name)
            if isinstance(value, dict):
                result[name] = {key: item for key, item in value.items() if not isinstance(item, (dict, list))}
                result[name]['diagnostics_deferred'] = True
    return result
