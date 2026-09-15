"""Nested calendars for fixed24h descriptive targets, never variable holding labels."""
DAY = 86400


def build_folds(rows, start, end):
    if start % DAY or end % DAY or end - start < 30 * DAY:
        raise ValueError('At least30 authorized UTC days required')
    identities = [(r['symbol'], r['as_of']) for r in rows]
    if len(identities) != len(set(identities)):
        raise ValueError('Duplicate opportunity identity')
    for row in rows:
        if row['fill_status'] != 'NOT_APPLICABLE' or row['exposure'] != 'EXPOSED_RESEARCH':
            raise ValueError('Only exposed fixed-window opportunity labels supported')
        if not start <= row['as_of'] <= end or row['as_of'] % DAY:
            raise ValueError('Outside authorized daily population')
        if row['available_at'] > row['as_of']:
            raise ValueError('Future feature availability')
        if row['label_status'] == 'MATURE' and row['label_available_at'] != row['as_of'] + DAY:
            raise ValueError('Variable holding or different target interval cannot reuse this contract')
    days = (end-start)//DAY
    results = []
    for lo, hi in ((.4,.6),(.6,.8),(.8,1.0)):
        begin, stop = start+int(days*lo)*DAY, start+int(days*hi)*DAY
        inner_begin = start+int(((begin-start)//DAY)*.7)*DAY
        sets = {k: [] for k in ('outer_train','outer_diagnostic','inner_train','inner_validation')}
        exclusions = []
        for row in sorted(rows, key=lambda r:(r['as_of'],r['symbol'])):
            key = [row['symbol'],row['as_of']]
            stamp, available = row['as_of'],row['label_available_at']
            # Population's original split-specific PURGED_EMBARGO is not reused;
            # derive each fold from original timestamp/label facts instead.
            eligible = (row['label_status']=='MATURE'
                        and row['exclusion_reason'] in (None,'PURGED_EMBARGO')
                        and row.get('y_log_percent') is not None)
            if not eligible:
                exclusions.append({'key':key,'reason':'LABEL_VALUE_NOT_EXPORTED'
                                   if row['label_status']=='MATURE' and row.get('y_log_percent') is None
                                   else row['exclusion_reason'] or row['label_status']})
                continue
            if available < begin-DAY:
                sets['outer_train'].append(key)
                if available < inner_begin-DAY:
                    sets['inner_train'].append(key)
                elif stamp >= inner_begin:
                    sets['inner_validation'].append(key)
            elif stamp < begin:
                exclusions.append({'key':key,'reason':'OUTER_PURGE_EMBARGO'})
            if begin <= stamp < stop:
                if available < stop:
                    sets['outer_diagnostic'].append(key)
                else:
                    exclusions.append({'key':key,'reason':'OUTER_END_LABEL_PURGE'})
        results.append({'outer_start':begin,'outer_end':stop,'inner_start':inner_begin,
                        'membership':sets,'counts':{k:len(v) for k,v in sets.items()},'exclusions':exclusions})
    return {'version':'opportunity_nested_dev_v1.0.1','scope':'EXPOSED_RESEARCH',
            'label_window_seconds':DAY,'embargo_seconds':DAY,'folds':results,
            'variable_holding_supported':False,'independent_oos':False,
            'selection_executed':False,'fit_executed':False,'execution_enabled':False}
