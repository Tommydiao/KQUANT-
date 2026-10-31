"""Pre-registered offline contrast, deliberately absent from production routing."""
from hashlib import sha256
from pathlib import Path

from . import options_one_minute as common
from . import options_opening_momentum as s0

POLICY_ID = "STRAT-SESSION-DIRECTION-5M-CHALLENGER-V1"
PROTOCOL = Path(__file__).resolve().parents[1] / "docs/R58_S1_PREREGISTRATION.md"


def policy():
    value = s0.load_policy()
    value.pop("policy_hash")
    value.update(policy_id=POLICY_ID, previous_close_direction_gate=False,
                 protocol_sha256=sha256(PROTOCOL.read_bytes()).hexdigest(), research_only=True)
    return {**value, "policy_hash": common.digest(value)}


def evaluate(**arguments):
    if "policy" in arguments:
        raise ValueError("S1_PARAMETERS_FROZEN")
    result = s0.evaluate(**arguments, policy=policy())
    result.update(research_strategy="opening_momentum_s1", test_only=True, production_routing=False)
    return result
