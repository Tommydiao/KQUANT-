"""Undeployed window adapter: reuse existing math without changing frozen policies."""
from copy import deepcopy
from datetime import timedelta

from kquant import options_one_minute as common
from kquant import options_opening_momentum as s0
from kquant import options_intraday_comparison as s1
from kquant import options_opening_trend as trend
from kquant.market_clock import is_trading_day, session_bounds_utc

WINDOW_ID = "OPENING_FIRST_HOUR_RESEARCH_V1"
OFFSETS = tuple(range(5, 60, 5))
WINDOW_END_MINUTES = 60


def load_policy():
    return policies()['S0']


def policies():
    result = {}
    for variant, parent in (("S0", s0.load_policy()), ("S1", s1.load_policy())):
        policy = deepcopy(parent)
        policy.pop("policy_hash", None)
        policy.update(policy_id=parent["policy_id"] + "-FIRST-HOUR-V1",
                      parent_policy_hash=parent["policy_hash"], window_id=WINDOW_ID,
                      checkpoint_minutes=list(OFFSETS), breakout_end_minutes=list(OFFSETS),
                      last_confirmation_minutes=55, entry_window_minutes=WINDOW_END_MINUTES)
        policy["policy_hash"] = common.digest(policy)
        result[variant] = policy
    return result


def schedule(day):
    if not is_trading_day(day):
        return {"window_id": WINDOW_ID, "state": "MARKET_CLOSED", "checkpoints": []}
    opening, closing = session_bounds_utc(day)
    cutoff = min(opening + timedelta(minutes=WINDOW_END_MINUTES), closing)
    return {"window_id": WINDOW_ID, "state": "SCHEDULED_NOT_RUN", "cutoff": cutoff,
            "reconciliation_at": cutoff,
            "checkpoints": [{"at": opening + timedelta(minutes=m),
                             "deadline": min(opening + timedelta(minutes=m, seconds=300), cutoff)}
                            for m in OFFSETS if opening + timedelta(minutes=m) < cutoff]}


def evaluate(*, _policy_pair=None, **arguments):
    from method_snapshot import calculation_scope
    with calculation_scope():
        return _evaluate(_policy_pair=_policy_pair, **arguments)


def prepare_inputs(*, symbol, bars, opening, checkpoint, now, source_decisions=None):
    """Only generation-bound minute admission/aggregation; no strategy verdict."""
    from prepared_minutes import freeze
    checks = {}
    rows, missing = trend.complete_minutes(bars, symbol=symbol, opening=opening,
        until=checkpoint, now=now, diagnostics=checks, price_only=True,
        source_decisions=source_decisions)
    return freeze((rows, missing, checks, s0.price_aggregate(rows) if not missing else []))


def _evaluate(*, _policy_pair=None, _minute_inputs=None, **arguments):
    """Explicit checkpoint only; one legal minute preparation for four results."""
    opening, closing, now = map(common.timestamp, (
        arguments["opening"], arguments["closing"], arguments["now"]))
    end = common.timestamp(arguments["checkpoint"])
    if (end - opening).total_seconds() / 60 not in OFFSETS or end > now:
        raise ValueError("INVALID_FIRST_HOUR_CHECKPOINT")
    deadline = min(end + timedelta(seconds=300), opening + timedelta(minutes=WINDOW_END_MINUTES), closing)
    if now >= deadline:
        raise ValueError("ORIGINAL_DEADLINE_EXCEEDED_NO_REPLAY_AS_LIVE")
    policy = policies() if _policy_pair is None else _policy_pair
    rows, missing, checks, groups = (_minute_inputs if _minute_inputs is not None else
        prepare_inputs(symbol=arguments['symbol'], bars=arguments['bars'], opening=opening,
            checkpoint=end, now=now, source_decisions=arguments.get('source_decisions')))
    session = opening.astimezone(common.NY).date().isoformat()
    valid = s0.price_reference_valid(arguments["reference"], arguments["symbol"], session, now)
    prepared = (rows, missing, checks, valid, groups)
    # S1 checks its own intraday contract at compute time, independently of S0.
    intraday = s1.intraday_contract(arguments['reference'], rows,
        symbol=arguments['symbol'], session=session, now=now) if not missing else None
    s1_prepared = (intraday, common.digest([intraday, rows]), groups) if intraday else None
    output = []
    for right in ("CALL", "PUT"):
        baseline = s0.evaluate(right=right, **arguments, policy=policy["S0"], _prepared=prepared)
        challenger = s1.evaluate_s1(symbol=arguments["symbol"], right=right, rows=rows,
            missing=missing, minute_check=checks, reference=arguments["reference"],
            opening=opening, closing=closing, now=now, checkpoint=end,
            scope_hash=arguments["scope_hash"], policy=policy["S1"], _prepared=s1_prepared)
        for variant, value in (("S0", baseline), ("S1", challenger)):
            value.update(window_id=WINDOW_ID, variant=variant,
                         original_deadline_at=deadline.isoformat(),
                         source_method_version=value.get("data_method_id"),
                         launch_state="UNDEPLOYED_RESEARCH_ADAPTER")
            output.append(value)
    return output


def evaluate_comparison_pair(**arguments):
    """Keep the existing persistence envelope without merging policy identities."""
    rows = evaluate(**arguments)
    output = []
    for right in ('CALL', 'PUT'):
        original = next(r for r in rows if r['variant'] == 'S0' and r['right'] == right)
        challenger = next(r for r in rows if r['variant'] == 'S1' and r['right'] == right)
        economic_id = common.digest([WINDOW_ID, arguments['scope_hash'], original['session'],
                                     original['symbol'], right, original['calculation_bar_end']])
        original['economic_opportunity_id'] = economic_id
        challenger.update(parent_evaluation_id=original['evaluation_id'],
                          economic_opportunity_id=economic_id, research_strategy='opening_momentum',
                          reference_collection_owner='S0' if original['state'] == 'NUMERIC_PASS' else 'S1')
        original['strategy_comparison'] = dict(schema='S0_S1_COMPARISON_V1', window_id=WINDOW_ID,
            s0={k: original[k] for k in ('evaluation_id', 'policy_id', 'policy_hash', 'state', 'reasons')},
            s1=challenger, economic_opportunity_id=economic_id,
            cohort='PAIRED_POLICY_COMPARISON' if original['state'] in ('NO_TRIGGER', 'NUMERIC_PASS')
            and challenger['state'] in ('NO_TRIGGER', 'NUMERIC_PASS') else
                'S1_INTRADAY_ONLY_DATA' if original['state']=='INCOMPLETE' and
                challenger['state'] in ('NO_TRIGGER','NUMERIC_PASS') else 'INPUT_NOT_PAIRED',
            amplitude=challenger.get('amplitude'), qualified_signal=False,
            option_cost={'state': 'REFERENCE_CONTRACT_UNAVAILABLE', 'round_trip_cost_per_unit': None},
            outcome={'state': 'NOT_MEASURED', 'y60_pct': None})
        output.append(original)
    return output
