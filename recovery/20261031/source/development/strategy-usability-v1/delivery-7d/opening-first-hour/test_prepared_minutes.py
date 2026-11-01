from copy import deepcopy
from datetime import datetime, timedelta, UTC
import json
import pytest

from prepared_minutes import MinutePreparation, partition
from kquant.options_minute_admission import partition as original_partition


@pytest.mark.parametrize('change', ['same','delivery','before_close','ohlc','interface','missing','invalid'])
def test_prepared_semantic_identity_matches_journal_contract(change):
    from prepared_minutes import PreparedMinute, semantic_identity
    from kquant.options_one_minute import digest, timestamp
    row = dict(symbol='TEST',open_at='2026-10-22T13:30:00+00:00',
               available_at='2026-10-22T13:31:00+00:00',received_at='2026-10-22T13:31:01+00:00',
               open=10,high=11,low=9,close=10,volume=10,sdk_evidence={'interface':'pull'})
    if change == 'delivery': row['received_at'] = '2026-10-22T13:31:02+00:00'
    if change == 'before_close': row['received_at'] = '2026-10-22T13:30:59+00:00'
    if change == 'ohlc': row['close'] = 11
    if change == 'interface': row['sdk_evidence']['interface'] = 'push'
    if change == 'missing': del row['received_at']
    if change == 'invalid': row['received_at'] = 'invalid'
    fields = ('symbol','open_at','close_at','available_at','provider_time','open','high','low','close',
              'volume','turnover','amount','confirmed')
    expected = {key:row[key] for key in fields if key in row}
    expected['interface'] = row.get('sdk_evidence',{}).get('interface')
    try:
        expected['received_before_available'] = timestamp(row['received_at']) < timestamp(row['available_at'])
    except (KeyError,TypeError,ValueError):
        expected['received_before_available'] = 'UNVERIFIED'
    assert PreparedMinute(row).semantic_identity == semantic_identity(row) == digest(expected)


def test_source_bundle_is_content_bound_without_cross_read_cache():
    from prepared_minutes import PreparedSources, freeze
    from kquant.options_one_minute import digest
    original = {'method': {'status': 'ACCEPTED'}, 'instruments': {'A': {'version': 1}}}
    first = PreparedSources(original)
    assert first.identity == digest(original)
    assert freeze(first) is first and deepcopy(first) is first
    with pytest.raises(TypeError):
        first['instruments']['A']['version'] = 2
    original['instruments']['A']['version'] = 2
    second = PreparedSources(original)
    assert first.identity != second.identity
    assert first['instruments']['A']['version'] == 1
    assert second['instruments']['A']['version'] == 2


@pytest.mark.parametrize('decision', [False, True])
def test_evidence_metadata_preserves_boundaries_and_live_file_bytes(tmp_path, decision):
    from prepared_minutes import PreparedMinute, PreparedDecision
    from prepared_generation import next_boundary, source_files
    now = datetime(2026, 10, 22, 13, 30, tzinfo=UTC)
    proof = {'source_path': 'source.json', 'known_at': now.isoformat(),
             'valid_until': (now + timedelta(seconds=20)).isoformat(),
             'clock': {'state': 'VERIFIED_BOUND', 'checked_at': now.isoformat()},
             'other': [{'approved_at': 'invalid'}, {'available_at': None}],
             'nested': {'acceptance_path': 'owner.json'}}
    raw = {'source_semantics': proof, 'repeated': [proof, proof],
           'received_at': (now + timedelta(seconds=2)).isoformat()}
    value = PreparedDecision({'decision': raw}) if decision else PreparedMinute(raw)
    for offset in (-1, 0, 2, 20, 899, 900):
        point = now + timedelta(seconds=offset)
        deadline = now + timedelta(seconds=1200)
        assert next_boundary(value, point, deadline) == next_boundary(raw, point, deadline)
    source = tmp_path / 'source.json'
    source.write_text('AAAA')
    (tmp_path / 'owner.json').write_text('owner')
    before = source_files(tmp_path, value)
    assert before == source_files(tmp_path, raw)
    source.write_text('BBBB')
    assert source_files(tmp_path, value) == source_files(tmp_path, raw) != before
    with pytest.raises(TypeError):
        value._evidence_metadata = (frozenset(), frozenset())
    raw['received_at'] = (now + timedelta(seconds=30)).isoformat()
    assert next_boundary(value, now, deadline) == now + timedelta(seconds=2)
    assert next_boundary(raw, now, deadline) == now + timedelta(seconds=20)


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
