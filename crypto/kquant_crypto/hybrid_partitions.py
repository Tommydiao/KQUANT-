"""Calendar splits inside already exposed development history, never new OOS."""

from .candidate_policy import digest


def partition_policy(start,end):
    if type(start) is not int or type(end) is not int or start<0 or start%86400 or end%86400 or end-start<5*86400:
        raise ValueError('At least five complete UTC calendar days required')
    days=(end-start)//86400
    cut1=start+int(days*.6)*86400
    cut2=start+int(days*.8)*86400
    value={'version':'hybrid_calendar_split_m2_v1','boundaries':[start,cut1,cut2,end],
           'ratios':[.6,.2,.2],'embargo_seconds':21600,'purge':'label_information_end >= partition_end',
           'exposure':'EXPOSED_DEVELOPMENT','independent_oos':False,'training_enabled':False}
    return {**value,'policy_hash':digest(value)}


def assign_partitions(labels,policy):
    if digest({k:v for k,v in policy.items() if k!='policy_hash'})!=policy['policy_hash']:
        raise ValueError('Partition policy hash mismatch')
    bounds=policy['boundaries']; names=('train','validation','test')
    identities=[r['economic_signal_id'] for r in labels]
    if len(set(identities))!=len(identities):
        raise ValueError('Duplicate economic signal')
    result=[]
    for row in labels:
        begin=row['information_start']; end=row['information_end']
        if end<begin:
            raise ValueError('Invalid label information interval')
        index=next((i for i in range(3) if bounds[i]<=begin<bounds[i+1]),None)
        reason=None
        if index is None:
            reason='outside_authorized_partition'
        elif row['status']!='mature' or row['source']!='executed_virtual':
            reason='not_mature_executed_population'
        elif end>=bounds[index+1]:
            reason='purged_information_overlap'
        elif index>0 and begin<bounds[index]+policy['embargo_seconds']:
            reason='embargo_after_boundary'
        result.append({'economic_signal_id':row['economic_signal_id'],
                       'partition':None if index is None else names[index],
                       'population_eligible':reason is None,'exclusion_reason':reason,
                       'dependency_group_id':row['dependence_group'],
                       'information_start':begin,'information_end':end,
                       'partition_policy_hash':policy['policy_hash'],
                       'independent_oos':False,'training_enabled':False})
    return sorted(result,key=lambda r:(r['information_start'],r['economic_signal_id']))
