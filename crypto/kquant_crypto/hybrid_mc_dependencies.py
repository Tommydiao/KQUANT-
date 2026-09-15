"""Conservative research-start dependencies; never estimates effective sample size."""


def audit_dependencies(starts):
    if len({r['as_of'] for r in starts}) != len(starts):
        raise ValueError('Duplicate start identity')
    rows = sorted(starts, key=lambda r:r['as_of'])
    for r in rows:
        if not r['history_start'] < r['as_of'] < r['scenario_end']:
            raise ValueError('Invalid history/start/scenario interval')
        if len(set(tuple(k) for k in r['economic_keys'])) != len(r['economic_keys']):
            raise ValueError('Cross-policy economic identities must be deduplicated')
    parent = list(range(len(rows)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    edges = []
    for i,a in enumerate(rows):
        for j in range(i+1,len(rows)):
            b = rows[j]
            reasons = []
            if b['history_start'] <= a['as_of']:
                reasons.append('SHARED_HISTORICAL_WINDOW')
            if b['history_start'] <= a['scenario_end']:
                reasons.append('CONSERVATIVE_HISTORY_SCENARIO_OVERLAP')
            shared = set(map(tuple,a['economic_keys'])) & set(map(tuple,b['economic_keys']))
            if shared:
                reasons.append('SAME_ECONOMIC_POSITION_OR_PENDING')
            if reasons:
                parent[root(j)] = root(i)
                edges.append(dict(left=a['as_of'],right=b['as_of'],reasons=reasons,
                                  shared_economic_keys=[list(k) for k in sorted(shared)]))
    groups = {}
    for i,row in enumerate(rows):
        groups.setdefault(root(i),[]).append(row['as_of'])
    return dict(starts=len(rows),components=list(groups.values()),edges=edges,
        independent_sample_count=None,
        limitation='Scenario ends are simulated horizons, NOT realized label availability. Components are conservative dependence groups, not proven independent market samples.')
