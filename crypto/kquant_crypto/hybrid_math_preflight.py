"""Bounded synthetic M3/M4 plumbing only; no filtering, fitting or calibration.

Caller-supplied finite parameter/innovation fixtures are NOT approved priors,
posterior draws, Student-t sampling, or market scenarios. No production gate
can pass this module. Inputs and resource bounds must be explicit.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import random


VERSION = "hybrid-math-preflight-fixture-v1"
SOURCE = "SYNTHETIC_ONLY_NOT_APPROVED_PRIORS"
SYMBOLS = ("BTC", "ETH", "SOL")


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Finite numeric fixture value required")
    return value


def _count(value):
    if type(value) is not int or value <= 0:
        raise ValueError("Explicit positive integer bound required")


def _seed(value):
    if type(value) is not int:
        raise ValueError("Explicit integer seed required")


@dataclass(frozen=True)
class PriorPredictiveFixture:
    """Discrete synthetic prior support: (conditional mean, positive scale).

    Standardized innovations are an explicit separate finite support, not an
    inferred likelihood. Equal-weight support sampling is a fixture convention.
    max_draws is a caller resource bound, never an admission threshold.
    """

    parameters: tuple
    innovations: tuple
    draws: int
    max_draws: int
    seed: int

    def __post_init__(self):
        _count(self.draws)
        _count(self.max_draws)
        _seed(self.seed)
        if self.draws > self.max_draws:
            raise ValueError("Fixture draw budget exceeded")
        parameters = tuple(tuple(pair) for pair in self.parameters)
        innovations = tuple(self.innovations)
        if not parameters or not innovations:
            raise ValueError("Explicit synthetic support required")
        for pair in parameters:
            if len(pair) != 2 or _finite(pair[1]) <= 0:
                raise ValueError("Expected mean and positive scale")
            _finite(pair[0])
        for value in innovations:
            _finite(value)
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "innovations", innovations)


def prior_predictive_fixture(spec):
    if not isinstance(spec, PriorPredictiveFixture):
        raise ValueError("Explicit PriorPredictiveFixture required")
    rng = random.Random(spec.seed)
    means, outcomes = [], []
    for _ in range(spec.draws):
        mean, scale = rng.choice(spec.parameters)
        outcome = _finite(mean + scale * rng.choice(spec.innovations))
        means.append(mean)
        outcomes.append(outcome)
    return {"source_kind": SOURCE, "spec": asdict(spec),
            "conditional_means": means, "predictive_returns": outcomes}


def synchronized_block_fixture(*, rows, block_length, blocks, max_rows, seed):
    """Sample whole aligned consecutive 5m synthetic rows with replacement.

    Row = (UTC epoch seconds, BTC value, ETH value, SOL value). Values are
    arbitrary synthetic scalars, NOT OHLC or executable quotes. A block seam
    is not consecutive history; source timestamps/indices remain explicit.
    """
    for value in (block_length, blocks, max_rows):
        _count(value)
    _seed(seed)
    rows = tuple(tuple(row) for row in rows)
    if not rows or len(rows) > max_rows or block_length * blocks > max_rows:
        raise ValueError("Empty fixture or row budget exceeded")
    for index, row in enumerate(rows):
        if len(row) != 4:
            raise ValueError("One timestamp and all BTC/ETH/SOL values required")
        for value in row:
            _finite(value)
        if row[0] < 0 or row[0] % 300 != 0:
            raise ValueError("Aligned nonnegative five-minute timestamp required")
        if index and row[0] != rows[index - 1][0] + 300:
            raise ValueError("Missing, duplicate or unordered synthetic batch")
    if block_length > len(rows):
        raise ValueError("Insufficient consecutive fixture rows")
    rng = random.Random(seed)
    starts = [rng.randrange(len(rows) - block_length + 1) for _ in range(blocks)]
    return {"source_kind": SOURCE, "symbols": SYMBOLS, "seed": seed,
            "block_length": block_length, "starts": starts,
            "blocks": [rows[start:start + block_length] for start in starts]}


def digest(payload):
    """Canonical JSON SHA256; nonfinite values cannot be evidence."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def seal_fixture(payload, diagnostics):
    """Bind diagnostic observations to this exact artifact, without thresholds.

    Hashes detect content mismatch, not authenticity or statistical validity.
    No Rhat/ESS/divergence cutoff or freshness policy is introduced here.
    """
    # JSON roundtrip breaks caller aliases and enforces the evidence format.
    payload = json.loads(json.dumps(payload, allow_nan=False))
    diagnostics = json.loads(json.dumps(diagnostics, allow_nan=False))
    artifact = {"version": VERSION, "source_kind": SOURCE, "payload": payload}
    report = {"version": VERSION, "artifact_sha256": digest(artifact),
              "observations": diagnostics, "thresholds_approved": False}
    return {"artifact": artifact, "artifact_sha256": digest(artifact),
            "diagnostics": report, "diagnostics_sha256": digest(report)}


def abstention_contract(bundle):
    """Fail closed even for intact fixtures; never authorizes new risk."""
    reason = "ABSTAIN_SYNTHETIC_ONLY_UNAPPROVED_PRIORS_AND_DIAGNOSTICS"
    try:
        artifact, report = bundle["artifact"], bundle["diagnostics"]
        if artifact["version"] != VERSION or report["version"] != VERSION:
            reason = "ABSTAIN_VERSION_MISMATCH"
        elif (digest(artifact) != bundle["artifact_sha256"]
              or digest(report) != bundle["diagnostics_sha256"]
              or report["artifact_sha256"] != bundle["artifact_sha256"]):
            reason = "ABSTAIN_HASH_MISMATCH"
        elif artifact["source_kind"] != SOURCE or report["thresholds_approved"] is not False:
            reason = "ABSTAIN_UNSUPPORTED_CONTRACT"
    except (KeyError, TypeError, ValueError, OverflowError):
        reason = "ABSTAIN_INVALID_EVIDENCE"
    return {"action": "ABSTAIN", "reason": reason,
            "MODEL_STATUS": "NOT_TRAINED", "MATHEMATICAL_FILTERING_ENABLED": False}
