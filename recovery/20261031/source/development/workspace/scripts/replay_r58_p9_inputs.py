"""Actual archived input replay; isolated writes, never historical instant signals."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import sys

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    from kquant import options_price_facts as facts
    from kquant import options_price_reference as prices
    from kquant import options_opening_trend_reference as sources
    from kquant import options_minute_decisions as canonical
    from kquant import options_one_minute as common
    from kquant import options_opening_momentum as model
    from kquant import options_opening_momentum_journal as journal
    from kquant import options_opening_trend_store as store
    from kquant.options_minute_admission import partition
    from kquant.market_clock import session_bounds_utc
    archived = json.loads(args.inputs.read_text())
    reviews = sources.load_reviews()
    path = args.out / "REPLAY_ONLY.sqlite3"
    store.initialize(path)
    journal.initialize(path)
    report = {"mode": "ARCHIVED_AS_OF_REPLAY_NOT_INSTANT_SIGNAL", "production_writes": 0,
        "owner_approvals_created": 0, "sources_modified": 0, "price_bindings": {}}
    for symbol in ("FCX", "NVTS"):
        reference = archived[symbol]
        native = reference.get("raw_quote", {})
        now = common.timestamp(reference["known_at"])
        binding = facts.persist_binding(path, facts.bind(native, symbol=symbol, session="2026-10-05",
            now=now, reviews=reviews))
        raw = {**deepcopy(native), "session_price_binding": binding}
        result = prices.build(raw, symbol=symbol, session="2026-10-05", now=now, reviews=reviews)
        report["price_bindings"][symbol] = {"observed_previous_close": binding["observed_provider_previous_close"],
            "verified_previous_close": result["previous_close"], "binding_status": binding["status"],
            "fact_hash": binding["fact_hash"], "reference_hash": result["reference_hash"],
            "blockers": result["reference_blockers"], "source_references": {
                k: (binding.get(k) or {}).get("source_sha256") for k in ("interface_fact", "price_basis_method", "action_coverage")}}
        bars = archived.get(symbol + "_raw_versions", [])
        if bars:
            envelope = archived[symbol + "_evaluation_envelope"]
            original_now = common.timestamp(envelope["evaluated_at"])
            opening, closing = session_bounds_utc(date(2026, 10, 5))
            rows = model.evaluate_pair(symbol=symbol, bars=bars, history={}, reference=result,
                opening=opening, closing=closing, now=original_now, checkpoint=common.timestamp(envelope["calculation_bar_end"]),
                scope_hash=envelope["scope_hash"])
            report["price_bindings"][symbol]["original_evaluation_envelope"] = envelope
            report["price_bindings"][symbol]["actual_price_components"] = [
                {"right": row["right"], "state": row["state"], "reasons": row["reasons"],
                 "factor_evidence": row.get("factor_evidence"), "bar_evidence": row.get("bar_evidence")} for row in rows]
    original = archived["ASTX_evaluation"]
    bars = archived["ASTX_raw_versions"]
    now = common.timestamp(original["evaluated_at"])
    end = common.timestamp(original["calculation_bar_end"])
    opening, closing = session_bounds_utc(date(2026, 10, 5))
    groups = {}
    for row in bars:
        if common.timestamp(row["open_at"]) < end:
            groups.setdefault(row["open_at"], []).append(row)
    admission = {}
    for start, versions in groups.items():
        own = partition(versions, symbol="ASTX", opening=common.timestamp(start),
            until=common.timestamp(start) + timedelta(minutes=1), now=now)
        admission[start] = {"captured_ids": [common.digest(v) for v in versions],
            "as_of_raw_ids": list(own["raw"]), "eligible_ids": list(own["eligible"]), "rejected": own["rejected"]}
    proof = reviews.get("canonical_resolution_method") or {}
    decisions = canonical.resolve(path, bars, symbol="ASTX", session="2026-10-05", now=now, proof=proof)
    reference = original.get("reference_evidence") or original.get("factor_evidence", {}).get("reference", {})
    job = ("ASTX", date(2026, 10, 5), bars, original["scope_hash"], reference)
    key = ("opening_momentum", "2026-10-05", "ASTX", int((end - opening).total_seconds() // 300))
    fingerprint = journal.input_fingerprint(job, decisions)
    admitted = journal.ready(path, key, job, now, fingerprint=fingerprint)
    lease = journal.begin(path, key, job, now, fingerprint=fingerprint)
    rows = model.evaluate_pair(symbol="ASTX", bars=bars, history={}, reference=reference,
        opening=opening, closing=closing, now=now, checkpoint=end, scope_hash=original["scope_hash"], source_decisions=decisions)
    for row in rows:
        row["computed_at"] = now.isoformat()
        row["runtime_inputs"] = {"input_generation": lease.generation, "input_fingerprint": lease.fingerprint}
    committed = journal.finish(path, lease, rows=rows)
    report["ASTX"] = {"original_evaluation_id": original["evaluation_id"], "original_as_of": now.isoformat(),
        "checkpoint": end.isoformat(), "original_deadline": (end + timedelta(seconds=300)).isoformat(),
        "raw_versions": len(bars), "minute_admission": admission, "selected_decisions": decisions,
        "method_status": proof.get("status", "NOT_CONFIGURED"), "journal_admitted": admitted,
        "journal_generation": lease.generation, "cas_committed": committed,
        "replayed_states": dict(Counter(row["state"] for row in rows)),
        "reasons": [row["reasons"] for row in rows], "historical_instant_signals_created": 0}
    (args.out / "actual_inputs_replay.json").write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({"price_bindings": report["price_bindings"], "ASTX": {k: v for k, v in report["ASTX"].items()
        if k not in {"minute_admission", "selected_decisions"}}}, ensure_ascii=True))


if __name__ == "__main__":
    main()
