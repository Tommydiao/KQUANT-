from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json

import pytest

from kquant import options_opening_momentum as model
from kquant import options_opening_trend as trend
from kquant.options_opening_trend_approval import status


@pytest.fixture
def isolated_comparison_policy(tmp_path, monkeypatch):
    # Exercise version isolation without reconstructing an unavailable historical policy.
    policy = model.load_policy()
    policy.pop('policy_hash')
    policy.update(policy_id=trend.POLICY_ID, test_only=True,
                  version='TEST_ONLY_VERSION_ISOLATION_NOT_HISTORICAL')
    path = tmp_path / 'TEST_ONLY-comparison-policy.json'
    path.write_text(json.dumps(policy), encoding='utf-8')
    monkeypatch.setattr(trend, 'CONFIG', path)
    from kquant import options_opening_trend_approval as approval
    contract = tmp_path / 'TEST_ONLY-source-contract.json'
    contract.write_text('{"test_only": true}', encoding='utf-8')
    monkeypatch.setattr(approval, 'status', lambda p, scope: status(
        p, scope, strategy_path=tmp_path / 'absent-owner', event_path=tmp_path / 'absent-event',
        event_policy=contract, web_policy=contract))
    return path


def inputs(right="CALL", minutes=5):
    opening = datetime(2026, 10, 2, 13, 30, tzinfo=UTC)
    rows = []
    for index in range(minutes):
        start = opening + timedelta(minutes=index)
        o = 100 + index
        values = (o, o + 1, o - .1, o + .9)
        if right == "PUT":
            o, h, l, c = values
            values = (200 - o, 200 - l, 200 - h, 200 - c)
        end = start + timedelta(minutes=1)
        rows.append(dict(symbol="TEST", interval="1m", open_at=start.isoformat(),
                         available_at=end.isoformat(), received_at=(end + timedelta(milliseconds=50)).isoformat(),
                         closed=True, **dict(zip(("open", "high", "low", "close"), values))))
    return dict(symbol="TEST", right=right, bars=rows, history={},
                reference=dict(symbol="TEST", session="2026-10-02", previous_close=99 if right == "CALL" else 101,
                               price_comparable=True, price_basis_evidence_hash="basis", source_hash="quote",
                               received_at=opening.isoformat(), time_evidence={"state": "ORDERED"},
                               volume_unit="UNKNOWN", reference_blockers=["NATIVE_CANDLESTICK_UNIT_EVIDENCE_MISSING"]),
                opening=opening, closing=opening + timedelta(hours=6, minutes=30),
                now=opening + timedelta(minutes=minutes, seconds=1), scope_hash="scope")


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_first_complete_price_bar_without_volume_or_history(right):
    result = model.evaluate(**inputs(right))
    assert result["state"] == "NUMERIC_PASS"
    assert not result["qualified_signal"]
    assert result["deadline_at"] == "2026-10-02T13:40:00+00:00"
    assert result["factor_evidence"]["auxiliary"]["state"] == "UNVERIFIED"
    assert result["factor_evidence"]["checks"]["prior_breakout"]
    assert result["research_strategy"] == "opening_momentum"


def test_later_bar_requires_prior_breakout():
    args = inputs(minutes=10)
    assert model.evaluate(**args)["state"] == "NUMERIC_PASS"
    args["bars"][0]["high"] = 200
    result = model.evaluate(**args)
    assert "MOMENTUM_PRIOR_BREAKOUT_NOT_MET" in result["reasons"]


@pytest.mark.parametrize("change,reason", [
    ("reference", "PRICE_REFERENCE_UNVERIFIED"),
    ("missing", "CONTIGUOUS_SESSION_MINUTES_MISSING"),
    ("zero", "ZERO_BAR_RANGE"),
    ("direction", "MOMENTUM_DAILY_DIRECTION_NOT_MET"),
])
def test_price_failures_remain_blocking(change, reason):
    args = inputs()
    if change == "reference":
        args["reference"]["time_evidence"]["state"] = "FUTURE"
    elif change == "missing":
        args["bars"].pop(1)
    elif change == "zero":
        for row in args["bars"]:
            row.update(open=100, high=100, low=100, close=100)
    else:
        args["reference"]["previous_close"] = 110
    assert reason in model.evaluate(**args)["reasons"]


def test_asof_conflict_does_not_use_future_revisions():
    args = inputs()
    args["bars"][0]["sdk_evidence"] = {"interface": "QuoteContext.set_on_candlestick"}
    revision = deepcopy(args["bars"][0])
    revision.update(open=100.2, received_at=(args["now"] + timedelta(seconds=1)).isoformat(),
                    sdk_evidence={"interface": "QuoteContext.candlesticks"})
    args["bars"].append(revision)
    assert model.evaluate(**args)["state"] == "NUMERIC_PASS"
    revision["received_at"] = args["now"].isoformat()
    result = model.evaluate(**args)
    assert result["reasons"] == ["SOURCE_CONFLICT"]


def test_first_push_previous_close_low_is_a_recheck_clue_not_a_veto():
    args = inputs()
    args["bars"][0].update(low=99, sdk_evidence={"interface": "QuoteContext.set_on_candlestick"})
    result = model.evaluate(**args)
    assert result["state"] == "NUMERIC_PASS"
    assert result["warnings"] == ["FIRST_MINUTE_SOURCE_RECHECK_REQUIRED"]


def test_pinned_checkpoint_never_extends_deadline():
    args = inputs()
    args["checkpoint"] = args["opening"] + timedelta(minutes=5)
    args["now"] = args["opening"] + timedelta(minutes=10)
    result = model.evaluate(**args)
    assert result["state"] == "EXPIRED"
    assert result["confirmation_at"] == args["checkpoint"].isoformat()
    args = inputs(minutes=25)
    assert model.evaluate(**args)["deadline_at"] == "2026-10-02T14:00:00+00:00"
    args["now"] = args["opening"] + timedelta(minutes=30)
    assert model.evaluate(**args)["state"] == "ENTRY_WINDOW_CLOSED"


def test_first_bar_cannot_be_used_before_close():
    args = inputs()
    args["now"] = args["opening"] + timedelta(minutes=4, seconds=59)
    assert model.evaluate(**args)["state"] == "WAIT_TREND"


def test_invalid_auxiliary_values_do_not_become_verified_or_block_price():
    args = inputs()
    args["reference"].update(volume_unit="SHARES", volume_unit_evidence_hash="unit")
    for row in args["bars"]:
        row.update(volume=float("nan"), turnover=100)
    result = model.evaluate(**args)
    assert result["state"] == "NUMERIC_PASS"
    assert result["factor_evidence"]["auxiliary"]["vwap"] is None
    assert result["factor_evidence"]["auxiliary"]["warnings"] == ["AUXILIARY_AMOUNT_UNAVAILABLE"]


def test_new_policy_cannot_reuse_old_hash_or_approval(tmp_path, isolated_comparison_policy):
    policy = model.load_policy()
    assert policy["policy_hash"] != trend.load_policy()["policy_hash"]
    result = status(policy, "scope", strategy_path=tmp_path / "absent", event_path=tmp_path / "absent")
    assert not result["qualified_signal_pipeline_enabled"]
    with pytest.raises(ValueError, match="POLICY_OR_SCOPE_CHANGED"):
        model.policy_for({"policy_id": model.POLICY_ID, "policy_hash": trend.load_policy()["policy_hash"]})


def test_status_returns_only_requested_strategy_and_five_checkpoints(tmp_path, monkeypatch, isolated_comparison_policy):
    from kquant import options_opening_trend_store as store
    from kquant.status_worker import query_opening_trend
    args = inputs()
    main, research = tmp_path / "main.db", tmp_path / "research.db"
    main.touch()
    store.initialize(research)
    store.persist([model.evaluate(**args)], research)
    monkeypatch.setattr("kquant.options_two_hour_data.universe", lambda path: {
        "scope_hash": "scope", "items": [{"symbol": "TEST", "identity_status": "verified"}]})
    result = query_opening_trend(main, trend_path=research, now=args["now"], research_strategy="opening_momentum")
    assert result["policy"]["policy_id"] == model.POLICY_ID
    assert len(result["evaluations"]) == 1
    assert result["checkpoint_coverage"]["checkpoints"][0]["numeric_directions"] == 1
    assert result["candidates"] == []
    old = query_opening_trend(main, trend_path=research, now=args["now"])
    assert old["evaluations"] == []


def test_manual_policy_keeps_new_strategy_snapshot(tmp_path):
    from kquant import options_one_minute as common
    from kquant import options_opening_trend_store as store
    from kquant import options_one_minute_manual as manual
    args = inputs()
    position_db, research = tmp_path / "manual.db", tmp_path / "research.db"
    common.initialize(position_db)
    store.initialize(research)
    evaluation = model.evaluate(**args)
    store.persist([evaluation], research)
    # Binding is verified without manufacturing a formal candidate or a broker fill.
    original = manual.open_report(dict(operation_key="test-momentum-manual-0001",
        evaluation_id=evaluation["evaluation_id"], contract_id="TEST261005C100000.US",
        quantity=1, multiplier=100, entry_price=1, underlying_entry_price=104.9,
        executed_at=args["now"].isoformat()), reviewer="test-only@example.invalid",
        now=args["now"], path=position_db, trend_path=research)
    assert original["policy_snapshot"]["policy_id"] == model.POLICY_ID


def test_checkpoint_journal_restores_original_slot_and_expires(tmp_path):
    from kquant import options_opening_momentum_journal as journal
    args = inputs()
    path = tmp_path / "journal.db"
    journal.initialize(path)
    day = args["opening"].date()
    key = ("opening_momentum", day.isoformat(), "TEST", 1)
    job = ("TEST", day, [], "scope", args["reference"])
    job_id = journal.begin(path, key, job, args["now"])
    assert journal.restore(path, args["now"])[key] == job
    assert journal.restore(path, args["opening"] + timedelta(minutes=10)) == {}
    journal.finish(path, job_id)
    assert journal.restore(path, args["now"]) == {}
