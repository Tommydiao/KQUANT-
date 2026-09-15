"""Actual label-interval partition diagnostics, never training permission."""
from .hybrid_target_contract import interval_components


def audit_group_partitions(groups, boundaries):
    if len(boundaries)!=4 or any(b<=a for a,b in zip(boundaries,boundaries[1:])):
        raise ValueError('Three ordered calendar partitions required')
    keys=[tuple(r['economic_key']) for r in groups]
    if len(set(keys))!=len(keys):raise ValueError('Economic groups must already be merged across policies')
    components=interval_components(groups)
    membership={tuple(key):i for i,c in enumerate(components) for key in c['economic_keys']}
    names=('dev_train','dev_validation','dev_diagnostic')
    result=[]
    for row in groups:
        begin,end=row['information_start'],row['information_end']
        i=next((i for i in range(3) if boundaries[i]<=begin<boundaries[i+1]),None)
        component=components[membership[tuple(row['economic_key'])]]
        reason=None
        if i is None or end>boundaries[-1]:reason='OUTSIDE_AUTHORIZED_WINDOW'
        elif end>=boundaries[i+1]:reason='GROUP_LABEL_CROSSES_BOUNDARY'
        elif component['information_start']<boundaries[i] or component['information_end']>=boundaries[i+1]:
            reason='DEPENDENCY_COMPONENT_CROSSES_BOUNDARY'
        result.append(dict(**row, proposed_partition=names[i] if i is not None else None,
            component_id=membership[tuple(row['economic_key'])],interval_exclusion=reason,
            interval_check_only_pass=reason is None,training_enabled=False,
            independent_oos=False,embargo_status='NOT_GRANTED_BY_THIS_AUDIT'))
    return dict(rows=result,components=components,training_enabled=False,
        scope='EXPOSED_DEVELOPMENT_INTERVAL_AUDIT',
        limitation='Counts establish label overlap checks only; no new partition grant, embargo approval, probability calibration or effective sample size.')
