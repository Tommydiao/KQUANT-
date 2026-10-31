import json
from pathlib import Path
from next_windows import build


def test_project_calendar_preserves_deadline_and_no_future_results():
    constraint = json.loads((Path(__file__).parent/'constraint.json').read_text())
    result = build(constraint)
    assert result['t0_utc'] == '2026-10-16T14:30:22Z'
    assert result['deadline_utc'] == '2026-10-23T14:30:22Z'
    assert [row['session'] for row in result['windows']] == [f'2026-10-{day}' for day in range(19, 24)]
    assert result['preferred_complete_observation_sessions'] == ['2026-10-19', '2026-10-20', '2026-10-21']
    for row in result['windows']:
        assert row['applicable_direction_positions_per_variant'] == 1000
        assert all(point['complete_s0'] is None and point['complete_s1'] is None for point in row['checkpoints'])


def test_last_friday_opening_does_not_invent_mature_sixty_minute_labels():
    constraint = json.loads((Path(__file__).parent/'constraint.json').read_text())
    final = build(constraint)['windows'][-1]
    assert final['session'] == '2026-10-23'
    assert not final['all_primary_labels_could_mature_before_delivery']
    assert not any(point['primary_label_could_mature_before_delivery'] for point in final['checkpoints'])
    assert final['checkpoints'][0]['earliest_primary_label_maturity'] == '2026-10-23T14:36:00+00:00'
