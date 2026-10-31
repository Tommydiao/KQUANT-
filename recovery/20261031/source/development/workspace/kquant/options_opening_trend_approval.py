"""Read exact owner decisions; implementation never creates an approval."""
import hashlib
import json
from pathlib import Path

from . import options_opening_trend as trend
from .options_opening_trend_events import PROPOSAL as EVENT_POLICY, APPROVAL as EVENT_APPROVAL

ROOT = Path(__file__).resolve().parents[1]
WEB_POLICY = ROOT / "config/options_opening_trend_web_policy_v1.json"
STRATEGY_APPROVAL = ROOT / "config/review_acceptances/options_opening_trend_o_setup_v1.json"


def status(policy, scope_hash, *, strategy_path=STRATEGY_APPROVAL, event_path=EVENT_APPROVAL,
           event_policy=EVENT_POLICY, web_policy=WEB_POLICY):
    from .options_opening_momentum import POLICY_ID as MOMENTUM_ID
    if policy["policy_id"] == MOMENTUM_ID and strategy_path == STRATEGY_APPROVAL:
        strategy_path = ROOT / "config/review_acceptances/options_opening_momentum_o_setup_v1.json"
    if policy["policy_id"] == MOMENTUM_ID and web_policy == WEB_POLICY:
        web_policy = ROOT / "config/options_opening_momentum_web_policy_v1.json"
    if policy["policy_id"] == MOMENTUM_ID:
        from .options_opening_trend_events import policy_paths
        proposal, approval = policy_paths(policy)
        if event_policy == EVENT_POLICY:
            event_policy = proposal
        if event_path == EVENT_APPROVAL:
            event_path = approval
    event_hash = hashlib.sha256(event_policy.read_bytes()).hexdigest()
    web_hash = hashlib.sha256(web_policy.read_bytes()).hexdigest()
    result = {"qualified_signal_pipeline_enabled": False, "selected_expiry_group": None,
              "strategy_hash": policy["policy_hash"], "scope_hash": scope_hash,
              "event_policy_sha256": event_hash, "web_policy_sha256": web_hash,
              "reasons": ["EXACT_O_SETUP_REQUIRED"]}
    try:
        strategy = json.loads(strategy_path.read_text(encoding="utf-8"))
        event = json.loads(event_path.read_text(encoding="utf-8"))
        common = all(r.get("status") == "APPROVED" and r.get("approved_by") == "OWNER"
                     and r.get("strategy_hash") == policy["policy_hash"] and r.get("scope_hash") == scope_hash
                     for r in (strategy, event))
        if any(r.get("test_only") and path.resolve().is_relative_to(ROOT / "config")
               for r, path in ((strategy, strategy_path), (event, event_path))):
            common = False
        group = strategy.get("selected_expiry_group")
        valid = (bool(scope_hash) and common and strategy.get("policy_id") == policy["policy_id"]
                 and group in policy["expiry_comparison"]
                 and strategy.get("event_policy_sha256") == event_hash and strategy.get("web_policy_sha256") == web_hash
                 and strategy.get("enable_qualified_web_signals") is True
                 and strategy.get("paper_enabled") is False and strategy.get("real_orders_enabled") is False
                 and event.get("policy_id") == policy["event_policy_id"] and event.get("policy_sha256") == event_hash)
        production = strategy_path.resolve().is_relative_to(ROOT / "config")
        if production or strategy.get("release_acceptance") is not None:
            from .options_release_acceptance import verify
            release_record = strategy.get("release_acceptance")
            if release_record is None and production:
                release_path = ROOT / "config/review_acceptances/options_opening_momentum_release_o_setup_p7.json"
                if release_path.is_file():
                    release_record = json.loads(release_path.read_text(encoding="utf-8"))
            release = verify(release_record)
            result["release_acceptance"] = release
            valid = valid and release["status"] == "PASS"
            if release["status"] != "PASS":
                result["reasons"].append(release["reason"])
        if valid:
            result.update(qualified_signal_pipeline_enabled=True, selected_expiry_group=group, reasons=[])
    except (OSError, ValueError, TypeError):
        pass
    return result
