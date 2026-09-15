"""Finite, predeclared common-path risk comparisons; no quantity selection."""
from .hybrid_mc_numerics_v12 import upper_event_probability


def summarize_common_paths(records, *, path_ids, alternatives, event_names,
                           family_alpha, comparison_budget):
    def valid_identity(value):
        return (type(value) is int and value >= 0) or (type(value) is str and bool(value))
    if any(not valid_identity(p) for p in path_ids):
        raise ValueError('Explicit integer or nonempty string path identity required')
    if not path_ids or len(set(path_ids)) != len(path_ids):
        raise ValueError('Unique nonempty frozen path identities required')
    if any(type(a) not in (int, float) for a in alternatives) or tuple(alternatives) != (0, 0.25, 0.5, 1):
        raise ValueError('Original four alternatives required')
    if not event_names or len(set(event_names)) != len(event_names):
        raise ValueError('Unique predeclared risk events required')
    if type(comparison_budget) is not int or comparison_budget < len(alternatives) * len(event_names):
        raise ValueError('Insufficient predeclared comparison budget')
    expected = {(p, a) for p in path_ids for a in alternatives}
    seen = set()
    counts = {(a, e): 0 for a in alternatives for e in event_names}
    for record in records:
        if not valid_identity(record['path_id']) or type(record['alternative']) not in (int, float):
            raise ValueError('Invalid observation identity type')
        key = (record['path_id'], record['alternative'])
        if key not in expected or key in seen:
            raise ValueError('Missing common-path identity or duplicate observation')
        if set(record['events']) != set(event_names) or any(type(v) is not bool for v in record['events'].values()):
            raise ValueError('Unknown event outcomes cannot become non-breaches')
        seen.add(key)
        for event, occurred in record['events'].items():
            counts[(key[1], event)] += occurred
    if seen != expected:
        raise ValueError('Incomplete common paths; do not drop failed simulations')
    results = [{'alternative': a, 'event': e,
                **upper_event_probability(counts[(a, e)], len(path_ids),
                                          family_alpha=family_alpha, comparisons=comparison_budget)}
               for a in alternatives for e in event_names]
    return {'comparisons': results, 'selected_alternative': None, 'admission': 'ABSTAIN',
            'scope': 'MODEL_CONDITIONAL_NUMERICAL_COMPARISON',
            'stress_probability_assigned': False, 'execution_allowed': False}
