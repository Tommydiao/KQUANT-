"""Descriptive exposed holding overlap audit; does not authorize fitting."""
from collections import Counter, defaultdict


def audit(rows, boundary):
    groups = defaultdict(list)
    seen = set()
    for row in rows:
        key = (row['policy'], row['trade_id'], row['as_of'])
        if key in seen:
            raise ValueError('Duplicate holding observation')
        seen.add(key)
        if row['scope'] != 'DEV_ONLY' or row['runtime_enabled'] or row['independent_oos']:
            raise ValueError('Exposed research contract required')
        groups[key[:2]].append(row)
    policies = {}
    for policy in sorted({k[0] for k in groups}):
        counts, group_counts = Counter(), Counter()
        max_remaining = max_holding = 0
        for (p, _), observations in groups.items():
            if p != policy:
                continue
            mature = [r for r in observations if r['label_status'] == 'MATURE']
            if len(mature) != len(observations):
                group_counts['INCOMPLETE_GROUP'] += 1
                counts['INCOMPLETE_GROUP'] += len(observations)
                continue
            entries = {r['as_of'] - r['holding_features']['age_seconds'] for r in mature}
            exits = {r['label_available_at'] for r in mature}
            if len(entries) != 1 or len(exits) != 1:
                raise ValueError('Holding group timing inconsistent')
            entry, known = entries.pop(), exits.pop()
            if any(r['available_at'] > r['as_of'] or r['as_of'] >= known for r in mature):
                raise ValueError('Invalid historical availability')
            remaining = max(known-r['as_of'] for r in mature)
            max_remaining = max(max_remaining, remaining)
            max_holding = max(max_holding, known-entry)
            # Entire source holding stays together. Labels spanning the boundary
            # are purged, never split into apparently independent observations.
            state = ('TRAIN_LABELS_KNOWN' if known < boundary else
                     'LATER_EXPOSED_GROUP' if entry >= boundary else 'BOUNDARY_PURGED')
            group_counts[state] += 1
            counts[state] += len(mature)
        policies[policy] = dict(observations=dict(counts), holding_groups=dict(group_counts),
            max_label_remaining_seconds=max_remaining,
            max_entry_to_label_available_seconds=max_holding,
            original_six_hour_bound_sufficient=max_holding <= 21600)
    return dict(scope='DEV_ONLY', boundary=boundary, policies=policies,
                training_enabled=False, embargo_frozen=False,
                independent_oos=False, performance='PERFORMANCE_UNPROVEN',
                limitation='Descriptive temporal purge only; no new embargo or evaluation authorization')
