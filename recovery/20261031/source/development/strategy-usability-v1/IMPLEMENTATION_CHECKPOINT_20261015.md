# Strategy Usability Implementation Checkpoint

Date: 2026-10-15. Status: DEVELOPMENT IMPLEMENTED, NOT RELEASED.

## Runtime Boundary

The accepted `local-candidate-4ae28624d9e0d41b` observation runtime was not edited or restarted. At 15:06:59 UTC its launcher session was `a640eb5c-64e4-46f2-b5da-7809be40abdc`, launcher PID 17656, backend listener PID 1300, and gateway listener PID 22296. Both memory-live endpoints returned HTTP 200. This establishes process/HTTP continuity, not trading eligibility or natural-signal acceptance.

Development is a small overlay under `source/development/strategy-usability-v1`, not a second project or production instance. It imports unchanged code from `source/development/workspace`. No production DB was initialized, migrated, copied, or written by this task. No SDK connection was opened. Test backends/Gateways used isolated ports and synthetic transport, and were cleaned up.

Exact S0 normalized policy hash: `9fcbe3bf87f5509bfda4ef31e4cd7956dd2be2bfcc25a9a2472123a61111b261`. Its source and JSON policy hashes still match the initial baseline. The original live runtime, summary, and Signals source files also match the initial hashes. The running 8020 page is still the accepted old build, NOT this development build.

## Implemented Code

- `kquant/options_intraday_comparison.py`: independent `STRAT-INTRADAY-MOMENTUM-S1-RESEARCH-V1`, inheriting S0 parameters except previous-close direction. One admitted snapshot feeds both strategies/directions. S0 itself is called unchanged. Unknown S0 reference remains INCOMPLETE, never a rejection.
- S1 independently checks same-session identity/currency, opening price, admitted closed minutes, source conflicts, and native price basis. It does not require the cross-day PriceReference to pass first. Missing native basis still blocks the affected S1 input. No arbitrary price-basis inference was added for undocumented push data.
- S0/S1 results persist in the same existing research DB and CAS transaction. Child evidence is stored once; the parent carries a compact comparison link. Full evidence is resolved by ID. S1 QUALIFIED revisions are explicitly refused before the old claims writer.
- Existing qualification continuations are reused for S1 reference collection. A jointly triggered S0/S1 snapshot uses one collector. S1-only collection never consults old qualified-publication approval, never writes qualified_claims, locks the original reference contract, and preserves original expiry/withdrawal behavior.
- `options_research_diagnostics.py`: range/body bps, explicit unsupported ATR/same-slot diagnostics; bid/ask friction, verified-unit cash amounts, delta-equivalent friction, and explicit-unit local Greek scenarios. Missing fees, units, currency, or stale quotes produce null/reasons, not zero or invented fills. No new threshold or alpha score.
- `options_research_availability.py`: first observed post-commit availability is separately recorded using the existing journal store. It does not overwrite original judgments or guess an earlier time after a crash. This is backend availability, not browser-delivery time.
- `StrategyComparisonCard.tsx`: same-card S0/S1 states and conditions, amplitude, reference code/expiry/strike/DTE/bid/ask, cost limitations, source times, and stock-path label status. Reconnection never renews original deadlines. Independent manual reporting remains explicitly labeled S0; no implicit S1-to-S0 position binding was introduced.
- Live research summaries are bounded to eight rows and 32KiB of observation payload, with total/deferred fields; existing qualified candidates are not silently discarded. Full data remains in history/detail. This addresses the observed research IPC expansion, not by increasing timeout.

## Actual Replay

Latest replay: `evidence/replay-2026-10-15-145659/`.

This is a read-only, retrospective, as-of DEVELOPMENT replay of the earliest persisted evaluation for each symbol/checkpoint. It is not an exhaustive replay of every later revision in the original 300 seconds. The manifest explicitly records that limitation. The same exposed trading day was still in progress; it is not an unseen holdout or a completed-day statistical validation.

| Denominator | Result |
|---|---:|
| Registered symbols | 111 |
| Checkpoints per symbol | 5 |
| Registered direction positions | 1110 |
| Earliest recorded symbol/checkpoint positions | 500 |
| Unresolved identity direction positions | 110 |
| Incomplete S1 input direction positions | 998 |
| S1 intraday-only complete direction positions | 2 |
| Paired complete S0/S1 positions | 0 |
| Replay execution errors | 0 |

Incomplete S1 inputs: 296 source-conflict positions, 654 native-price-basis-unverified positions, and 48 missing-contiguous-minute positions. These are direction/checkpoint positions, not independent trades.

BTDR at 09:35 ET: S0 INCOMPLETE, S1 CALL NO_TRIGGER, S1 PUT NUMERIC_PASS. The PUT is a retrospective technical event, not a delivered live signal or recommendation. It has no verified corresponding historical option quote. The original records lack exact post-commit availability, so the primary 60-second reaction / 60-minute path label is `READY_COMMIT_TIME_UNAVAILABLE`. No stock or option PnL is claimed. One first S1 technical event is counted; repeated directions, scopes and revisions are not independent samples.

Earlier replay attempts are retained: one bounded-query attempt had 18 diagnostic failures and one test-store initialization error. They are not used as successful results. Earlier labels based on computation time are superseded by the explicit missing-availability result.

## Verification

- 57 focused tests: unchanged full S0 payloads, low-gap CALL/high-gap PUT, independent S1 input, invalid minutes, original deadlines, cost arithmetic/nulls, stock-path labels, real store/qualification continuations, one collector for a joint trigger, no S1 claims, post-commit observation idempotency, bounded current projection.
- 44 additional existing regressions: P7 input/generation and P12 bootstrap/reference checks. One upstream deprecation warning remains; no skipped test is represented as passed.
- Both unified and stock builds compiled. Existing bundle-size warnings above 500KiB remain.
- `evidence/browser-20261015-145207`: actual API/Gateway + compiled page + browser login, real BTDR replay, 1440/2560, Chinese/English, dark/light, disconnect/reconnect; no page errors or layout overflow. This build predates only the explicit S0 manual-button label change.
- `evidence/browser-20261015-150123`: final compiled page, synthetic reference obtained through the actual persistent qualification lane; eight desktop combinations show `TEST261006C105000.US`, expiry, strike, DTE, bid/ask and unknown amount/fees. It is visibly TEST_ONLY, historical and unqualified. No current-price or real-market claim.
- Browser bridge uses isolated snapshots and TCP server threads; it is NOT the independent-process Supervisor hour. Deliberately unmounted legacy routes return tagged TEST_ONLY 503 and remain separately logged.

## Assembly Failures And Limits

Independent-process assembly attempts are under `source/evidence/new-machine-20261008/strategy-usability-assembly-short-20261015-v*/`. They use actual Supervisor.start, Worker initialization/run, role maps, queue, store, API, Gateway and compiled pages, with explicit synthetic market/source fixtures. Compressed one-second checkpoint scheduling is a short stress exercise, not original five-minute market cadence or a one-hour pass.

v1 completed the short exercise but failed: three unexplained HTTP failures, including a current-query IPC deadline with approximately 1.69MB response. v2/v3/v4 encountered `CHECKPOINT_INTERNAL_WRITER_BUSY` at `_price_fact_quotes -> _journal_guard`, followed by controller EOF and failed HTTP observations. Those errors were NOT exempted merely because fault windows overlapped.

Mitigations now in code: compact comparison transport, one stored S1 evidence copy, bounded observation cards, post-commit recording through existing writer coordination, and an eight-symbol lane batch to account for the additional S1 rows without increasing lock timeout. Lock wait/hold diagnostics were added. These changes do NOT establish that write contention is solved.

v4 recovered 100 pending calculation jobs with original deadlines intact, but later failed. All test child processes were reaped. Its S1 records were INCOMPLETE because equal-time synthetic source versions selected the original push evidence; this is not a positive S1 assembly proof.

v5 completed 60.328 seconds with a later TEST_ONLY NoAdjust snapshot and without the optional CPU profiler. It covered all five compressed checkpoints, each with 200 evaluated directions and 22 identity exclusions. There were no unexplained HTTP failures; the three 503 responses on each affected endpoint were attributed to the matching intentional process-crash contract, not a blanket time-window exemption. All 100 pending jobs were recovered with original deadlines preserved, and all test children were cleaned up. The source fingerprint stayed unchanged during this run.

The actual isolated research DB contains S1 revisions INCOMPLETE=152, NO_TRIGGER=493 and NUMERIC_PASS=493, with 493 post-commit availability records and zero S1 qualified claims. These are synthetic revision counts, NOT independent opportunities or real signals. This supplies the previously missing actual Supervisor/Worker positive chain. Five checkpoint enqueue-to-commit P95 values were 3.235, 4.406, 4.969, 6.641 and 5.797 seconds. They fail the 2-second target and are not market-receipt-to-calculation latency. Changing the profiler and fixture means this successful short run does not prove the earlier writer contention is fixed. Full-hour, original-cadence and performance acceptance remain false in the report.

Full 60-minute matching assembly, natural signals, market latency and exact new O-LAUNCH acceptance are NOT completed. Source gaps are not used as a reason to block safe engineering acceptance, but the observed writer/transport failures are genuine engineering gates.

## Exact Remaining Work

1. Finish bounded diagnosis of the shared writer hold/queue contention using the captured phase and wait/hold evidence. Preserve requests for retry without dropping the remaining source batch. Do not expand timeouts or remove validation.
2. Build on the v5 synthetic positive Supervisor/Worker chain, pending recovery and no-old-claims evidence; finish release integration and run the matching 3600-second / 300-second-cadence hour. Preserve separate safety and performance verdicts.
3. Extend the replay to original-window revisions and record complete-day cohorts before any unseen-day comparison. Existing missing commit times remain missing; new post-commit records do not backfill them.
4. Bind the final overlay and compiled build into the original release mechanism, prepare one exact research-only O-LAUNCH delta, and obtain acceptance before replacing the live observation payload. No approval is requested for this unfinished checkpoint.
5. After accepted deployment, record actual new-window S1 availability and browser delivery, optional reference contracts and later labels. No old opportunity is replayed as an immediate alert.

This document is an implementation checkpoint with code, failures and artifacts, not a new architecture plan or completion certificate.
