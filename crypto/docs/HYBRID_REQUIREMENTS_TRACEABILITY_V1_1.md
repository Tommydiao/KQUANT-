# Hybrid V1.1 Requirement Evidence Map

Final M0/M1 report. Full Crypto suite:539 passed in64.92s, exit0. Log:
`outputs/hybrid_regime_v1/full_regression_final_20260905.txt`. There are48 new
Hybrid test cases and491 pre-existing cases. Passing fixtures are not a deployed
runtime, new market evidence or a performance certificate.

| ID | Actual verification | Scope / remaining |
| --- | --- | --- |
| P0-01 | test_protection_before_ready_entry_and_never_waits_model_future; test_btc_protection_needs_no_sol_batch_or_finished_model | Logical writer priority/pending-no-quote plus unchanged protection component. Real worker scheduling/latency remains M5 |
| P0-02 | test_delayed_decision_never_fills_past_open; test_past_open_and_expired_fill_never_mutate_ledger | Strict timeline and synthetic cash ledger. Real delayed OHLC/BBO adapter not wired |
| P0-03 | test_news_reevaluation_one_intent_and_repeat_no_cash_change; test_arms_have_independent_intents | SQL uniqueness and immutable content identities; actual opportunity reset policy M2 |
| P0-04 | test_stale_portfolio_rejects_without_reservation; test_partial_commit_fault_rolls_back_everything | Portfolio hash/version CAS and transaction rollback; latest live model registry binding M5 |
| P0-05 | test_daily_budget_not_reset_from_current_equity; existing test_last_old_day_close_breach_survives_rollover_and_uses_actual_open_baseline | Risk reference and baseline rollover. Full MC midnight simulation M4 |
| P0-06 | numerical tests: zero/all counts,4.9% point estimate, exact coverage, multiplicity and general-alpha inversion | Exact numerical helper only; no actual model paths, block/bootstrap sensitivity or admitted thresholds |
| P0-07 | synthetic posterior summary separates conditional means/new outcomes with contradictory fixture | No probability UI or trained model; typed artifact registry M3 |
| P0-08 | test_censored_labels_cannot_be_zero_filled; test_termination_is_not_a_mature_exit; test_future_counterfactual_policy_and_synthetic_are_not_merged | Label schema/selector only; no historical labels generated |
| P0-09 | Original backtest/validation denominator and ordering documented in baseline audit | B-10R transfer conflict blocks complete PASS; not guessed |
| P0-10 | m0_golden_20260905_04/golden_trace_report.json: A/B events,trades,equity exact match | Current baseline reproduced; OFF/SHADOW Hybrid plugin equivalence still unimplemented |
| P0-11 | test_proxy_cannot_claim_real_exchange_fill; unchanged candidate quote/ohlcv tests | Execution-quality field contract; no new real fills |
| P0-12 | test_foreign_database_refused; test_restart_same_intent_and_consumed_fill_are_idempotent; existing test_candidate_import_and_trade_do_not_touch_original_execution_or_stores | Test-only DB separation; no Hybrid persistent writer created. Original process/lease checks read-only |
| P0-13 | test_writer_failure_halts_without_replaying_or_consuming_next_event | Synthetic failure stops queue; real process emergency protection/recovery remains M5 |

Historical failed test/audit attempts are recorded in daily log; successful final
tests do not remove those artifacts. No frontend changed in this milestone, so
no new UI/browser/build result is claimed. API/execution integrations remain off.
