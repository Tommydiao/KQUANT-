from capture_delivery import summarize

POINT = '2026-10-16T13:35:00+00:00'
def row(state='NO_TRIGGER', at='2026-10-16T13:35:01+00:00', **kw):
    return dict(evaluation_id=at,symbol='TEST',right='CALL',evaluated_at=at,state=state,
        checkpoint=POINT,factor_state='FULL_INTRADAY_RESEARCH',momentum=.7,q=.9,reasons='[]',**kw)

def test_late_full_is_not_timely_and_missing_direction_remains():
    result = summarize([row(at='2026-10-16T13:40:00+00:00')],['TEST'],[POINT])
    assert result['latest_full_including_late'] == 1
    assert result['full_timely'] == 0
    assert result['expected_direction_checkpoints'] == 2
    assert result['missing_direction_checkpoints'] == 1

def test_revision_conflict_cannot_leave_full_credit():
    rows = [row(),row('INCOMPLETE',at='2026-10-16T13:35:02+00:00')]
    result = summarize(rows,['TEST'],[POINT])
    assert result['first_full'] == 1
    assert result['full_timely'] == 0

def test_unknown_fee_and_page_counts_not_invented_by_factor_count():
    result = summarize([row('NUMERIC_PASS')],['TEST','GWH'],[POINT])
    assert result['full_timely'] == 1
    assert result['completion_ratio'] == .25
    assert result['complete_objects_all_checkpoints'] == 0
    assert result['unique_technical_events'] == 1

def test_partial_factor_is_not_full():
    sample = row()
    sample['factor_state'] = 'PARTIAL_PRICE_COMPONENTS'
    assert summarize([sample],['TEST'],[POINT])['full_timely'] == 0
