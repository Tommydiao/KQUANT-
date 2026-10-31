"""Only isolated databases and explicitly synthetic facts/owner decisions."""
from datetime import timedelta
from hashlib import sha256
import json

import pytest

from test_r58_signal_recovery import reference, proof
from kquant import options_price_reference as prices
from kquant import options_opening_momentum as model
from kquant import options_opening_trend_store as store
from kquant import options_opening_trend_approval as approvals
from kquant import options_opening_trend_reference as sources
from kquant.options_opening_trend_pipeline import step, contract_record
from kquant.options_opening_trend_current import current


def prepare(tmp_path, monkeypatch):
    args, quote, reviews = reference(tmp_path, monkeypatch)
    now = args["now"]
    args["reference"] = prices.build(quote, symbol="TEST", session="2026-10-02", now=now,
        reviews=reviews, root=tmp_path)
    evaluation = model.evaluate(**args)
    assert evaluation["state"] == "NUMERIC_PASS"
    policy = model.load_policy()
    from kquant.options_opening_trend_events import policy_paths
    event_policy, _ = policy_paths(policy)
    web_policy = sources.ROOT / "config/options_opening_momentum_web_policy_v1.json"
    strategy = dict(test_only=True, status="APPROVED", approved_by="OWNER", strategy_hash=policy["policy_hash"],
        scope_hash="scope", policy_id=policy["policy_id"], selected_expiry_group="extended",
        event_policy_sha256=sha256(event_policy.read_bytes()).hexdigest(),
        web_policy_sha256=sha256(web_policy.read_bytes()).hexdigest(), enable_qualified_web_signals=True,
        paper_enabled=False, real_orders_enabled=False)
    event = dict(test_only=True, status="APPROVED", approved_by="OWNER", strategy_hash=policy["policy_hash"],
        scope_hash="scope", policy_id=policy["event_policy_id"], policy_sha256=strategy["event_policy_sha256"])
    strategy_path, event_path = tmp_path / "owner-test-only.json", tmp_path / "event-test-only.json"
    strategy_path.write_text(json.dumps(strategy))
    event_path.write_text(json.dumps(event))
    parser = approvals.status
    def approved(policy, scope):
        return parser(policy, scope, strategy_path=strategy_path, event_path=event_path,
                      event_policy=event_policy, web_policy=web_policy)
    monkeypatch.setattr(approvals, "status", approved)
    snapshot = dict(contract_symbol="TEST261006C105000.US", underlying_symbol="TEST", direction="CALL",
        expiry_date="2026-10-06", strike_price=105, currency="USD", contract_multiplier=100, delta=.525,
        bid=1, ask=1.01, bid_size=100, ask_size=200, bbo_received_at=now.isoformat(),
        calc_received_at=now.isoformat(), contract_validity="UNEXPIRED", depth_status="available")
    identity = snapshot["contract_symbol"]
    contracts = dict(depth_units=proof(tmp_path, now, interface="US_OPTION_DEPTH", raw_units_per_contract=100),
        deliverables={identity: proof(tmp_path, now, contract_symbol=identity, underlying="TEST", deliverable_type="STANDARD", adjusted=False)},
        quote_multipliers={identity: proof(tmp_path, now, interface="US_OPTION_QUOTE", contract_symbol=identity,
            underlying="TEST", multiplier_field="contract_multiplier", multiplier=100)})
    row = contract_record(snapshot, evidence=contracts, root=tmp_path, now=now)

    class Services:
        def event(self, *args):
            return dict(trade_eligible=True, valid_until=(now + timedelta(seconds=60)).isoformat(),
                event_decision=dict(decision="WARN", warnings=["TEST_ONLY_COVERAGE_WARNING"],
                    checked_at=now.isoformat(), valid_until=(now + timedelta(seconds=60)).isoformat()),
                sources={"test": {"valid_until": (now + timedelta(minutes=10)).isoformat()}})
        def expiries(self, *args): return {"expiries": ["2026-10-06"]}
        def chain(self, *args): return {"contracts": [{"call_symbol": identity, "strike_price": 105}]}
        def greeks(self, ids): return {"items": [{"contract_symbol": identity, "delta": .525}]}
        def contract(self, *args): return row
        def spot(self, *args): return dict(symbol="TEST", last=105, received_at=now.isoformat())
        def scope_hash(self): return "scope"
        def approval(self, policy, scope): return approved(policy, scope)
        def current_trend(self, original, checked): return current(original, args["bars"], now=checked)
        def contract_evidence(self, record, *, now, binding=None):
            return sources.contract_sources(record, contracts, root=tmp_path, now=now, binding=binding)
    return args, evaluation, Services(), strategy_path


def test_exact_approval_positive_specific_contract_uses_production_functions(tmp_path, monkeypatch):
    args, original, services, strategy_path = prepare(tmp_path, monkeypatch)
    path = tmp_path / "isolated.db"
    store.initialize(path)
    store.persist([original], path)
    job = dict(evaluation=original, progress={})
    for _ in range(6):
        progress, _, revision = step(job, services, clock=lambda: args["now"])
        job["progress"] = progress
    assert revision["state"] == "QUALIFIED"
    assert revision["valid_until"] == (args["now"] + timedelta(seconds=3)).isoformat()
    persisted = store.append_revision(original["evaluation_id"], revision, path)
    actual = store.status(path=path, session=original["session"], now=args["now"], scope_hash="scope", policy=model.load_policy(), compact=True)
    assert actual["candidates"][0]["contract_id"] == "TEST261006C105000.US"
    fast = store.current_cards(path=path, session=original["session"], scope_hash="scope",
        now=args["now"], policy=model.load_policy())
    assert fast["candidates"][0]["contract_id"] == "TEST261006C105000.US"
    assert not model.load_policy()["qualified_publication_enabled"]
    assert store.status(path=path, session=original["session"], now=args["now"] + timedelta(seconds=3), scope_hash="scope", policy=model.load_policy())["candidates"] == []
    broken = json.loads(strategy_path.read_text())
    broken["scope_hash"] = "wrong"
    strategy_path.write_text(json.dumps(broken))
    assert not approvals.status(model.load_policy(), "scope")["qualified_signal_pipeline_enabled"]
    assert persisted["deadline_at"] == original["deadline_at"]


@pytest.mark.parametrize("value", [False, "false", None, 1])
def test_native_standard_is_not_truthiness_or_multiplier(tmp_path, value):
    from test_options_opening_trend_reference import NOW
    from kquant import options_one_minute as common
    row = dict(strike_price=105, call_symbol="TEST261006C105000.US", put_symbol="TEST261006P105000.US",
        is_standard=value, raw_standard=value, raw_standard_type=type(value).__name__)
    response = dict(symbol="TEST", expiry_date="2026-10-06", contracts=[row], source="longbridge_option_chain",
        sdk_version="test-only", sdk_interface="QuoteContext.option_chain_info_by_date", requested_at=NOW.isoformat(), received_at=NOW.isoformat())
    response["source_hash"] = common.digest(response)
    official = dict(source_kind="OFFICIAL_INTERFACE_FACT", review_method="PROGRAMMATIC_DOCUMENT_REVIEW")
    facts = {"standard_definition": proof(tmp_path, NOW, fact_type="OPTION_STANDARD_CHAIN", **official),
             "equity_specification": proof(tmp_path, NOW, fact_type="EQUITY_STANDARD_SPECIFICATION",
                 source_url="https://www.theocc.com/clearance-and-settlement/clearing/equity-options-product-specifications", **official)}
    evidence = dict(provider_standard_chain=facts, ordinary_equities={"TEST": proof(tmp_path, NOW,
        fact_type="ORDINARY_EQUITY_IDENTITY", underlying="TEST", asset_type="US_ORDINARY_EQUITY",
        source_url="https://www.sec.gov/test-only", **official)})
    snapshot = dict(contract_symbol=row["call_symbol"], underlying_symbol="TEST", direction="CALL", expiry_date="2026-10-06", strike_price=105, contract_multiplier=100)
    bound = contract_record(snapshot, evidence=evidence, root=tmp_path, now=NOW,
        chain_evidence={"response": response, "row": row, "right": "CALL"})
    assert bound["deliverable"] == "UNKNOWN"
    row.update(is_standard=True, raw_standard=True, raw_standard_type="bool")
    response["source_hash"] = common.digest({k: v for k, v in response.items() if k != "source_hash"})
    bound = contract_record(snapshot, evidence=evidence, root=tmp_path, now=NOW,
        chain_evidence={"response": response, "row": row, "right": "CALL"})
    assert bound["deliverable"] == "STANDARD"
    assert bound["size_unit_status"] == "UNVERIFIED_NOT_ASSUMED_CONTRACTS"
