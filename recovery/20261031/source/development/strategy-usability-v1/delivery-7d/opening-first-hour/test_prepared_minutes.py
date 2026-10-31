from copy import deepcopy
from datetime import datetime, timedelta, UTC
import json
import pytest

from prepared_minutes import MinutePreparation, partition
from kquant.options_minute_admission import partition as original_partition


def test_decision_preparation_preserves_document_and_rebuilds_changed_content():
    from prepared_minutes import PreparedDecision, decision_key
    pool = MinutePreparation(factory=PreparedDecision)
    original = dict(selected_version_id='a', source_version_ids=['a', 'b'],
                    observed_raw_ids=['a', 'b'], source_semantics={'method': {'version': 'v1'}})
    raw = json.dumps({'decision': original})
    value = pool.prepare(raw)
    assert value == original
    assert value.admission_key == decision_key(original)
    assert pool.prepare(raw) is value
    with pytest.raises(TypeError):
        value['source_semantics']['method']['version'] = 'v2'
    newer = pool.prepare(raw.replace('v1', 'v2'))
    assert newer.admission_key != value.admission_key


def test_immutable_content_shared_and_revision_distinct():
    pool = MinutePreparation(2)
    raw = '{"close":1,"sdk_evidence":{"items":[1,2]}}'
    first = pool.prepare(raw)
    assert pool.prepare(raw) is first
    assert deepcopy(first) is first
    assert json.loads(json.dumps(first)) == json.loads(raw)
    for change in (lambda: first.update(close=2),
                   lambda: first['sdk_evidence']['items'].append(3),
                   lambda: first.__setitem__('close', 2)):
        with pytest.raises(TypeError):
            change()
    revised = pool.prepare(raw.replace('"close":1', '"close":2'))
    assert revised.identity != first.identity
    pool.prepare('{"close":3}')
    assert len(pool.entries) == 2
    assert first['close'] == 1


def test_current_admission_rechecked_at_every_time_boundary():
    opening = datetime(2026, 10, 22, 13, 30, tzinfo=UTC)
    end = opening + timedelta(minutes=1)
    row = dict(symbol='TEST', interval='1m', closed=True,
               open_at=opening.isoformat(), available_at=end.isoformat(),
               received_at=(end+timedelta(seconds=2)).isoformat(),
               open=10, high=11, low=9, close=10, volume=10, turnover=100,
               turnover_source='NATIVE', currency='USD', sdk_evidence={})
    prepared = MinutePreparation().prepare(json.dumps(row))
    for now in (end, end+timedelta(seconds=3)):
        args = dict(symbol='TEST', opening=opening, until=end, now=now)
        assert partition([prepared], **args) == original_partition([row], **args)
    assert not partition([prepared], symbol='TEST', opening=opening, until=end, now=end)['raw']
    assert partition([prepared], symbol='TEST', opening=opening, until=end,
                     now=end+timedelta(seconds=3))['eligible']
