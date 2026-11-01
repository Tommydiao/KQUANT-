"""Content reuse must not turn current authority/time checks into cached verdicts."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
import sqlite3

import pytest

import first_hour_minute_decisions as decisions
from minute_resolution_plan import ResolutionPreparation
from prepared_minutes import PreparedMinute, partition
from kquant import options_one_minute as common
from test_generation_handoff import actual_lane


def native(bar, *, delay=2, close=None, interface='QuoteContext.candlesticks'):
    value = deepcopy(bar)
    end = common.timestamp(value['available_at'])
    received = end + timedelta(seconds=delay)
    value['received_at'] = received.isoformat()
    if close is not None:
        value['close'] = close
    value['sdk_evidence'].update(interface=interface, request_started_at=received.isoformat(),
        clock_evidence=dict(state='VERIFIED_BOUND', uncertainty_ms=1, source_hash='TEST_ONLY',
                            checked_at=end.isoformat()))
    return PreparedMinute(value)


def proof_at(root, now, seconds=60):
    receipt = dict(approved_by='OWNER', status='APPROVED', test_only=True,
        method_hash=common.digest(decisions.LOCAL_METHOD),
        approved_at=(now-timedelta(minutes=10)).isoformat(),
        valid_until=(now+timedelta(seconds=seconds)).isoformat())
    raw = json.dumps(receipt).encode()
    (root/'TEST_ONLY-receipt.json').write_bytes(raw)
    return dict(semantics='CLOSED_SNAPSHOT_ADOPTION', status='ACCEPTED',
        method=deepcopy(decisions.LOCAL_METHOD), acceptance_path='TEST_ONLY-receipt.json',
        acceptance_sha256=sha256(raw).hexdigest())


def test_bound_exact_content_and_eligibility_sets():
    cache = ResolutionPreparation(bound=2)
    a, b, c = [PreparedMinute({'close': n}) for n in (1, 2, 3)]
    pairs = lambda value: [(value.identity, value)]
    calls = []
    def choose(value):
        calls.append(value)
        return value
    assert cache.select(pairs(a), pairs(a), 'm', 'p', lambda: choose(a.identity)) == a.identity
    assert cache.select(pairs(a), pairs(a), 'm', 'p', lambda: choose(None)) == a.identity
    assert len(calls) == 1
    assert cache.select(pairs(a), [], 'm', 'p', lambda: choose(None)) is None
    assert cache.select(pairs(a), [], 'm', 'p', lambda: choose(a.identity)) is None
    for value in (b, c):
        assert cache.select(pairs(value), pairs(value), 'm', 'p', lambda: value.identity) == value.identity
    assert cache.snapshot()['entries'] == 2
    assert cache.snapshot()['authority_cached'] is False
    assert cache.select(pairs(a), pairs(a), 'changed-method', 'p', lambda: None) is None
    assert cache.select(pairs(a), pairs(a), 'changed-method', 'changed-policy', lambda: a.identity) == a.identity
    mutable = [('untrusted', {'close': 1})]
    assert cache.select(mutable, mutable, 'm', 'p', lambda: 'first') == 'first'
    assert cache.select(mutable, mutable, 'm', 'p', lambda: 'second') == 'second'


@pytest.mark.parametrize('case', ['same', 'later_pull', 'later_push_conflict', 'same_time_conflict',
                                   'older_push_conflict', 'wrong_adjustment', 'future'])
def test_selection_differential_and_changed_version(tmp_path, case):
    with actual_lane(tmp_path) as (lane, _, now, _, job, bars, _):
        proof = proof_at(tmp_path, now[0])
        original = native(bars[0])
        rows = [original]
        if case != 'same':
            revision = native(bars[0], delay=1 if case == 'older_push_conflict' else 3,
                close=bars[0]['close']+0.5,
                interface='push' if 'push' in case else 'QuoteContext.candlesticks')
            if case == 'same_time_conflict':
                revision = native(bars[0], delay=2, close=bars[0]['close']+0.5)
            if case == 'wrong_adjustment':
                revision = PreparedMinute({**revision, 'sdk_evidence': {**revision['sdk_evidence'], 'adjustment':'Adjust'}})
                rows = []
            if case == 'future':
                revision = native(bars[0], delay=1000, close=bars[0]['close']+0.5)
            rows.append(revision)
        opening, _ = decisions.session_bounds_utc(job[1])
        classified = partition(rows, symbol=job[0], opening=opening,
                               until=opening+timedelta(minutes=5), now=now[0])
        raw_pairs = list(classified['raw'].items())
        eligible = list(classified['eligible'].items())
        expected = decisions._select_version(eligible, proof) if eligible else None
        cache = ResolutionPreparation()
        for _ in range(2):
            selected = cache.select(raw_pairs, eligible, common.canonical(proof), decisions.POLICY_HASH,
                lambda: decisions._select_version(eligible, proof) if eligible else None)
            assert selected == expected
        if case in {'later_push_conflict', 'same_time_conflict', 'wrong_adjustment'}:
            assert expected is None
        elif case == 'later_pull':
            assert expected == rows[-1].identity
        else:
            assert expected == original.identity
        added = decisions.resolve(lane.path, rows, symbol=job[0], session=job[1].isoformat(),
                                  now=now[0], proof=proof, root=tmp_path)
        assert [row['selected_version_id'] for row in added] == ([expected] if expected else [])


def test_cache_does_not_renew_authority_or_known_at(tmp_path, monkeypatch):
    cache = ResolutionPreparation()
    monkeypatch.setattr(decisions, '_resolution_preparation', cache)
    with actual_lane(tmp_path) as (lane, _, now, _, job, bars, _):
        proof = proof_at(tmp_path, now[0], seconds=10)
        rows = [native(bars[0])]
        args = dict(symbol=job[0], session=job[1].isoformat(), proof=proof, root=tmp_path)
        first = decisions.resolve(lane.path, rows, now=now[0], **args)
        assert len(first) == 1
        assert decisions.resolve(lane.path, rows, now=now[0]+timedelta(seconds=1), **args) == []
        assert cache.snapshot()['hits'] >= 1
        # Only the fresh temporary TEST_ONLY journal is reset to exercise the
        # same pure selection with a different persistence observation time.
        with sqlite3.connect(lane.path) as db:
            db.execute('DELETE FROM two_hour_jobs')
        second = decisions.resolve(lane.path, rows, now=now[0]+timedelta(seconds=2), **args)
        assert second[0]['known_at'] != first[0]['known_at']
        assert second[0]['selected_version_id'] == first[0]['selected_version_id']
        assert second[0]['decision_hash'] != first[0]['decision_hash']
        hits = cache.snapshot()['hits']
        assert decisions.resolve(lane.path, rows, now=now[0]+timedelta(seconds=10), **args) == []
        assert cache.snapshot()['hits'] == hits
        receipt = tmp_path/'TEST_ONLY-receipt.json'
        receipt.write_bytes(receipt.read_bytes().replace(b'APPROVED', b'REVOKED!'))
        assert decisions.resolve(lane.path, rows, now=now[0], **args) == []


def test_new_later_conflict_cannot_reuse_old_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(decisions, '_resolution_preparation', ResolutionPreparation())
    with actual_lane(tmp_path) as (lane, _, now, _, job, bars, _):
        proof = proof_at(tmp_path, now[0])
        original = native(bars[0])
        conflict = native(bars[0], delay=3, close=bars[0]['close']+0.5, interface='push')
        args = dict(symbol=job[0], session=job[1].isoformat(), now=now[0], proof=proof, root=tmp_path)
        first = decisions.resolve(lane.path, [original], **args)
        assert len(first) == 1
        assert decisions.resolve(lane.path, [original, conflict], **args) == []
        start = common.timestamp(original['open_at'])
        assert decisions.accepted(first[0], [original, conflict], symbol=job[0],
                                  start=start, now=now[0], root=tmp_path) is None


def test_batch_is_same_durable_decisions_with_one_writer(tmp_path, monkeypatch):
    with actual_lane(tmp_path) as (lane, _, now, _, job, bars, _):
        proof = proof_at(tmp_path, now[0])
        rows = [native(bar) for bar in bars[:4]]
        expected = decisions.resolve(lane.path, rows, symbol=job[0], session=job[1].isoformat(),
                                     now=now[0], proof=proof, root=tmp_path)
        with sqlite3.connect(lane.path) as db:
            db.execute('DELETE FROM two_hour_jobs')
        calls = []
        append = decisions.append_many
        def observed(path, values):
            calls.append(len(values))
            return append(path, values)
        monkeypatch.setattr(decisions, 'append_many', observed)
        requests = [([row], job[0], job[1].isoformat(), now[0]) for row in rows]
        assert decisions.resolve_batch(lane.path, requests, proof=proof, root=tmp_path)
        actual = decisions.read(lane.path, symbol=job[0], session=job[1].isoformat(), now=now[0])
        assert sorted(actual, key=lambda r:r['open_at']) == sorted(expected, key=lambda r:r['open_at'])
        assert calls == [4]
        assert decisions.resolve_batch(lane.path, requests, proof=proof, root=tmp_path)
        assert calls[-1] == 0


def test_batch_write_cap_falls_back_without_writing(tmp_path, monkeypatch):
    with actual_lane(tmp_path) as (lane, _, now, _, job, bars, _):
        proof = proof_at(tmp_path, now[0])
        monkeypatch.setattr(decisions, 'WRITE_BOUND', 1)
        requests = [([native(bar)], job[0], job[1].isoformat(), now[0]) for bar in bars[:2]]
        assert decisions.resolve_batch(lane.path, requests, proof=proof, root=tmp_path) is False
        assert decisions.read(lane.path, symbol=job[0], session=job[1].isoformat(), now=now[0]) == []
        with pytest.raises(ValueError, match='PREPARATION_BATCH_BOUND'):
            decisions.resolve_batch(lane.path, requests*5, proof=proof, root=tmp_path)


def test_actual_lane_batch_rechecks_time_boundary_and_persists_before_handoff(tmp_path, monkeypatch):
    import first_hour
    with actual_lane(tmp_path) as (lane, _, now, key, job, bars, reviews_path):
        proof = proof_at(tmp_path, now[0])
        reviews_path.write_text(json.dumps({'canonical_resolution_method':proof}))
        for bar in bars:
            common.save_bar(native(bar), job[1].isoformat(), lane.minute_path)
        calls = []
        original = decisions.resolve
        def observed(*args, **kwargs):
            calls.append(kwargs['now'])
            return original(*args, **kwargs)
        monkeypatch.setattr(decisions, 'resolve', observed)
        reviews = lane._source_reviews()
        with lane._input_batch(entries=[(key,job)], reviews=reviews):
            at, boundary = lane.input_read_context.decisions_produced_until[key]
            assert at == now[0] and boundary > at
            generation = lane._prepare_generation(key, job, lane.input_epochs.get(job[:2],0),
                                                  reviews, first_hour.policies())
            assert not calls
            assert generation.decisions
            assert generation.decision_token[0] == len(generation.decisions)
            now[0] = boundary
            lane._checkpoint_inputs(key, job, now[0], reviews, produce_decisions=True)
            assert calls == [boundary]
            now[0] = at-timedelta(milliseconds=1)
            lane._checkpoint_inputs(key, job, now[0], reviews, produce_decisions=True)
            assert calls[-1] == now[0]
        assert lane.input_read_context.decisions_produced_until == {}
