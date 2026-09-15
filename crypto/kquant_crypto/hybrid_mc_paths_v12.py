"""T20 DEV-only synchronized OHLC paths and frozen risk-input binding.

No filesystem market loader, strategy, sampler model, execution, or admission.
History is an explicitly bounded in-memory sequence of complete three-symbol
batches. The first batch supplies the preceding close and is never sampled.
Execution/valuation along future paths belongs to the protected owner; this
module does not implement another stop/target/day-boundary engine.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import random

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
VERSION = "hybrid_mc_paths_v12_dev_only"
STEP = 300


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _copy(value):
    return json.loads(json.dumps(value, allow_nan=False))


class PathInputError(ValueError):
    def __init__(self, reason, **details):
        self.audit = {"reason": reason, "rejected": True, **details}
        super().__init__(reason)


def _require(condition, reason, **details):
    if not condition:
        raise PathInputError(reason, **details)


def _number(value, name, *, positive=False):
    _require(type(value) in (int, float) and math.isfinite(value), "NONFINITE_OR_NONNUMERIC", field=name)
    _require(value > 0 if positive else value >= 0, "NEGATIVE_OR_ZERO", field=name)
    return value


def _epoch(value, name):
    _require(type(value) is int and value >= 0, "INVALID_EPOCH", field=name)
    return value


@dataclass(frozen=True)
class DevPathSpec:
    history_start: int
    history_end: int  # Exclusive close boundary; includes the preceding-close batch.
    as_of: int
    block_bars: int
    horizon_bars: int
    paths: int
    seed: int
    max_history_bars: int
    max_generated_symbol_bars: int
    history_manifest_hash: str
    source_kind: str

    def __post_init__(self):
        for name in ("history_start", "history_end", "as_of"):
            _epoch(getattr(self, name), name)
            _require(getattr(self, name) % STEP == 0, "UNALIGNED_TIME", field=name)
        _require(self.history_start < self.history_end <= self.as_of, "INVALID_PRE_CUTOFF_WINDOW")
        for name in ("block_bars", "horizon_bars", "paths", "max_history_bars", "max_generated_symbol_bars"):
            _require(type(getattr(self, name)) is int and getattr(self, name) > 0, "INVALID_RESOURCE_BOUND", field=name)
        _require(type(self.seed) is int, "EXPLICIT_INTEGER_SEED_REQUIRED")
        _require(self.paths * self.horizon_bars * len(SYMBOLS) <= self.max_generated_symbol_bars, "OUTPUT_BUDGET_EXCEEDED")
        _require(bool(self.history_manifest_hash), "MANIFEST_BINDING_REQUIRED")
        _require(self.source_kind in {"SYNTHETIC_DEV", "EXPOSED_DEV_AUTHORIZED"}, "UNAUTHORIZED_SOURCE_KIND")


def _ohlc(bar):
    for key in ("open", "high", "low", "close"):
        _number(bar[key], key, positive=True)
    _require(bar["high"] >= max(bar["open"], bar["close"])
             and bar["low"] <= min(bar["open"], bar["close"])
             and bar["low"] <= bar["high"], "ILLEGAL_OHLC")


def audit_history(history, spec):
    """Reject the entire window on gaps; never silently drop/concatenate rows."""
    _require(isinstance(spec, DevPathSpec), "EXPLICIT_DEV_SPEC_REQUIRED")
    _require(isinstance(history, (list, tuple)), "BOUNDED_HISTORY_SEQUENCE_REQUIRED")
    _require(1 < len(history) <= spec.max_history_bars, "HISTORY_BUDGET_OR_LENGTH")
    _require(len(history) * STEP == spec.history_end - spec.history_start, "HISTORY_WINDOW_MISMATCH")
    source_ids = set()
    for index, batch in enumerate(history):
        _epoch(batch["start"], "batch.start")
        _require(batch["start"] == spec.history_start + index * STEP, "GAP_DUPLICATE_OR_UNORDERED", source_index=index)
        _require(set(batch["bars"]) == set(SYMBOLS), "CROSS_SYMBOL_MISSING_OR_EXTRA", source_index=index)
        for symbol in SYMBOLS:
            bar = batch["bars"][symbol]
            _epoch(bar["start"], "bar.start")
            _require(bar["start"] == batch["start"], "CROSS_SYMBOL_TIME_MISMATCH", source_index=index, symbol=symbol)
            _epoch(bar["available_at"], "available_at")
            _require(batch["start"] + STEP <= bar["available_at"] <= spec.as_of, "NOT_CLOSED_OR_AVAILABLE_PRE_CUTOFF",
                     source_index=index, symbol=symbol)
            _ohlc(bar)
            sid = bar["source_bar_id"]
            _require(isinstance(sid, str) and bool(sid) and sid not in source_ids, "MISSING_OR_DUPLICATE_SOURCE_ID")
            source_ids.add(sid)
    _require(spec.block_bars <= len(history) - 1, "INSUFFICIENT_CONTIGUOUS_BLOCK")
    return {"history_start": spec.history_start, "history_end_exclusive": spec.history_end,
            "as_of": spec.as_of, "batches": len(history), "preceding_close_source_index": 0,
            "eligible_block_starts": list(range(1, len(history) - spec.block_bars + 1)),
            "sampling_weights": "uniform over eligible starts, independently with replacement per block/path",
            "cross_symbol_missing": 0, "rejected_blocks": [], "gap_policy": "reject entire input window with PathInputError.audit",
            "history_content_hash": digest(history), "history_manifest_hash": spec.history_manifest_hash}


def generate_paths(history, anchors, spec):
    """Sample common block indices once, reconstruct all three symbols together.

    Ratios: source open / source preceding close, high/open, low/open,
    close/open. At seams the sampled opening ratio is applied to the simulated
    preceding close. No historical absolute timestamps are future clock times.
    """
    audit = audit_history(history, spec)
    _require(set(anchors) == set(SYMBOLS), "ANCHORS_REQUIRE_THREE_SYMBOLS")
    for symbol in SYMBOLS:
        _number(anchors[symbol], symbol, positive=True)
    rng = random.Random(spec.seed)
    paths = []
    for path_index in range(spec.paths):
        previous = dict(anchors)
        batches, starts = [], []
        while len(batches) < spec.horizon_bars:
            start = rng.choice(audit["eligible_block_starts"])
            starts.append(start)
            for offset in range(min(spec.block_bars, spec.horizon_bars - len(batches))):
                index = start + offset
                source, predecessor = history[index], history[index - 1]
                step = len(batches)
                batch = {"start": spec.as_of + step * STEP, "source_index": index,
                         "source_start": source["start"], "source_predecessor_index": index - 1,
                         "block_seam": offset == 0, "bars": {}}
                for symbol in SYMBOLS:
                    bar = source["bars"][symbol]
                    gap_ratio = bar["open"] / predecessor["bars"][symbol]["close"]
                    opening = previous[symbol] * gap_ratio
                    generated = {"open": opening, "high": opening * (bar["high"] / bar["open"]),
                                 "low": opening * (bar["low"] / bar["open"]),
                                 "close": opening * (bar["close"] / bar["open"]),
                                 "source_bar_id": bar["source_bar_id"], "source_available_at": bar["available_at"],
                                 "open_previous_close_ratio": gap_ratio}
                    try:
                        _ohlc(generated)
                    except PathInputError as error:
                        raise PathInputError("ILLEGAL_RECONSTRUCTED_PATH", path_index=path_index,
                                             simulated_step=step, symbol=symbol, rejected_paths=1,
                                             cause=error.audit) from error
                    batch["bars"][symbol] = generated
                    previous[symbol] = generated["close"]
                batches.append(batch)
        paths.append({"path_index": path_index, "block_starts": starts, "batches": batches})
    bank = {"version": VERSION, "scope": "DEV_ONLY", "scenario_type": "historical_bootstrap_paths",
            "spec": asdict(spec), "audit": audit, "anchors": dict(anchors), "symbols": list(SYMBOLS), "paths": paths,
            "execution_quality": "proxy", "sizing_enabled": False, "admission": "ABSTAIN",
            "recursive_entries": False, "recursive_news": False, "risk_probabilities": None,
            "limitations": ["Block seams break cross-block serial dependence; sampled opening ratios retained explicitly.",
                "OHLC extrema across symbols are not known simultaneous executable bids.",
                "No bid/ask size, liquidity or within-bar ordering evidence; no invented quote interpolation.",
                "Historical unconditional bootstrap, not calibrated current-state risk; no stress probabilities.",
                "No stop/target, fills, future signals, daily resets, VaR/ES or admission simulated here."]}
    return {"path_bank": bank, "path_bank_hash": digest(bank)}


def seal_risk_snapshot(snapshot):
    """Validate input identities without debiting reservations or resetting risk.

    Exposures are dictionaries keyed by stable position/intent IDs. Positions
    supply current liquidation_value from the owner's valuation; pending entries
    supply reserved_cash. This module does not invent a second cost/exit model.
    Additional fields survive and are hash-bound. All cash amounts are absolute.
    """
    required = {"portfolio_version", "as_of", "cash", "reserved_cash", "available_cash", "positions",
                "pending_entry_intents", "pending_exit_intents", "protective_prices", "remaining_holding_time",
                "current_liquidation_equity", "mark_quality_by_symbol", "mark_prices", "risk_day_id",
                "day_start_equity", "day_baseline_status", "historical_high_watermark", "remaining_daily_loss_budget",
                "remaining_position_risk_budget", "loss_streak", "cooldown_until", "cost_policy_id", "execution_policy_id",
                "daily_loss_limit"}
    _require(isinstance(snapshot, dict) and required <= snapshot.keys(), "INCOMPLETE_RISK_SNAPSHOT")
    for key in ("portfolio_version", "cost_policy_id", "execution_policy_id"):
        _require(isinstance(snapshot[key], str) and bool(snapshot[key]), "MISSING_POLICY_OR_VERSION", field=key)
    _epoch(snapshot["as_of"], "as_of")
    _require(snapshot["risk_day_id"] == snapshot["as_of"] // 86400, "RISK_DAY_MISMATCH")
    for key in ("cash", "reserved_cash", "available_cash", "current_liquidation_equity", "historical_high_watermark",
                "remaining_position_risk_budget"):
        _number(snapshot[key], key)
    _require(math.isclose(snapshot["available_cash"], snapshot["cash"] - snapshot["reserved_cash"], abs_tol=1e-8),
             "CASH_RESERVATION_IDENTITY")
    for key in ("positions", "pending_entry_intents", "pending_exit_intents", "protective_prices", "remaining_holding_time"):
        _require(isinstance(snapshot[key], dict), "EXPECTED_ID_KEYED_MAPPING", field=key)
    positions, pending = snapshot["positions"], snapshot["pending_entry_intents"]
    _require(not set(positions) & set(pending), "DUPLICATE_EXPOSURE_ID")
    for identity, exposure in {**positions, **pending}.items():
        _require(exposure["symbol"] in SYMBOLS, "UNSUPPORTED_EXPOSURE_SYMBOL")
        _number(exposure["quantity"], "quantity", positive=True)
        _number(exposure["risk_amount"], "risk_amount")
        _epoch(exposure["expires_at"], "expires_at")
        _require(identity in snapshot["protective_prices"] and identity in snapshot["remaining_holding_time"], "MISSING_PROTECTION_OR_EXPIRY")
        protection = snapshot["protective_prices"][identity]
        _number(protection["stop"], "stop", positive=True)
        _number(protection["target"], "target", positive=True)
        _require(protection["stop"] < protection["target"], "INVALID_PROTECTION_GEOMETRY")
        _require(snapshot["remaining_holding_time"][identity] == max(0, exposure["expires_at"] - snapshot["as_of"]),
                 "REMAINING_HOLDING_TIME_MISMATCH")
    for exit_intent in snapshot["pending_exit_intents"].values():
        _require(exit_intent["position_id"] in positions, "ORPHAN_PENDING_EXIT")
    liquidations = [_number(p["liquidation_value"], "liquidation_value") for p in positions.values()]
    reservations = [_number(p["reserved_cash"], "reserved_cash") for p in pending.values()]
    _require(math.isclose(snapshot["reserved_cash"], math.fsum(reservations), abs_tol=1e-8), "PENDING_RESERVATION_MISMATCH")
    _require(math.isclose(snapshot["current_liquidation_equity"], snapshot["cash"] + math.fsum(liquidations), abs_tol=1e-8),
             "LIQUIDATION_EQUITY_IDENTITY")
    _require(snapshot["historical_high_watermark"] >= snapshot["current_liquidation_equity"], "HIGH_WATERMARK_BELOW_CURRENT")
    _number(snapshot["daily_loss_limit"], "daily_loss_limit", positive=True)
    _require(snapshot["daily_loss_limit"] < 1, "INVALID_DAILY_LIMIT")
    if snapshot["day_baseline_status"] == "ESTABLISHED":
        _number(snapshot["day_start_equity"], "day_start_equity", positive=True)
        _number(snapshot["remaining_daily_loss_budget"], "remaining_daily_loss_budget")
        line = snapshot["day_start_equity"] * (1 - snapshot["daily_loss_limit"])
        _require(math.isclose(snapshot["remaining_daily_loss_budget"], max(0, snapshot["current_liquidation_equity"] - line), abs_tol=1e-8),
                 "DAILY_BUDGET_MUST_NOT_RESET")
    else:
        _require(snapshot["day_baseline_status"] == "DAY_BASELINE_PENDING"
                 and snapshot["day_start_equity"] is None and snapshot["remaining_daily_loss_budget"] is None,
                 "UNKNOWN_DAY_BASELINE_MUST_NOT_INVENT_BUDGET")
    for key in ("loss_streak", "cooldown_until"):
        _epoch(snapshot[key], key)
    _require(set(snapshot["mark_prices"]) == set(SYMBOLS)
             and set(snapshot["mark_quality_by_symbol"]) == set(SYMBOLS), "INCOMPLETE_MARKS")
    for symbol in SYMBOLS:
        _number(snapshot["mark_prices"][symbol], symbol, positive=True)
        _require(bool(snapshot["mark_quality_by_symbol"][symbol]), "MISSING_MARK_QUALITY")
    payload = _copy(snapshot)
    claimed = payload.pop("portfolio_snapshot_hash", None)
    identity = digest(payload)
    _require(claimed is None or claimed == identity, "RISK_SNAPSHOT_HASH_MISMATCH")
    return {"snapshot": payload, "portfolio_snapshot_hash": identity,
            "existing_risk_amount": math.fsum(p["risk_amount"] for p in positions.values()),
            "pending_risk_amount": math.fsum(p["risk_amount"] for p in pending.values())}


def bind_alternatives(paths, snapshot, proposal, multipliers):
    """Return read-only research input bindings, never a selected size or fill.

    m=0 excludes only the new proposal; current positions/pending/exits remain.
    All alternatives reference the same path-bank hash; quantities do not seed RNG.
    """
    bank = paths["path_bank"]
    _require(digest(bank) == paths["path_bank_hash"], "PATH_BANK_HASH_MISMATCH")
    sealed = seal_risk_snapshot(snapshot)
    _require(snapshot["as_of"] == bank["spec"]["as_of"], "SNAPSHOT_PATH_TIME_MISMATCH")
    _require(snapshot["mark_prices"] == bank["anchors"], "SNAPSHOT_ANCHOR_MISMATCH")
    _require(max(snapshot["remaining_holding_time"].values(), default=0) <= bank["spec"]["horizon_bars"] * STEP,
             "HORIZON_DOES_NOT_COVER_EXISTING_AND_PENDING")
    _require(isinstance(multipliers, (list, tuple)) and bool(multipliers), "EXPLICIT_ALTERNATIVES_REQUIRED")
    _require(proposal["symbol"] in SYMBOLS, "UNSUPPORTED_PROPOSAL")
    for key in ("quantity", "risk_amount", "reserved_cash", "stop", "target"):
        _number(proposal[key], key, positive=True)
    _epoch(proposal["expires_at"], "proposal.expires_at")
    _require(proposal["stop"] < proposal["target"], "INVALID_PROPOSAL_PROTECTION")
    _require(snapshot["as_of"] < proposal["expires_at"] <= snapshot["as_of"] + bank["spec"]["horizon_bars"] * STEP,
             "HORIZON_DOES_NOT_COVER_PROPOSAL")
    _require(len(set(multipliers)) == len(multipliers), "DUPLICATE_ALTERNATIVES")
    alternatives = []
    for multiplier in multipliers:
        _number(multiplier, "multiplier")
        _require(multiplier <= 1, "NO_UPSIZING")
        new = _copy(proposal) if multiplier else None
        if new is not None:
            for key in ("quantity", "risk_amount", "reserved_cash"):
                new[key] *= multiplier
        alternative = {"multiplier": multiplier, "proposed_entry": new,
                       "portfolio_snapshot_hash": sealed["portfolio_snapshot_hash"],
                       "path_bank_hash": paths["path_bank_hash"], "admission": "ABSTAIN", "selected": False}
        alternative["binding_hash"] = digest(alternative)
        alternatives.append(alternative)
    return {"version": VERSION, "risk_snapshot": sealed, "alternatives": alternatives,
            "scope": "DEV_ONLY", "sizing_enabled": False, "execution_enabled": False,
            "remaining_daily_loss_budget": snapshot["remaining_daily_loss_budget"],
            "existing_and_pending_preserved": True, "future_risk_evaluation": "NOT_IMPLEMENTED_T20_INPUTS_ONLY"}
