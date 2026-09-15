# KQUANT V1.2 固定恢复指令

## User progress/profitability report and saved model recovery: 2026-09-12

Delivered `docs/HYBRID_PROGRESS_AND_STRATEGY_REVIEW_20260912.md` using fresh
portfolio reports and net win/payoff calculations, current process checks and
immutable online snapshot `rx07_progress_report_snapshot_20260912_01`.
All five historical policy variants remain net negative; no OOS/profit claim.

New standalone saved model capsule02 (capsule01 failed Windows file-handle
cleanup; preserved) restored into independent directory and actually replayed
306forecasts exactly, max difference0,450TRAIN rows,1divergence retained.
`rx01_saved_model_restore_check_20260912_02/report.json` exit0. ArchiveSHA
`14bb5074c2d8d31f4330d36aea3d27d5a9b04d6dddf1b205f0e404b7a91904b2`.
Verifier uses saved posterior, not fitting; numerical gateFAIL, DEV_ONLY. This
does not bundle full training/MC environment or prove profitable predictions.
Latest full1239test checkpoint predates these patches; don't combine with later
targeted verification and call final whole-source regression complete.

## Availability and real renewal rechecks: 2026-09-12

Prospective audit02 rehashes context/snapshot for every admitted record and
recomputes closed/available synchronized history and matched block counts.
Exit0,70complete/74rejected/6unavailable unchanged. Unavailable six are TWO
economic signals across3policies:ETH1768342200 has3 UP_TREND blocks and
SOL1772031000 has0, each2017historical5m batches, minimum30 frozen. Not missing
all history, not6independent samples. Other70 histories eligible.15tests pass.

RX07 auditor now reconstructs every clock segment from its five raw time probes
and verifies renewal overlap at probe completion (not exact activation timestamp).
`rx07_dual_v2_renewal_audit_20260912_01` exit0:933raw/replayed records,924forming,
7strict-qualified closed,2order-uncertain rejects;2clock segments/10probes and
1renewal revalidated. One complete three-coin5m batch and one1h batch; the next
5m batch is incomplete. No continuity PASS. Prefix hash
`275d8b961d74c8ddff8d393300c732478246aab381c20bb856cf835bbdd7581d`.
This proves raw reception continues after eligibility rejects; it does not make
rejected closed bars usable or supply bid/ask. No receiver/dependency edits.

## RX06 numeric audit and RX07 first native dual close: 2026-09-12

New `scripts/audit_rx06_prospective_pair_dev.py` refuses missing terminal reports,
checks source/runner/path hashes, frozen population identities/order and original
rejection reasons, complete path counts, paired arithmetic, fill/open counts and
stored quantiles. It does NOT resimulate protection, independently regenerate
paths or recompute unavailable histories; those limits are explicit.
Actual engineering02 audit `rx06_prospective_engineering_audit_20260912_01` exit0:
70completed,74original rejection,6unavailable,140paired paths. Tests15passed0.38s.
Do not use engineering2paths per record as meaningful probability evidence.
Run same audit on full output ONLY after terminal report exists and worker is
terminal. Full worker28624 remains alive, latestrecord6 paths3400.

RX07 v2 worker30524 verified alive. Independent immutable prefix audit
`rx07_dual_v2_prefix_audit_20260912_01` exit0:408raw/408matching normalizations,
402forming and6strict-qualified native closed bars:BTC/ETH/SOL each5m and1h.
One synchronized batch per interval; no unresolved raw, no tail, no failure in
prefix. Hash`d2ab366e7eb34a3c926cad50f463f150118639516cd739f9eb679c99f708ffb7`.
These are actual network closed bars, not synthetic fixtures. No warmup,2H
continuity, quote labels, calibrated forecasts or execution permission claimed.

## RX07 v2 receive-only preregistration: 2026-09-12

New `scripts/observe_rx07_dual_v2_dev.py` retains v1 unmodified so old manifests
remain replayable. Sole policy change: a rejected normalized message does not
terminate RAW collection. Invalid messages stay rejected; later bars after a
missing required boundary remain ineligible, with no implicit backfill/rewarm.
Transport/clock expiry/renewal discontinuity still terminate the segment.
Completion means RAW_RECEIPT_SEGMENT_COMPLETE only. strict_data_pass, signal_ready
and execution_ready are explicitly false; no model/quote labels/orders.
No freshness, timestamp, strategy, cost or execution policy change.

Before launch: focused21tests passed1.56s exit0, including a synthetic future
source timestamp rejection followed by continued raw forming-message collection.
Synthetic test is NOT real closed-boundary or clock-renewal evidence.
Launched new run `rx07_dual_v2_2h_20260912_01`,7200seconds, local20:53:48,
launcher40472 after verifying no existing RX07 Python receiver. Logs at
`rx07_dual_v2_2h_job_20260912_01`. Preserve failed v1.
Source hashes in new manifest freeze this scope before incoming outcomes.

## RX07 first boundary failure and Crypto regression: 2026-09-12

`rx07_dual_2h_20260912_01` is TERMINAL FAILED, not a running/complete2H run.
Actual report: total186.935s including setup/shutdown;460forming and1closed
rejection,461raw messages. BTC5m nativeE1789217700.036 seconds falls INSIDE
receiver bounds[1789217700.0261395,1789217700.2378628], about9.86ms above lower.
Thus strict receipt-order proof is uncertain, NOT proof of future exchange time.
NativeE and original local receipt1789217368.5579233 remain unchanged. Do not
relax freshness or rewrite this rejected record. No closed acceptance or fills.
Terminal independent replay artifact: `rx07_dual_terminal_audit_20260912_01`.

Next RX07 engineering: distinguish persistent RAW reception from strict eligible
normalization, without allowing rejected bars into signal warmup or execution.
Current implementation terminates whole receive segment on any rejected closed
message; that limitation prevents collecting further rejection/renewal evidence.
Any revised receiver must preregister separate collection and eligibility status,
retain gaps, and use a NEW run, never append or stitch this failed segment.
OS clock approval remains outstanding; it is not needed to audit recorded data.

Actual full Crypto regression on this source checkpoint:
`work/hybrid_runtime_restore_env_20260906/Scripts/python.exe -m pytest -q`
1239passed,10skipped,27subtests,118.90s,exit0. No stock/frontend rerun claimed.

## RX07 independent prefix replay: 2026-09-12

Added `scripts/audit_rx07_receipts_dev.py`. It checks receiver source hashes,
captures only initial byte length without locking/modifying the writer, retains
any incomplete tail, and replays complete raw messages using serialized clocks.
It checks raw/normalization pairing, contiguous receipt sequence, event hashes,
closed duplicates/conflicts and synchronized symbol counts. Prefix success is
NOT continuity or signal acceptance. Pending final raw records are explicit.

Actual `--source outputs/hybrid_delivery/rx07_dual_2h_20260912_01 --output outputs/hybrid_delivery/rx07_dual_prefix_audit_20260912_01` exit0:
370 raw records/370 identical normalization results, all forming, no terminal
failure in captured prefix, no incomplete tail, no unpaired raw. Captured hash
`bfeafee500275b544a2bfd38068d1a993ba5a94d3411adf5c966ba76cb1a2fcd`.
Focused audit/observer/adapter tests19passed2.47s. Full Crypto regression started
separately; do not claim it passed until terminal exit is recorded.

## RX07 independent receiver launched: 2026-09-12 local 20:46:30

`scripts/observe_rx07_dual_dev.py` adds durable raw receipt capture, native 5m/1h
normalization, duplicate/conflict/gap checks, three-symbol batch counting and
asynchronous 240-second clock renewals under unchanged 600-second validity.
Disjoint/expired clock mappings, invalid closed receipts or connection failures
terminate this observation segment; no reconnect, historical bootstrap, model
loading, order creation or original writer ownership. Renewal continuity is
receiver-interval overlap, not proof that OS time was fixed.

Actual smoke `rx07_dual_smoke_20260912_01`: exit0, 38 real forming messages,
zero closed bars/labels. Old smoke field `connected_seconds=22.273` included
shutdown, so do NOT treat it as receive coverage; requested window15s, total25.560s.
New runner records explicit receive-window end separately from shutdown. Focused
tests after correction:31 passed1.54s exit0. Not a full regression result.

Launched new isolated run, launcherPID36440, with verified absence of another
matching receiver before launch:
`work/hybrid_runtime_restore_env_20260906/Scripts/python.exe scripts/observe_rx07_dual_dev.py --seconds 7200 --output outputs/hybrid_delivery/rx07_dual_2h_20260912_01`
Logs: `outputs/hybrid_delivery/rx07_dual_2h_job_20260912_01/`.
State: RUNNING_AT_LAUNCH, not 2H acceptance. Inspect actual PID and raw receipts;
terminal report determines success. A run-local `STOP` file requests a failed/
incomplete terminal segment without affecting any other service. Do not resume
or append an old output, and do not edit runner dependencies while it runs.
OS clock correction remains unapproved; signal_ready and execution_ready remain
false even when receipt segment finishes. Next assess real closed boundaries,
renewals and continuity, then separately plan bootstrap/signal readiness.

## RX07 dual receipt contract checkpoint: 2026-09-12

Added isolated `kquant_crypto/hybrid_dual_receipt.py` and focused tests. Native
UTC 5m/1h boundaries, E/t/T milliseconds, closed flags, source/receipt ordering,
existing 30-second freshness, OHLCV and conservative availability are checked.
Forming bars are a distinct rejection, not a network failure. Kline receipts
remain explicitly NOT bid/ask or execution evidence. Clock renewal requires
overlapping valid intervals; expiry or local jumps cannot bridge continuity.
No old adapter, clock policy, collector environment, A/B or admission changed.
Official schema checked at
https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams
(UTC kline E/t/T/x, 5m and 1h). No source event time is manufactured.

Actual command using `work/hybrid_runtime_restore_env_20260906/Scripts/python.exe`:
`-m pytest -q tests/test_hybrid_dual_receipt.py tests/test_hybrid_hourly_receipt.py tests/test_multifactor_hourly_observer.py`
Result: 28 passed in 1.04s, exit0. `git diff --check` exit0 (does not inspect
untracked files). This proves adapter engineering only, not online continuity.
Next: independent receive-only service with asynchronous clock renewals and
durable raw receipts, then real 2H boundary verification. Not yet launched.
RX06 worker28624/launcher5112 verified live; stdout shows record0 completed5000
paired paths and record2 progressing. Full result is NOT yet complete. Preserve
its running code and output. OS clock correction still needs user approval.

## RX06 full paired risk run launched after recovery verification: 2026-09-12

New engineering02 completed70records x2paths,74original rejections,6unavailable.
`scripts/verify_rx06_pair_recovery_dev.py --source outputs/hybrid_delivery/rx06_prospective_pair_engineering_20260912_02 --output outputs/hybrid_delivery/rx06_pair_recovery_verify_20260912_01`
Actual exit0: a CONSTRUCTED partial copy of actual outputs reused139paths and
recomputed1;70JSONL files and final records exactly match complete source, originals
unchanged. This is a controlled recovery test, not a claimed real crash.19focused
recovery/paired-kernel tests passed0.83s, including corruption, mismatch, truncation,
duplicate rows, target-fill isolation and retained byte identity.

FULL launch command, Crypto cwd:
`work/hybrid_runtime_restore_env_20260906/Scripts/python.exe scripts/run_rx06_prospective_pair_dev.py --phase full --output outputs/hybrid_delivery/rx06_prospective_pair_full_20260912_01`
Started hidden local process20:32:31,launcher5112/worker28624 verified via actual
Win32_Process command lines. stdout reached record0/path200,stderr empty then.
Logs:`outputs/hybrid_delivery/rx06_prospective_full_job_20260912_01`.
No duplicate matching process existed at dispatch. Frozen5000paths per eligible
record; current engineering predicts70eligible, but final full status must be read
from actual report. No result or calibrated risk gate assumed before completion.

Do not edit runner,hybrid_prospective_risk,hybrid_mc_recovery,conditioned sampler,
config or frozen core sources while this job runs. Progress flushes every100paths.
If actual handle is missing/terminal, inspect logs and preserve partial files; resume
only in a NEW output directory with `--phase full --resume-from <prior-full-dir>`.
Exact phase/config/code/source and deterministic sampling must match. Never reuse
engineering phase as full evidence. Truncated final JSONL is rejected for explicit
audit, never silently discarded. Observation timeout does not authorize restart.

## RX06 paired pending-risk engineering completed: 2026-09-12

Frozen contract:`config/rx06_prospective_pair_dev_v1.json`, all admitted records,
same seeded paths with target pending versus without only that pending. Original
cash remains unchanged on removal; all other positions/pending retained. No new
signals, orders or alternative risk budget. Full contract5000paths/record, current
engineering2paths/record only; neither mode enables selection or execution.

Actual base-Python command exit0:
`scripts/run_rx06_prospective_pair_dev.py --phase engineering --output outputs/hybrid_delivery/rx06_prospective_pair_engineering_20260912_01`
70 completed records x2paths=140 paired engineering paths;74original rejections;
6unavailable for conditioned history. All records retained, no favorable substitute.
Missing first-hour prefix, future/late prefix, path gap, plan/cash isolation and
actual original VIRTUAL_ENTRY accounting covered by focused tests. After an
additional fail-closed duplicate/removed-target fill assertion:11tests passed0.27s;
that assertion is newer than this engineering output and must be captured in the
next run's code hash. Current full5000 experiment NOT started/completed.

This answers state/clock assembly and protective-engine plumbing only; no pooled
probability, predictive gain or real fill claim from two paths. Valuation remains
48H costed mark, incremental NAV drawdown only, not full-lifecycle realized PnL.
Before long full run, retain per-path progress and validate recoverable prefixes;
do not rerun from zero on observation timeout or weaken missing-history gates.

## RX06 genuine prospective-state freeze completed: 2026-09-12

`scripts/freeze_rx06_prospective_states_dev.py --output outputs/hybrid_delivery/rx06_prospective_states_20260912_01`
Base Python actual exit0. Every frozen50 technical opportunity, no outcome-based
selection, three original policy portfolios.150 indexed opportunity-policy
snapshots; ORIGINAL27pending/23already_exposed;T1 24pending/25already_exposed/
1risk_pause;T2 25pending/24already_exposed/1risk_pause. Rejected plans not inserted.
Each snapshot is after genuine closed-bar decision but before next-bar execution,
restores identically, and full trade/equity hashes match all3original portfolios.
Only sanitized identity/time/plan fields enter context; future original trade IDs
or labels are not used as simulation inputs. Historical close proxy remains
explicit, no quote latency or actual exchange execution claim.

76 admitted policy records: BTC1/ETH30/SOL45;RANGE6/UP_TREND70.69 have no existing
position,7have one;52states have one pending,24have two. These are correlated
policy records, NOT76 independent trades; missing asset/mode coverage remains.
Past2017bars, contemporaneous anchors and state are stored, along with partial
first-hour closed5m prefix. A future simulator must preserve that prefix rather
than claim an incomplete generated hour is a complete confirmation candle.
No paths generated, risk success or strategy permission assigned in this freeze.

Next: bounded paired with-proposal/without-proposal replay using the SAME state
and common paths, retaining all other pending and original protection. Only
originally admitted pending proposals may be compared; rejected cases remain
auditable rejections. Freeze experiment budget/selection before path outcomes,
report missing conditioned history and all still-open horizon exposure.

## RX06 fixed-path risk trace completed: 2026-09-12

`scripts/audit_rx06_risk_trace_dev.py --output outputs/hybrid_delivery/rx06_risk_trace_20260912_02`
Actual base-Python exit0. Path0 at EVERY12eligible start, unchanged sampler,
frozen hashes/seed, original three-policy simulator. Initial plus576post-batch
observations per policy;12x3x577=20772 trace rows. Every saved outcome field
matches the original path0 exactly, and all original path/report hashes remain
unchanged. Instrumentation class restored in finally; no original source edits.

All7 flagged start-policy groups inherit an initial booked-risk/current-NAV
threshold exceedance. Initial excess virtual cash ranges0.0825732091 to
0.1609807613; fixed-path maximum excess up to0.2040516300. Flagged durations
are4,12,32or51 post-batch observations depending on state/policy. These are
not realized loss, newly submitted orders or a proof of safety. No changed
risk definition or tolerance; no claim about all60000 paths' first-breach times.
Full risk trajectories are separately stored for independent inspection.

First attempt01 stopped before traces because instrumentation used serialized
state key rather than object attribute; fixed to actual exit_candidate attribute.
Failed directory preserved; successful02 uses a new directory. This was an audit
adapter error, not a modified strategy or erased simulation failure.

Next uncovered RX06 requirement is prospective added-position risk. Existing
holdings/pending simulations do not stand in for it. A future diagnostic must
freeze genuine opportunity-time portfolio/plan states and use original risk
admission; no fabricated backdated opportunity or forced acceptance is allowed.

## RX06 multi-start recovery completed and independently audited: 2026-09-12

Recovery launcher31924/worker38376 ended; report.json exists. Actual final auditor:
`scripts/audit_rx06_completed_mc_dev.py --run outputs/hybrid_delivery/rx06_multistart_recovered_20260912_01 --output outputs/hybrid_delivery/rx06_final_audit_20260912_03`
Base Python exit0.12 eligible starts x5000 common three-policy paths=60000 joint
paths;2 frozen starts unavailable for insufficient conditioned historical blocks.
Start order, snapshot/path hashes, complete path IDs, unavailable counts and numeric
summaries audited. Eligible starts form8 conservative dependency components, NOT
60000 independent market samples or8 proven-independent samples. No pooled profit
probability, OOS claim, policy selection,10R conversion or runtime admission.

Budget semantics clarified in final audit03 (01/02 retained): sum of booked
estimated entry risk divided by current costed NAV, checked after each batch.
Not actual loss, current-to-stop remaining risk or order-admission failure.
Nonzero path flags occur at1764774000(all3policies),1764777600(T1),
1772373600(all3policies); all these groups already exceed0.5% at frozen start.
Counts per5000 respectively4992/4992/4908,4985,4977/4978/4978. Saved booleans
cannot isolate first post-start breach, so do not claim newly caused breaches or
risk success. Future first-breach/remaining-risk audit needs explicit semantics;
do not erase flags, expand tolerance or change original protection/budget.
At1754337600 T1 has3104/5000 open at48H, T2 has2702/5000; these are horizon
marks and remaining exposure, not realized successful strategy exits.

Engineering path/recovery audit PASS; conditional data12eligible/2unavailable;
model risk remains uncalibrated; strategy performance remains unproven/negative
in exposed historical evidence. Next RX06 work is bounded risk-definition and
prospective-position coverage, not additional draws to seek a favorable result.

## RX02 complete cash-difference bridge: 2026-09-12

`scripts/audit_rx02_fixed_fill_cost_dev.py --output outputs/hybrid_delivery/rx02_fixed_fill_cost_20260912_02 --original-stress outputs/hybrid_delivery/rx02_original_stress_20260912_01/ORIGINAL_2/trades.jsonl`
Actual base-environment execution exit0, prior reports untouched.
All ORIGINAL27/T1 24/T2 25 opportunities match within each policy's BASE/stress
pair. Entry/exit times, market references and exit reasons all unchanged; no
unmatched trades. Stress quantities are87.4203-91.2613%,87.3959-91.3539%,
87.4637-91.4242% of their own BASE sizes, respectively.
At the same stressed per-unit net outcome, quantity changes explain cash deltas
20.8532357515 /16.0349429561 /26.5450805785 versus fixed-fill repricing.
Residuals below1e-14. This identifies an algebraic exposure effect, not improved
entry prediction or a causal policy advantage. BASE R denominator stays fixed in
fixed-fill sensitivity; full portfolio sizing is separately recomputed by the
original risk engine. All source hashes rechecked unchanged at audit completion.

## RX02 missing ORIGINAL full stress replay completed: 2026-09-12

Actual command using existing base Python:
`scripts/replay_rx02_original_stress_dev.py --output outputs/hybrid_delivery/rx02_original_stress_20260912_01`
Exit0. Same authorized capsule, original A and ORIGINAL exit, original risk,
predeclared fee/slippage multipliers1/2. BASE27 trade/equity byte hashes match
the old run before stress starts. Full stressed portfolio:27trades,net cash
-167.4889723925114,PF0.37395175644669354. Still fails original target.
Fixed-fill double-cost result remains separately -188.34220814401678,
PF0.37446273878832786; different sizing/cash path explains why the two experiment
units cannot be merged. No claim of independent OOS or improved strategy.

Two preregistration checks first stopped before output creation because the old
runner hash differed. Resolved with verified original/portable BASE byte parity,
unchanged core source hashes, and AST equality of current runner versus the
portable ZIP runner (only blank-line text difference observed). Archive/current
runner hashes and AST parity are saved. Fresh BASE replay parity remains mandatory;
no semantic source mismatch bypass. Original outputs were rehashed unchanged.
Earlier fixed-cost report's MISSING_SOURCE remains historically true and immutable;
this new run provides the missing comparison without editing that report.

## RX04 diagnostic synthesis and eligibility: 2026-09-12

Actual read-only command:
`work/hybrid_runtime_restore_env_20260906/Scripts/python.exe scripts/audit_rx04_preprocessing_dev.py --output outputs/hybrid_delivery/rx04_preprocessing_20260912_01`
Exit0. Frozen population hash/training rows and TRAIN-only mean/std/group/feature
order match; finite values and feature/label availability checks pass. Training:
450rows/150dates,2025-08-02 through2025-12-29 UTC,labels end2025-12-30.
Diagnostic:306rows/102dates,2026-01-01 through2026-04-12,labels end2026-04-13.
Excluded6 PURGED_EMBARGO and3 CENSORED. No refit, no restricted data access.
This is transformation/provenance parity, not independent verification of every
upstream factor or proof that feature selection was unexposed.

Current diagnostic conclusion (sources rx04_geometry_20260909_01,
rx04_saved_forecasts_20260909_01,rx04_inference_timing_20260910_01):
- CODE/INPUT: frozen preprocessing audit PASS; runtime integration not certified.
- NUMERICAL: FAIL, retained chain2/draw162 divergence; stored draw neighborhoods
  and pooled correlations do not establish a root cause or rule out a funnel.
- PREDICTIVE: unqualified EXPOSED_DEV; MSE model-minus-training-baseline interval
  [0.059853,0.941869],Brier difference interval[-0.005143,0.016274].
  Coverage89.54% alone is not calibration: mean90% interval width10.67713
  log-percent, interval score17.22552; each calendar third has worse mean MSE.
- TRADE USE: disabled; target remains gross24H log return, not net trade R.
- LATENCY: import5.579s/load0.743s/first inference0.003317s/warmP95 0.001477s;
  one frozen snapshot, excludes ingestion, predictive interval sampling and MC.
  Training time is not per-signal latency.

Decision: do not automatically spend a numerical-repair run on this weak economic
target merely to remove one divergence. Any later single repair must preregister
its mathematical equivalence, budget and diagnostic purpose; it cannot establish
economic advantage or silently replace this failed artifact. No holding model,
new features, TCN or real-time model consumer authorized by this audit.

Full Crypto regression before the new preprocessing-audit script: actual
`python -m pytest -q`,1206passed,10skipped,27subtests,87.20s,exit0.
Terminal session60443 completed. Not a frontend build or a post-script full run;
new script was executed independently on actual frozen data as described above.

## RX02 fixed-fill cost evidence / RX06 recovery: 2026-09-12

Final MC auditor now independently recomputes P10/P50/P90 net cash change,
maximum historical/incremental NAV drawdown and horizon-open counts from every
path, rejecting mismatches against the runner's summary. Quantiles use a separate
standard-library linear interpolation implementation. Focused auditor/recovery
tests:9 passed0.25s, including deliberately corrupted summaries and nonfinite
values. Full final-run audit is still pending; these tests do not certify pending
market results. Only auditor/helper/tests changed, not the live recovery runner,
path generator, policy or frozen source contracts.

Actual command (Crypto cwd, existing base environment):
`work/hybrid_runtime_restore_env_20260906/Scripts/python.exe scripts/audit_rx02_fixed_fill_cost_dev.py --output outputs/hybrid_delivery/rx02_fixed_fill_cost_20260912_01`
Exit 0. BASE net PnL parity holds on all ORIGINAL27/T1 24/T2 25 trades.
Fixed quantity, timing and BASE cash-risk denominator; fee and slippage doubled.
Cash PF BASE -> stress: ORIGINAL0.574417->0.374463;
T1 0.666913->0.439162; T2 0.368306->0.213676.
Stress net cash: -188.342208 / -141.722427 / -233.828863.
These are exposed development counterfactuals, not new portfolio replays.
Existing full portfolio stress cash is separately -125.687484(T1),
-207.283782(T2); ORIGINAL_2 source is absent and explicitly MISSING_SOURCE,
not silently substituted or rerun. Initial script failed on that missing source;
fixed to report nullable missing comparison, then actual execution succeeded.
Focused cost tests: 2 passed in0.11s. This patch is newer than the Sept10 full
regression checkpoint; do not claim the old full test run covers it.

RX06 current isolated recovery directory:
`outputs/hybrid_delivery/rx06_multistart_recovered_20260912_01`.
Launcher31924 and child38376 were verified alive via actual Win32_Process.
Progress12/14 is not a final report (includes unavailable starts).
Do not start duplicate recovery, edit frozen MC code, or merge partial evidence.
After report.json exists, run `scripts/audit_rx06_completed_mc_dev.py` against
this directory with a NEW audit output directory. Original runs remain intact.
No execution, filtering, sizing, clock or service changes made.

## RX06 final-audit preparation: 2026-09-10

`scripts/audit_rx06_completed_mc_dev.py` prepared; only run after actual
recovery report.json exists. It requires the full frozen start index, validates
snapshot/path hashes and sequential5000records per eligible start, independently
rechecks unavailable-state historical block counts, and recomputes eligible-only
dependency groups. Partial output cannot pass. Per-policy risk/stop/open-horizon
events remain per-start; no pooled market probabilities or10R conversion.
Zero count among5000 paths gives a conditional one-sided95% upper bound
approximately0.000598967, NOT zero real-world risk or market calibration.
7focused event/prefix tests passed0.35s. Auditor has NOT yet run on complete
real output because MC recovery remains live; latest start1772636400 had600paths.

## RX01 source restore and full regression checkpoint: 2026-09-10

`scripts/archive_hybrid_source.py --output outputs/hybrid_delivery/rx01_source_checkpoint_20260910_01`
exit0,877files,source.zip2065464bytes, restored every file and verified hashes.
Archive SHAdefe09ffd8b03376d9f1f0f985c9def51f1450d8a75fdb8a1e48999f12f517ae.
HEADbaac8d1fe3156be39f7b725d0ed9a20e68c2431f plus existing dirty/untracked
source preserved. No commit,push,dependency install,data or model restore claim.
Exclusion rules now cover .env variants except .env.example, database sidecars
and private certificate formats. Signature scan remains bounded, not proof of
absence of every possible secret. Archive is local only, not deployment.

Same-code Crypto full regression exit0:1200passed,10skipped,27subtests,107.50s.
Full captured output:rx01_source_checkpoint_20260910_01/crypto_pytest.log.
Source archive taken before this resume-note update; code under test unchanged.
No frontend changes/build in this checkpoint. MC recovery worker16232 still
live, latest first previously-unrun start4400paths; full MC not complete.

## RX04 measured compute timing: 2026-09-10

`work/hybrid_dev_fit_fast_env/Scripts/python.exe scripts/benchmark_rx04_frozen_inference_dev.py
--output outputs/hybrid_delivery/rx04_inference_timing_20260910_01` exit0.
Actual perf_counter durations:dependency imports5.5789s, provenance verification
.1235s, posterior loading/materialization .74335s, first saved-snapshot inference
.003317s;200warm same-snapshot repetitions p50/p95/p99 .000948/.001477/.001723s.
Original first exposed BTC diagnostic expected log mean/probability reproduced
within1.45e-15. No fitting or forecast changes, training-only standardization
and hashes checked. This excludes network, feature extraction, quantile sampling,
MC and order paths; concurrent MC active. Not production latency or model Gate.
Original3h38 training duration is not per-signal inference time. Numerical and
calibration failures unchanged; source artifact remains DEV_ONLY.

## RX02 capital/time audit: 2026-09-10

`scripts/audit_rx02_exposure_dev.py --output outputs/hybrid_delivery/rx02_exposure_20260910_02`
exit0, authorized255day window excluding warmup. ORIGINAL/T1/T2 any-position
time fractions1.6680%/3.9243%/3.2298%; full-calendar time-weighted COSTED marked
position-value/NAV fractions .1971%/.4738%/.3819%. This is not gross notional,
pending reservations or average exposure conditional on holding. T1 occupies
about2.35x original time; lower absolute loss is not pure exit advantage.
Removing best actually traded asset leaves netPnl -106.5526/-49.0028/-134.8246.
T1/T2 BTC has no trades and must not count as best performer with zeroPnL.
Run01 retained but superseded for this best-asset-selection bug; run02 corrects
it, no original trade/equity outputs touched.3focused tests passed0.14s.
Concentration shares use gross positive NET trade profits, never divide by a
negative total net result. Missing traded groups and valuation gaps explicit.

## RX08 holding label interval audit: 2026-09-10

`scripts/audit_rx08_holding_intervals_dev.py --output outputs/hybrid_delivery/rx08_holding_intervals_20260910_01`
exit0. Rechecked10708identity rows against27cross-policy economic groups and
original hashed M2 DEV boundaries. Max observed group information37.6667h.
Actual group label end and transitive dependency components do not cross these
particular boundaries:12dev_train/5dev_validation/10dev_diagnostic pass INTERVAL
checks only. No actual overlap found; do not manufacture a leakage finding.
Ninefocused interval/target tests passed0.28s including long label crossing,
boundary equality and linked group exclusion. Legacy6h embargo is recorded but
not reused as a sufficient long-holding rule. Embargo/admission remains ungranted;
no source labels/partitions rewritten and no training authorized by this audit.

## RX08 start dependency audit: 2026-09-10

`scripts/audit_rx06_dependencies_dev.py --output outputs/hybrid_delivery/rx06_dependencies_20260910_01`
completed exit0 using frozen snapshot/index hashes only, no new path results.
14registered starts form9conservative dependency components with7pairwise
edges via shared history, history/scenario-horizon overlap or economic exposure.
This includes the2unavailable starts; final eligible-only inference must filter
those transparently and recompute components, not call9 independent samples.
Economic position/pending identities deduplicated across ORIGINAL/T1/T2 and
preserved by policy. Scenario ends are SIMULATED horizons, not actual label
availability, so this is not netR label purge or proof of independent OOS.
3focused tests passed0.15s. Actual worker16232 remains the recovery process;
no duplicate launched, no runtime code used by that worker modified.

## RX06 recovery checkpoint: 2026-09-10

Prior launcher10804/worker43764 absent; process command scan found no matching
MC worker. Prior stdout stopped at3600, last valid path_id3617; no stderr cause
or final report. Cause UNKNOWN, do not claim successful completion or a crash
diagnosis. Structural prefix audit:8x5000+3618=43618 joint paths,3eligible starts
not run and2ineligible starts preserved. Source outputs remain untouched.

New recovery script checks original simulation/frozen code hashes,policy,rules,
index,snapshots,contiguous IDs and finite metrics; regenerates same seed path
sampling hashes, preserves old JSONL lines byte-for-byte and simulates missing
paths only. New output `outputs/hybrid_delivery/rx06_multistart_recovered_20260910_01`.
Exact command/IDs in `outputs/hybrid_delivery/rx06_recovery_job_20260910_01/launch_record.json`.
Launcher38116/worker16232 confirmed live, initially validating first5000 prefix.
Expected additional paths16382; not a changed experiment or independent samples.
11focused tests passed0.35s, not a fresh full regression. No old source or
simulation runner changed; no system time,collector,model or trade changes.
Before any further launch, inspect these actual process IDs/command and logs;
do not infer completion from stored job status or duplicate a live worker.

## Research addendum checkpoint: 2026-09-09

Current RX06-launch Crypto regression completed: base interpreter
`python -m pytest -q`, exit0,1186passed/10skipped/27subtests,85.69s.
Summary preserved in rx06_multistart_job_20260909_01/checkpoint_tests.json;
not a full raw log and not MC completion or performance evidence. No frontend
changes/tests at this checkpoint. git diff --check also exit0.

RX06 actual historical start freeze and runtime checkpoint:
`scripts/freeze_rx06_multistarts_dev.py --output outputs/hybrid_delivery/rx06_multistarts_20260909_01`
completed exit0:6121 hourly rows,14 outcome-blind starts, all three policy state
restore/hash/value parity. Index SHA55548934cd39cd40d4588aa440d3458dd90269308f3268088d1e5640f3246f18.
Dedicated ExistingExposurePortfolio blocks new _reserve only, retains inherited
pending entry and protection; old allow_entries=False cancels pending and is
not used by new path runner.8focused tests passed0.32s.
Two-path/start smoke exit0 in4.80s:12SMOKE_ONLY,2UNAVAILABLE (24 and1 conditioned
blocks, threshold30 retained). No later replacement starts. Actual full5000 path
run launched hidden with launcher10804/worker43764, local22:16:46 (clock-offset
warning retained). See `outputs/hybrid_delivery/rx06_multistart_job_20260909_01`.
Last observed worker CPU advancing and first start600paths; NOT completed.
Check both process identity and stdout/stderr before restarting; do not duplicate.
Full output: `outputs/hybrid_delivery/rx06_multistart_full_20260909_01`.
Current CLI cannot resume partial output in place; retain failure evidence and
use a new output only after terminal state is verified. No collector/service
restart, account access, model fitting or trading changes occurred.

RX06 multistart contract registered BEFORE new path outcomes in
`config/rx06_multistart_dev_v1.json`. First history-eligible closed UTC hour per
calendar month/BTC regime with original A position or pending. Selection does
not depend on subsequent PnL or conditioned-block abundance. Incomplete prior
history is logged as ineligible; once a start is frozen, insufficient matching
blocks means unavailable, never substitution. Shared 5000 paths/start,12bar
blocks,576bar horizon, seed20260909; existing pending retained, no new signals.
Historical replay NAV peak and simulation-start peak must both be reported;
the old one-start runner resets its path peak and does not meet this new scope.
Pure selection helper added;4focused tests passed0.10s. Actual start materialization
and multistart simulation NOT yet executed. No calibrated risk/performance claim.

RX04 stored-posterior geometry extended without refit:
fast math environment ran `scripts/audit_rx04_geometry_dev.py --output
outputs/hybrid_delivery/rx04_geometry_20260909_01`, exit0 in4.83s wall.
Verified posterior SHA, retained all draws, inspected +/-5 stored draws around
the one divergence plus pooled tau correlations with scalar/group parameters.
Largest reported absolute tau-group correlation is .328235 (SOL UP_TREND);
this does not prove or rule out local funnel geometry. Full leapfrog trajectory
is unavailable, root cause remains unproven and numerical gate remains FAIL.
Nine affected prediction/localization tests passed0.93s; not full regression.
Task registry RX04/RX05 corrected from stale pending/preregistration statuses
to IN_PROGRESS with actual evidence. No system maintenance or trading changes.

RX04 immutable saved-forecast diagnostics completed in
`outputs/hybrid_delivery/rx04_saved_forecasts_20260909_01/report.json`.
Command: base runtime Python, `scripts/audit_rx04_saved_forecasts_dev.py
--population outputs/hybrid_delivery/multifactor_population_20260907_01
--output outputs/hybrid_delivery/rx04_saved_forecasts_20260909_01`.
Exit0; 306 forecasts/102 dates verified against original prediction and
population hashes, training rows and per-row identities/labels. No refit or
new forecast. Added central90 interval score and fixed equal-calendar thirds
to existing diagnostic helper. Eight focused tests passed in0.22s; this is NOT
a fresh full-regression checkpoint.
Overall width10.67713 log-percent, interval score17.22552, coverage89.54%.
Three34-date segments have coverage88.24%/85.29%/95.10% and Brier
.245535/.250524/.272001; paired MSE worse than training-mean baseline in all
three segments. Seven-day synchronized-date bootstrap MSE difference95%
interval[.059853,.941869], Brier difference[-.005143,.016274]. These are
EXPOSED descriptive results, not independent calibration or strategy gains.
RX04 bounded sampler-geometry diagnosis and RX06 multi-start work remain;
runtime consumers disabled. System-time maintenance remains unapproved.

RX07 clock diagnosis advanced beyond Binance-only comparison. Read-only NTP
stripchart commands to time.windows.com and time.cloudflare.com (3 samples
each, exit0) independently show local wall clock behind by approximately
326.7s; W32Time remains Stopped/Manual. Evidence is preserved in
`outputs/hybrid_delivery/rx07_clock_probe_20260909_01/independent_time_check.json`
alongside five native Binance probes. No clock/service/process modification.
The service-stop cause is not proven. Concrete maintenance proposal and scope
are in HYBRID_BLOCKERS_V1_1.md RX07 section. User approval is required before
system maintenance; new clock segment and original freshness bounds required
after any adjustment. Offline RX04/RX06/RX08 work remains executable.

RX05 fixed6h branch executed without changing frozen matching:
`scripts/evaluate_rx05_six_hour_dev.py --output outputs/hybrid_delivery/rx05_six_hour_20260909_01`
base interpreter exit0,48resolvedpairs,2unmatched preserved. Matched signal
mean net6h-.0011379118 (-.113791%); reference+.0113130457 (+1.131305%);
paired delta-.0124509575 (-1.245096percentage points),14/48improved.
Past-reference-through-signal-label intervals form13connected components;
not48independent samples. Fixed-horizon gross and10/5costed price returns
stored separately; no stop/target policy and no portfolio claim.
Critical netR branch issue found BEFORE computing reference policy outcomes:
transferring later signal stop/target geometry backward to earlier reference
time would violate contemporaneous input contract. Branch remains blocked,
not silently evaluated or revised after negative6h result. Need preregistered
reference-time geometry (or explicitly non-PIT descriptive assignment) before
netR comparison; do not change frozen matching/thresholds to improve results.
5reference/matching tests passed0.17s. Old evidence untouched, strategyNO_GO.

RX05 outcome-blind references actually frozen:
`scripts/freeze_rx05_references_dev.py --output outputs/hybrid_delivery/rx05_reference_selection_20260909_01`
base interpreter exit0,9.0s. Frozen50 original signal snapshots reproduce
regime;48matched,2unmatched under preregistered past7day/same symbol/mode/
hour-offset/ATRfraction ratio rule; no relaxed dates/thresholds, zero reused
reference timestamps. Closed historical availability explicitly assumed,
not strict live receipt. Labels/returns not used in reference selection.
selectionSHA6a1d33414fdb14906efbed3e02273f567867018fa9dfa775c5140d3df9954900,
policySHAa1901cd8d5500a3cfe28dd1ed40348aa5108d275742279c252ff81657a3ad9e3.
3matching tests passed0.09s; future candidates cannot change earlier selection,
missing/unavailable/excluded controls stay unmatched. No reference outcomes
computed yet. Next verify synthetic-reference geometry from contemporaneous
price plus frozen relative plan distances, then resolve ORIGINAL policy and
fixed6h movement separately; retain2unmatched and dependency intervals.

RX02 paired summary actual run:
`scripts/summarize_rx02_paired_dev.py --output outputs/hybrid_delivery/rx02_paired_summary_20260909_01`
exit0. All50 meanR ORIGINAL-.050634,T1-.158847,T2-.299889;
paired deltaT1-.108213,T2-.249254. Filled27 means-.158644/-.214149/-.292722;
unfilled23 hypothetical means+.076160/-.093928/-.308301. These are equal-BASE
normalized unit outcomes, not portfolio cash PF; unfilled subset selection is
endogenous and is not evidence to remove risk limits. Seven paired/resolver
tests passed0.24s. Original inputs unchanged, no new training/selection.
RX05 matching rule preregistered BEFORE reference selection/outcome access:
config/rx05_entry_edge_attribution_01.json. One previous7day same-symbol/mode/
5m-hour-offset control; ATRfraction ratio[.8,1.25]; deterministic hashseed20260909;
no match remains unmatched. No sweep, no relaxed constraints, no extension
filter activation. Reference snapshot/geometry/shared resolver audit and
immutable selected IDs still required before resolving matched outcomes.

RX02 fixed50 hypothetical unit outcomes preregistered and actually replayed:
config/rx02_fixed_opportunity_outcomes_v1.json freezes next5m open legacyproxy,
one reference unit,original BASE risk,10/5costs,ORIGINAL/T1/T2,RANGEunchanged.
`scripts/replay_rx02_fixed_opportunities_dev.py --output outputs/hybrid_delivery/rx02_fixed_opportunities_20260909_01`
base interpreter exit0,8.3s.150counterfactual rows:50each policy; each links
original27filled versus23unfilled, never changes original fill/label state.
All27 ORIGINAL outcomes exactly match prior netR/exit-time/reason; inputs
unchanged, authorized capsule hash matches. No cash competition in unit
outcomes, not portfolio PF. Existing full portfolio evidence remains separate.
Uses existing exit_on_bar/structural_exit/netR primitives; no new indicators,
no capital budget or execution rule changes. Missingnextbar unavailable,
gaps censored null; entrygapstop and samebarstopfirst tested. No selection,
no training, no new strategy. Next: bounded aggregate paired attribution and
entry-reference preregistration; keep grouped dependency contract explicit.

RX03 target contract now consumed by actual population retrospective sidecar.
Missing target or attempted netR relabel rejected; existing immutable artifact
target mapped explicitly to POPULATION_GROSS_LOG_RETURN_24H. Real306forecasts
rerun to rx03_population_target_20260909_02,306ABSTAIN,zero formal writes.
Prediction/posterior/population hashes unchanged; review envelope adds contract.
02includes target-contract source hash,01preserved. No model load for execution.
Holding identity audit02 now merges overlapping/touching economic information
intervals:27economic opportunities ->18connected interval components.
This is NOT18independent market samples and assigns no new training/test split.
10708identity-row hash unchanged; maximum group span37.6667h unchanged.
14target/sidecar tests pass0.18s, no full regression claim after these patches.
Next pending RX02: explicitly registered unfilled opportunity counterfactual
policy/shared resolver before matched entry experiments. Existing original
outputs and research-only admission remain unchanged.

RX03 target identity audit completed:
`scripts/audit_rx03_holding_identity_dev.py --output outputs/hybrid_delivery/rx03_holding_identity_20260909_01`
base interpreter exit0.10708holding rows ->130policy parent trades ->27economic
opportunities keyed by symbol/mode/original signal time. Maximum union label
information interval37.6667hours. No partition or training admission created.
Original sources/hashes unchanged. Identity artifact explicitly carries
economic key,parent trade,policy,snapshot and information start/end; validates
source hash,chronology,BASErisk and allowlisted three current holding inputs.
Contract registry separates population24Hgross-log,entry-policy-netR and
incremental-exit-value; cross-target use and runtime consumers denied.
This registry is not yet wired into all research loaders; no claim of systemwide
enforcement. Next: group information-overlap audit and target loader integration,
then matched-entry preregistration after pending RX02 counterfactual contract.

RX02 authorized-capsule excursion audit:
`scripts/audit_rx02_excursions_dev.py --output outputs/hybrid_delivery/rx02_excursions_20260909_02`
base interpreter exit0, original hashes unchanged.130policy trades inspected,
not130independent opportunities. Gross-bar high/low transformed to costed
BASE-R diagnostic marks, first occurrence reported as5m interval, not exact
tick time. Intrabar stop/target exit-bar extrema excluded because price path
after exit is unknowable; gap/authorization checks fail closed.
ORIGINAL19/27positive observed MFE;fixed19/27;T1 18/24;T2 17/25.
Fixed2.5R/3R:19no prior observed touch,8protective exit-bar ordering unknown,
zero target exits. Together with prior17timeout/8stop/2modeinvalidated exits
this explains equality under the frozen protection order, not unbounded
future target performance. T1/T2 retained original target metadata is NOT
active for trend; audit02 corrects audit01's misleading target interpretation.
01preserved as superseded, no original trade changed.18focused tests passed
0.24s. Prior1156full regression predates excursion patch; not latest fullgreen.
Full RX02 and RX01-RX08 remain open; next consolidate target/label contracts
and unfilled counterfactual policy before any matched-entry experiment.

RX02 prior-event occupancy audit completed:
`scripts/audit_rx02_occupancy_dev.py --output outputs/hybrid_delivery/rx02_occupancy_20260909_01`
base interpreter exit0. ORIGINAL23/T1 26/T2 25rejections all supported by
preceding same-symbol reservation/position or unexpired recorded risk pause.
Strict increasing event IDs; entry/reservation and exit/position IDs match.
All three runs end with zero pending/positions. No chronology fabricated.
12focused tests passed0.11s. Fresh complete Crypto checkpoint regression:
1156passed,10skipped,27subtests,76.49s,exit0. This full run includes current
RX02 and MC deadline patches; no frontend changes/build or stock regression.
Result summary checkpoint_tests.json preserves exact observed final lines,
not represented as full raw logs. Next remains legal-window extrema and
first-target-touch audit; not independent OOS, model use or trading approval.

RX02 frozen50 opportunity funnel completed in independent evidence02:
`scripts/audit_rx02_opportunity_funnel_dev.py --output outputs/hybrid_delivery/rx02_funnel_20260909_02`
base interpreter exit0, source files unchanged. Each economic signal joined
to one policy admission event, its completed trade and original label/partition.
ORIGINAL27FILLED_VIRTUAL+23NOT_FILLED(already_exposed);
T1 24fills+25already_exposed+1risk_pause;
T2 25fills+24already_exposed+1risk_pause. Zero pending or ambiguous admissions.
No counterfactual labels generated. Unfilled label_status explicitly
NOT_APPLICABLE_NO_TRADE and netR null; original unavailable labels preserved.
Original raw train/validation/test counts27/9/14, eligible12/5/10;
23excluded as not_mature_executed_population. All partitions exposed DEV,
not independent test and not approved new long-holding purge/embargo.
Legacy unfilled labels use dataset cutoff for information_end; this is not
evidence that those positions remain open. Symbol/mode/UTC-date strata and
all150policy-opportunity rows written. No extra policy opportunities outside
frozen50found.8attribution tests passed0.10s. First01 evidence preserved;
02 adds eligible partition summary, not new selection. RX02 still partial:
legal-window extrema/target first-touch and full occupancy chronology pending.

User addendum archived byte-for-byte at
docs/KQUANT_20260909_Strategy_Review_Research_Addendum.md;
SHA205c9e5ab8cdf72046dc56c4abae0a38d7cdbfaad705452f7c2630dcfa5dbb84.
RX01-RX08 appended to the existing task registry, no duplicate scheduler.
Referenced report hash a62fe909 differs from local c802f6a7; original report
is preserved, version mismatch remains unresolved, not evidence equivalence.

Actual RX02 partial audit command (base pinned interpreter):
`scripts/audit_rx02_attribution_dev.py --source outputs/hybrid_delivery/multifactor_portfolio_20260907_02 --paired outputs/hybrid_delivery/multifactor_exit_replay_20260907_02 --output outputs/hybrid_delivery/rx02_attribution_20260909_01`
exit0. Every source trade hash checked, inputs unchanged. Cash bridge
reconciles gross reference PnL minus actual simulated entry/exit slippage and
fees to net PnL; no second cost deduction. BASE risk denominator retained.
ORIGINAL gross-25.63081 / costs81.35569 / net-106.98650;
T1 gross1.59677 / costs71.65960 / net-70.06283;
T2 gross-84.74152 / costs74.54363 / net-159.28515.
T1 common24 opportunities have cash delta-13.50358 versus baseline;
three baseline-only trades net-50.42725; no challenger-only trades.
T2 common25 delta-77.75247; two baseline-only net-25.45382.
Fixed A27 paired exit delta meanR T1=-.05550434,T2=-.13407796.
These are descriptive subsets, not causal proof or winner selection.
Fixed2.5R/3R each exit via17timeouts/8stops/2modeinvalidations, no target
exit; exact first-touch audit remains pending. Existing paired audit excludes
23unfilled opportunities; no0R fill. Full RX02 is NOT complete.
6affected tests passed0.24s (4attribution+2MCdeadline), not full regression.
Process inventory showed no KQUANT-path Python executable at this snapshot;
other Python/Node services exist. No claim of collector continuous health,
no service stopped/restarted. More precise service ownership remains RX07.
Next: audit full50 technical opportunity identities, rejection chronology,
and legal-window target/extrema using authorized capsule, then preregister
entry attribution. Model filtering/sizing/execution remain disabled.

Prior MC deadline fix is now recorded: expired hardcoded cutoff removed in
favor of explicit optional timezone-aware operational --deadline-utc;
--capsule supported. Actual smoke2 run multifactor_mc_capsule_smoke_20260909_01
completed2paths, first2results match old5000run. Not a new5000path acceptance.

## Explicit human resume: 2026-09-09

Portable portfolio packaging now includes policy, current exchange rules,
original specification and full pure replay source dependencies. First build
multifactor_portfolio_portable_20260909_01 failed because runner assumed output
parent existed. Failure/log preserved. Runner now creates parents but refuses
existing output; no policy/risk changes. New02build exited0 in42.264s,
dataset and complete10scenario results exactly match frozen reference.
Archive authorized_dev_portfolio_replay.zip:6688794bytes,
SHA85b90b0d4f072eab47ff528422900c3c0d86dd7fa834688ec36755cc4527638b.
45affected tests passed2.02s. Existing dataset-only archive remains unchanged.
Final actual zip extraction/replay in the clean duckdb-only environment:
multifactor_portfolio_clean_verify_20260909_01,exit0,42.553s,PASS for dataset
and complete scenario parity; input hashes unchanged. The archive RUNBOOK
contains the working command and result locations. No model/strategy upgrade.
This package still excludes mathematical fitting,MC and online acceptance;
current exchange filters remain a disclosed historical-PIT limitation.

Full portfolio runner now accepts --capsule and --verify-reference. Actual run:
`scripts/replay_multifactor_portfolio.py --capsule outputs/hybrid_delivery/multifactor_dataset_capsule_20260909_01 --verify-reference outputs/hybrid_delivery/multifactor_portfolio_20260907_02 --output outputs/hybrid_delivery/multifactor_portfolio_capsule_20260909_01`
used clean work/multifactor_portable_verify_env_20260909/Scripts/python.exe,
exit0. All10scenarios exactly reproduce trade/equity hashes:REFERENCE,ORIGINAL,
fixed2.5R/fixed3R/T1/T2 at their registered base/stress costs. No selection.
Original27meanR-.158644/PF.574417;T1_1:24meanR-.116007/PF.666913;
T2_1:25meanR-.255995/PF.368306. Failure preserved, no profit qualification.
40affected portfolio/exit/capsule tests passed1.86s. Data now portable for full
portfolio replay, but this run still uses repository code/policy/rules/spec;
those dependencies must be bundled before source-isolated portfolio acceptance.

Source/data-isolated replay archive produced and executed:
outputs/hybrid_delivery/multifactor_portable_replay_20260909_01/authorized_dev_dataset_replay.zip
SHA633d13e2084efdf550eddd23f2a2c825dc412a7c3cb4ab06e657e5826df1b918,
6649763bytes.11explicit source files,DEV-only data capsule,requirements/RUNBOOK
and per-member hashes. No credentials or unrestricted Parquet embedded.
Actual isolated-import rebuild exited0 in19.574s with unchanged inputs and all
three data/features/labels hashes matching the original frozen dataset.
Final verifier with declared-path checks and its own source hash reran as
multifactor_portable_clean_verify_20260909_02:exit0,20.491s,all hashes equal.
Then created work/multifactor_portable_verify_env_20260909 using venv; installed
only declared duckdb==1.5.5 (cached wheel; pip25.0.1 also present). Existing
collector environment untouched. Actual archive extraction/rebuild from this
environment exited0 in20.401s, same hashes. Evidence clean_verify_20260909_01.
Package RUNBOOK conservatively reflects build-time fresh-install-not-tested;
the subsequent clean verification supplies that evidence separately, no old
archive overwritten.10archive/capsule tests pass after explicit declared-path
and Windows case-alias validation. This is dataset replay only; full models,
MC,portfolio and online release remain incomplete.

Portable DEV dataset roundtrip and actual feature/label reconstruction completed:
`scripts/export_multifactor_dataset_capsule_dev.py --output outputs/hybrid_delivery/multifactor_dataset_capsule_20260909_01`
then
`scripts/build_hybrid_multifactor_dev.py --capsule outputs/hybrid_delivery/multifactor_dataset_capsule_20260909_01 --output outputs/hybrid_delivery/multifactor_capsule_rebuild_20260909_01`
Both base-interpreter commands exited0. Capsule includes only approved DEV plus
warmup: each coin76440five-minute/6370hourly bars; compressed6667383bytes.
Actual source receipts/provenance roundtrip unchanged; assumed-close remains
historical proxy, not observed availability. Restricted tail absent.
Rebuilt18360feature snapshots and36720labels exactly match previous dataset06
dataset/features/labels hashes. Mature6h18342,24h18288; censored18/72, never0R.
Capsule hash686ac7b368d1d1300ef5e847d9d82621677dded67c6750335d6dde4db95165bd.
14affected tests passed0.53s. This removes dependence on original full-range
Parquet for this builder; portable runtime/source and full replay/model bundle
are still incomplete. No refit or change to original results or admission.

Latest full Crypto base regression:1132passed,10skipped,27subtests passed,
67.73s,exit0. Isolated math sensitivity rerun:7passed,1.38s,exit0.
No stock tests or frontend build rerun for these Python-only research changes.

Receipt recovery command now implemented:
`scripts/recover_multifactor_hourly_dev.py --source outputs/hybrid_delivery/multifactor_native_receiver_20260909_01 --output outputs/hybrid_delivery/multifactor_native_recovery_20260909_01`
ran with base interpreter, exit0. Actual21rejections reproduced, original source
hash unchanged, zero snapshots/labels. Old run lacks durable journal_contract;
status AUDIT_ONLY_NO_DURABLE_JOURNAL_CONTRACT, not live recovery acceptance.
New-contract logs recalibrate from recorded probes, reproduce normalization,
validate freeze time/hash/chronology, and replay only recorded freezes into a
new independent directory. Missing freeze intent means pending ingestion only.
Truncated tail requires explicit salvage; never silently skipped.46affected
tests passed in1.35s including synthetic crash after intent, repeat replay,
missing intent, tamper, independent CLI and source preservation.
Current reader requires matching adapter/clock/journal source versions; it is
not a general migration tool or continuously reconnecting collector.
Full base regression first failed collection because new sensitivity test
imported SciPy; test now explicitly skips absent isolated math dependency.
No packages installed in collector environment. Math sensitivity7tests had
already run successfully in its isolated environment; skip is not math PASS.

Actual population forecast-to-sidecar compatibility run completed, exit0:
`scripts/audit_multifactor_population_sidecar_dev.py --artifact outputs/hybrid_delivery/multifactor_population_fit_20260908_01 --predictions outputs/hybrid_delivery/multifactor_population_prediction_20260908_01 --population outputs/hybrid_delivery/multifactor_population_20260907_01 --output outputs/hybrid_delivery/multifactor_population_sidecar_20260909_01`
using the pinned base interpreter.306existing exposed diagnostic forecasts,
306ABSTAIN, zero formal EVAL writes. Forecast values and model metadata hash
are bound to each review; target outcomes are excluded from reviewer inputs.
Population24h gross-log forecasts have no executable plan and cannot substitute
for costed entryR. Unknown model availability is not backdated; one-divergence
numerical failure remains explicit.14affected tests passed in0.16s.
Reviews SHA c47a754999b8c9d86fdd930e3e69e3ee8e28d067e7d74a39782b97de249b4698.
This is retrospective forecast compatibility, not new inference, training,
calibration or forward integration. Full MF6 acceptance remains incomplete.

Offline factor branch continued independently of online acceptance:
`scripts/audit_multifactor_block_sensitivity_dev.py --output outputs/hybrid_delivery/multifactor_block_sensitivity_20260909_01`
ran with work/hybrid_math_restore_env_20260906/Scripts/python.exe, exit0.
Input is the previously frozen training_rows.json verified against the pause
checkpoint, not diagnostic/test rows. Preregistered fixed7day simultaneous
three-coin deletions, no refit/feature selection/activation.450rows,150UTCdates,
22blocks including the explicit partial tail. Spearman direction reversals:
return_6h1, er24zero, relative_volume24seven, relative_core24one.
Full correlations respectively .03596,.09616,.00625,.01585. These weak gross24h
relationships are not netR evidence, calibrated probabilities or independent
folds.7new tests passed in1.79s; original model and strategy unchanged.
MF2 remains incomplete; do not promote this diagnostic to strategy acceptance.

Receiver write-ahead follow-up: journal_contract is now recorded before journal
creation. Each accepted receipt records and fsyncs freeze_intent (sequence,
event ID/hash, calibrated receipt interval and rounded-up frozen_at) before
ingest or advance. journal_commit is written only after both succeed.
Log persistence failure prevents either database write; database failure leaves
the original intent available for recovery without inventing a later timestamp.
36 affected tests passed in1.33s, exit0, including both database failure points
and intent persistence failure. This is component-level fault injection, not
an actual closed-hour live recovery acceptance. Existing run01 is unchanged;
it predates journal_contract/freeze_intent and must not receive retroactive ones.
Still pending: independent receipt-log recovery command with source/clock/hash
validation and handling of missing intents, then actual closed-hour lifecycle.
No new observation, model fit, screening, sizing or execution was activated.

Independent bounded native receiver actually executed:
`scripts/observe_multifactor_hourly_dev.py --output outputs/hybrid_delivery/multifactor_native_receiver_20260909_01 --seconds 15`
using the pinned base interpreter below. Exit0, total29.641s including probes,
connection and cleanup; requested15seconds was the post-calibration receive
window including connection establishment, not a whole-run deadline.
Five clock probes and raw envelopes persisted before parsing/factor writes.
21real messages,21forming-hour rejections,0accepted closed hours,0snapshots,
0labels. No natural lifecycle or warmup acceptance. Local UTC still differs
from server-aligned receipt by approximately327seconds; raw and interval clocks
both preserved, system time untouched, freshness30seconds unchanged.
Receipts SHA c0f6073e2e7b603ad87c9f1abca39578e4e9d61c440ed7ff45f94f08ebf17497.
Report and manifest in that immutable output directory.32affected tests passed
in1.24s, including clock-failure archive and existing-output refusal.
Receiver is deliberately bounded1..300seconds, one connection and no bootstrap;
it does not implement long-running recovery or full250hour warmup yet.
Next: durable receiver-to-factor recovery plus full research delivery, not
repeated short runs presented as independent market evidence.

Native hourly receipt adapter added: hybrid_hourly_receipt.py. It consumes
UTC Binance Spot closed1H kline messages with native E/t/T milliseconds and
the existing ClockSegment bounds/check contract, never substitutes serverTime
or local time for source event time. Existing30second freshness unchanged.
Accepted event payload persists native time, calibrated receiver interval,
raw message hash and adapter version atomically in the independent journal.
Integer factor availability rounds up; quote_evidence remainsfalse.
Thirty affected tests passed including three-symbol freeze/reopen with retained
provenance,320second stale rejection, missing time, unit mismatch, forming bar,
clock expiry and local jump. These are synthetic contract tests, not measured
online receipts. No observer launched and no natural label lifecycle claimed.
Official field reference checked on2026-09-09:
https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams
Next integration must archive rejected raw envelopes too and preserve bounded
processing, receiver continuity and ownership; this adapter alone is not a
running collector or complete forward release.

User explicitly requested continued work after the night pause. Delivery resume
exited0; multifactor development pause flags cleared. HEAD remains baac8d1;
the four existing tracked modifications were preserved. No KQUANT Python
process was present at inspection; unrelated processes were not touched.
No model refit, service restart, deployment or execution activation performed.

Frozen-file ingress binding now uses a separate input_binding.sqlite3 beside
the independent factor journal, without changing its schema or code hashes.
The exact input bytes (maximum32MiB) are hashed and consumed from the same
in-memory snapshot. Changed files and out-of-range offsets fail closed.
Old unbound journals remain intact and cannot be silently bound: use a new run.
This is immutable-file ingestion, not an append-only live stream contract.

Actual new run bound_recovery_20260909_01 consumed500 then504events in separate
CLI processes; retry of the first event inserted0/idempotent1. All exited0.
Input SHA256:7b469114a2d9298b43a078656bfd623ea8721ec02f16206eb30fb9bee82fd3fc.
Same fixture paths and interpreter as below; use --offset500 for the second
batch (CLI spelling: --offset 500). Receipt basis remains REPLAY_CLOCK_FIXTURE,
DEV_ONLY, executionfalse and live_acceptancefalse.19affected tests passed in
0.63s; git diff --check exited0. No full release regression claimed.

Next: isolated real receipt integration and independently reproducible release.
Completed population numerical failure and negative strategy evidence remain
unchanged. No automatic model screening, sizing or Live promotion permitted.
Existing heartbeat remains paused; no duplicate automation created this turn.

## Night pause: 2026-09-09 approximately 01:52 CST

Development paused ahead of the02:00deadline; no KQUANT Python process was
running at inspection. Other project processes were left untouched. Delivery
pause-development invoked; multifactor task graph requires explicit human
resume. Existing kquant heartbeat is paused, not duplicated. No fit restarts,
service restarts, model activation or trading action. All current evidence
remains in the paths below; current assessment01 is the latest summary.
Automatic goal continuation is not fresh human authorization to resume.

## Explicit user resume: 2026-09-08, current checkpoint

Source-linked current assessment generated successfully with all scenario trade
hashes verified: `outputs/hybrid_delivery/multifactor_current_assessment_20260908_01/CURRENT_ASSESSMENT.md`.
Machine-readable assessment.json binds7source report hashes. Four states remain:
engineering PARTIAL, data PARTIAL/proxy, model NUMERICAL_GATE_FAIL,
performance PERFORMANCE_UNPROVEN with descriptive negative replay results.
No refit, selection, restricted interval, formal evaluation or execution action.

Runnable factor ingress CLI verified in separate processes:
`scripts/run_multifactor_factor_journal_dev.py consume|status`.
Independent run `cli_recovery_20260908_01` consumed500 then504events using
`--offset 500`; returned next_offset1004. Status reports1004, executionfalse.
One duplicate retry inserted0/idempotent1. No provider/model imported.
Fixture: `outputs/hybrid_delivery/multifactor_ingress_cli_fixture_20260908_01`;
actual authorized historical bars but explicitly synthetic receipt clock.
From crypto cwd, interpreter remains
`.\work\hybrid_runtime_restore_env_20260906\Scripts\python.exe`.
Status command: `scripts/run_multifactor_factor_journal_dev.py status --run-id cli_recovery_20260908_01`.
Consumption takes `--input <events.jsonl> --contract <contract.json> --offset <next_offset> --limit 1000`.
Use returned event offset (nonempty records); changed input needs a new run.
Status is read-only metadata, not a full integrity replay claim.17affected tests
passed before offset addition; keep online/P95 and live acceptance false.

Factor journal cache optimization independently rerun as
`outputs/hybrid_delivery/multifactor_journal_recovery_20260908_02`.
Same251hours/1004events/753snapshots:8.672s versus299.39s earlier.
All saved event payloads, results and digests match run01 exactly.14tests pass,
including external connection commits/corruption invalidating cached state.
Cache is copied before mutation, discarded on failure, rebuilt after restart;
SQLite data_version and connection total_changes checked under write lock.
Old source archived in run01/hybrid_factor_journal_frozen.py before changes.
Code-hash mismatch intentionally refuses opening old journal with new code;
old evidence remains readable with read-only SQLite and its archived contract.
This removes measured replay-per-event cost, not online/P95 acceptance.

Actual-data factor journal recovery audit completed:
`outputs/hybrid_delivery/multifactor_journal_recovery_20260908_01`.
251authorized historical hours,1004events,753snapshots exactly matched the
in-memory adapter, including6snapshots after all19factor warmups completed.
Halfway reopen plus duplicate retry inserted0extra records. Runtime299.39s,
exit0. Receipts are synthetic close+1second, not online evidence.
Database SHA5b400fea1f99901b70d88bb758faeeb23fbdc7a314a34168a8b79d3ec8a08a26.
This exposes the cost of replaying full history per append; throughput is NOT
accepted for live operation. Optimize only against the same frozen outputs.

Holding temporal audit completed on all10708v2 observations without fitting:
`outputs/hybrid_delivery/multifactor_holding_overlap_20260908_01/report.json`.
Existing 2026-01-01UTC boundary retained; no boundary-selected optimization.
ORIGINAL has12earlier/15later holding groups (614/820rows); fixed2.5R and3R
each12/15groups (614/822rows); T1 10/14groups (1802/1741rows); T2 11/14groups
(1150/1709rows). No group spans this particular boundary. Later remains
EXPOSED_RESEARCH, not independent test. Cross-policy groups are correlated.
Max entry-to-label availability: ORIGINAL/fixed21900s, T1 135600s, T2 87300s.
The extra exit-bar300s is availability, not additional realized holding time.
Four temporal-group tests pass. These observed maxima are NOT newly approved
embargo parameters. Holding training remains disabled pending its contract;
completed authorized entry/population DEV fits are unaffected.

Independent factor event journal added (`hybrid_factor_journal.py`). Input,
explicit freeze-clock event and frozen output commit atomically. Recovery
replays the bounded event history and verifies saved results/content hashes;
module hashes and receipt contract are frozen at database creation.
Twelve journal/ingress tests passed: reopen/idempotency, injected SQLite failure,
changed payload, corrupted snapshot, foreign database and receipt-policy change.
This is library-level recovery evidence, not an operating online receiver.
Replay cost grows with history; max10000events is an explicit safety bound,
not a throughput guarantee. No production writer or service is connected.

Incremental factor ingress verified against the frozen authorized historical
dataset06: 18360 snapshots / 348840 values (all19 factors) exactly match batch.
Evidence: `outputs/hybrid_delivery/multifactor_incremental_parity_20260908_01`.
Command exited0:
`.\work\hybrid_runtime_restore_env_20260906\Scripts\python.exe scripts/audit_multifactor_incremental_parity_dev.py --output outputs/hybrid_delivery/multifactor_incremental_parity_20260908_01`
Use a NEW output directory for reruns; existing evidence is immutable.
Receipt is preregistered synthetic close+1second, NOT measured online latency.
Twelve affected tests passed. Missing peers, future receipts, forming bars,
out-of-order arrival, duplicate/correction and bounded pending queues covered.
No collector started; this in-memory adapter does not claim restart recovery.
Next: independently persisted forward input/checkpoint integration, without
loading DEV artifacts into formal consumers or touching original writers.
Engineering parity PASS; online data acceptance incomplete; model DEV_ONLY;
performance remains unproven. Review bundle01 predates these new modules.

Independent review persistence exercised on actual27retrospective abstentions:
`work/multifactor_research_reviews.sqlite3`,run `a27_compatibility_20260908_v1`.
First ingestion inserted27; second fresh CLI process inserted0/idempotent27.
Both commands exited0. Original validation/EVAL/PAPER/SHADOW schemas untouched.
Store refuses unrelated database tables, executable permissions, changed run
manifest or changed same-ID payload. Batch failure rolls back run and records.
Ten store/sidecar tests passed including reorder/reopen, injected SQLite failure,
and formal-database refusal. This is an audit ledger, NOT Paper fills or a
completed forward model integration. No market receiver or service was started.
Command:
`.\work\hybrid_runtime_restore_env_20260906\Scripts\python.exe scripts/ingest_multifactor_reviews_dev.py --source outputs/hybrid_delivery/multifactor_sidecar_audit_20260908_02 --run-id a27_compatibility_20260908_v1`
Review bundle01 predates this storage module and does not include the database.

Review delivery bundle created and independently read-verified:
`outputs/hybrid_delivery/multifactor_review_bundle_20260908_01/KQUANT_MULTIFACTOR_DEV_REVIEW_20260908.zip`.
145manifest members,22213356bytes;SHA9a6d1c5ceaf9f8b93c8785134a84d78c8fe642a9e436a7a825b11341c05f1a44.
Six integrity/tamper/path tests passed. Includes actual completed posterior,
daily population, predictions, labels, selected trade/equity ledgers and reports.
Raw OHLC and full environment are NOT included; not standalone replay/deployment,
not independentOOS or a releaseGate. Do not present packaging as completion ofMF6.
Verify without extraction or execution:
`.\work\hybrid_runtime_restore_env_20260906\Scripts\python.exe scripts/verify_multifactor_review_bundle.py outputs/hybrid_delivery/multifactor_review_bundle_20260908_01/KQUANT_MULTIFACTOR_DEV_REVIEW_20260908.zip`

LATEST: population sampling COMPLETE, not still running.
Completed-chain audit independently verifies every chain variable equals its
combined-posterior slice and recomputes matching diagnostics. Single divergence
is chain2/draw162(zero-based), maxdepth hits0. No unique root cause claimed.
Evidence `multifactor_population_chain_audit_20260908_01`,commandexit0.
Mode diagnostic MSE differences from trainingmean: RANGE+0.1028,
TRANSITION+0.9325,UP_TREND+0.1813. Trend grossBrier slightly improves but only
27daily records/14dates; NOT original A27filled labels and not a chosen winner.
At23:07 local on2026-09-08, child PID10016 no longer exists; stdout and full
artifact report COMPLETED. Background process exit code was not captured, so do
not invent one. The independent diagnostic command subsequently exited0.
Do not restart or refit this population merely to repair its negative evidence.
All4chains complete,1000draws each,450TRAIN rows/150dates. Rhat1.00510,
bulkESS1013.95,tailESS1511.31,BFMI0.8093..0.8995,maxdepth0,but1divergence.
Registered divergence limit0 => NUMERICAL_GATE_FAIL. Runtime flags remainfalse.
Posterior SHA0557776debfef9c6f3e13214a23f1c8ff27b8149f6114e2c8fe24e9a98d81ba9.
Resume sampling/predictive elapsed13056.843seconds, excludes prior completedchain0.

Actual EXPOSED prediction diagnostic on306rows/102dates:
`outputs/hybrid_delivery/multifactor_population_prediction_20260908_01`.
MAE2.623396 vs trainmean2.564777;RMSE3.720931 vs zero3.667068;
Brier0.2560199 vs trainfrequency0.2496151; ECE0.100501;
central90coverage0.895425. Coverage alone does not establish calibration.
Synchronized7day/2000replicate MSE error-difference interval[0.05985,0.94187]
is worse than training mean; Brier difference interval[-0.00514,0.01627].
All3coins have worse point MSE and Brier than their same global train baselines.
These are gross24h log-percent development outcomes, not trade netR or winrate.
No independent OOS, calibrated probabilities, tail/mean qualification or
PERFORMANCE_PASS. Retain all failures. Next work: consolidate reproducible
delivery and specifically bounded independent-forward requirements; do not
load the artifact into formal consumers or optimize against this exposed result.

Post-change regression checkpoint:
Crypto base environment1068passed/9skipped/27subtests,116.15seconds,exit0;
JUnit `outputs/hybrid_delivery/multifactor_regression_20260908_01/junit.xml`.
Skips concern isolated numerical environments, not unnoticed passed tests.
Affected MC numerics/posterior review/DEV-fit suites rerun in isolated math
environment:42passed,7.66seconds,exit0, JUnit
`outputs/hybrid_delivery/multifactor_math_regression_20260908_01/junit.xml`.
No new sampling was initiated by those tests. Compiled sampler-specific and
separate artifact tests remain outside this follow-up run.
Source checkpoint382files: `multifactor_source_checkpoint_20260908_01`;
SHA691d01ae04b284d241a1edc73b5214dd60e497bf70ddb3b8bb798583261f7261.
All four attached evidence configs' declared source hashes match the archive.
It excludes data/models/secrets and predates this final report/task-status edit;
it is a reproducible source checkpoint, not a deployable full release.

Actual read-only model/plan compatibility audit completed:
`outputs/hybrid_delivery/multifactor_sidecar_audit_20260908_02`.
Uses hash-verified completed A27 multifactor artifact and matching frozen training
rows, joins original opportunities by economic_signal_id (plan fields are not
on compact executed_trade). Run01 failed on that field mismatch and is retained.
Run02 reviewed27/abstained27. All have post-signal training labels, unverified
model availability, proxy execution and unvalidated outputs. No posterior
inference, formal EVAL/PAPER/SHADOW writes, alerts or trading gates occurred.
Model target mapping distinguishes gross24h log-percent from BASE trade netR;
formal consumers are refused. Eight sidecar/artifact tests passed.
This is retrospective compatibility engineering, NOT completed MF6 forward
integration. Gated independent forward run and full acceptance remain unfinished.

Holding labels corrected by NEW version, old evidence retained:
`outputs/hybrid_delivery/multifactor_policy_holding_v2_20260908_01`.
Old A holding v1 used exit-bar start as label availability. V2 uses conservative
exit_time+300seconds, censors beyond authorized cutoff and rejects path gaps.
This correction does not affect the active daily-population fit or A27 entry-R
model, which do not consume holding v1 targets. Do not train holding v1 labels.
V2 SOURCE BASE risk and actual exit fees are preserved; final trailing stop is
not a historical feature. Source ledger hashes verified. Original1434 labels,
fixed2.5R/3R1436each,T1=3543,T2=2859, total10708 conditional observation rows.
These are27/27/27/24/25source trades with cross-policy overlap, not130 independent
trades or10708independent samples. All mature in this run; missing/censored
behavior covered by tests. Six old/new holding tests passed, exit0.
New holding training remains disabled pending explicit variable-horizon embargo
contract. Prior outputs, original strategy and sampler were not changed.

Actual TRAIN-only factor ablation completed:
`outputs/hybrid_delivery/multifactor_ablation_20260908_01`.
Uses only hash-verified parent training_rows.json, not diagnostic labels.
Three expanding folds within150TRAIN dates,24h purge/embargo, fixed Ridge alpha1;
FULL plus exactly four leave-one-out variants. Train counts174/264/354;
validation87rows per fold. Removing return_6h lowers MSE by0.2300/0.1650/0.0405;
other effects change sign by fold. This is unstable incremental feature evidence,
not a trading result or permission to change the active four-factor Bayesian fit.
Saved preregistration, membership and per-variant training preprocessing.
Three ablation tests passed including future-outcome perturbation and missing
label rejection. Next: complete existing sampler, then run frozen prediction
audit; no winner selection or additional alpha search.

Prediction diagnostic preparation completed while sampling remains active:
`hybrid_prediction_diagnostics.py` computes symbol/mode/symbol-mode error and
coverage breakdowns, paired MSE/Brier differences against training-only baselines,
and 2000 synchronized7-day UTC moving-block replicates with fixed seed202609078.
Missing dates disable resampling instead of bridging gaps. Duplicate, unfilled,
unknown-label and future-feature observations are rejected. Fewer than12 weekly
blocks are explicitly unstable. This is exposed descriptive comparison only,
not calibrated probability, independent OOS or performance admission.
Integrated into `scripts/audit_multifactor_population_prediction_dev.py` before
any completed-population posterior is available. No active sampling code changed.
Focused resume/deadline/artifact/diagnostic tests:15 passed, exit0,0.63seconds.
PID11700 is the venv launcher; actual sampling child PID10016 was verified by
parent relation and creation time. Do not infer a stalled fit from launcher CPU0.

The actual human requested continuation after the pause below. Development is
resumed; historical pause sections below are retained as evidence, not current
instructions. No strategy, prior, seed, sample size or trading gate changed.

Remaining-chain fit launched at 19:23 Asia/Shanghai, launcher PID11700.
Verify actual process identity and logs before any further launch; PID alone is
not ownership proof. Parent chain0 and all frozen input hashes passed verification.
Completed chain0 is reused; incomplete chain1 starts again from its registered
seed, not from a nonexistent mid-chain checkpoint. Output directory is new:
`outputs/hybrid_delivery/multifactor_population_fit_20260908_01`.
Logs: `outputs/hybrid_delivery/multifactor_population_resume_20260908_01`.
Six resume tests passed; actual `--verify-only` returned1 completed/3 remaining.

Cooperative operational deadline: 2026-09-08T18:00:00Z (next02:00 local),
preserving the user's overnight stop preference. On deadline save evidence and
pause development/scheduler, not original services. Check for a complete4-chain
artifact before running the prepared exposed prediction audit. No calibration,
performance PASS, math filtering, sizing, deployment or Live is authorized.

Actual command (working directory: repository crypto):
```powershell
.\work\hybrid_dev_fit_fast_env\Scripts\python.exe scripts/fit_multifactor_population_dev.py --population outputs/hybrid_delivery/multifactor_population_20260907_01 --output outputs/hybrid_delivery/multifactor_population_fit_20260908_01 --resume-from outputs/hybrid_delivery/multifactor_population_fit_20260907_01 --checkpoint outputs/hybrid_delivery/multifactor_pause_20260907_01/checkpoint.json --deadline-utc 2026-09-08T18:00:00+00:00
```
Do not repeat this command while running or reuse its existing output directory.

## PAUSED BY USER: 2026-09-08 02:00 Asia/Shanghai

Development and training are paused. Do not treat automatic Goal continuation
or a heartbeat as explicit user resume. No further implementation/training until
the user resumes. Full objective remains unfinished; do not mark it complete.

Session70007 exited0 with DEADLINE_PARTIAL at the requested deadline. One of
four chains is complete and hash-verified; interrupted second chain is not a
completed chain and cannot be resumed mid-chain. No final population posterior
artifact or predictive diagnostic was produced. Chain0 remains immutable.
Actual checkpoint: outputs/hybrid_delivery/multifactor_pause_20260907_01/checkpoint.json.
Delivery.pause=True and existing kquant heartbeat status=PAUSED were confirmed.
No original market collection, website or protection process was stopped.

Latest source archive02 SHA:
5105620f118439286707bab7150e2bb029ebcfc029c42563b9eda079673c37bd.
It precedes this final status note; the pause JSON is the authoritative terminal
checkpoint. No code was deployed, committed or pushed during this work.

After explicit resume: investigate isolated sampler runtime without changing
priors/targets, implement verified remaining-chain continuation reusing chain0,
then run the prepared exposed diagnostic only after a complete4-chain artifact.
No automatic math selection, sizing, formal model consumption or Live upgrade.

## User stop deadline

Pause development and training at 2026-09-08 02:00 Asia/Shanghai
(2026-09-07 18:00 UTC). Save a checkpoint and wait for explicit user resume.
Do not stop existing market collection, web services or protection channels.
Check the deadline before starting work; do not start long jobs that cannot
be safely checkpointed by the deadline. Existing heartbeat has the same rule.

## Latest priority: multifactor DEV research

Incremental follow-up:
- Population fit01 completed chain0:1000 posterior draws after1000 tune,
  sampler time4664s. Chain hash:
  26fbb44d4e243c1d78ca5fd099af708d2bd779e88d3ddacba708fa64e3774124.
  Independent partial-chain audit01:0 divergences,0 max-depth hits,
  mean tree depth4.079,max5,BFMI0.8093. NO multi-chain Rhat or complete model.
  At this checkpoint chain1 is running; session70007 remains authoritative.
  Current environment logged Python fallback/no C compiler; exact performance
  root cause not profiled. Do not change priors or claim saturation to explain
  runtime. Completed chain files preserved, interrupted chain is not resumable
  mid-chain; future recovery needs an explicit remaining-chain runner, not a
  duplicate full fit. User02:00 deadline still enforced by per-draw callback.
- Nested opportunity folds02 implements fixed24h labels only, not unbounded
  holding. Fold01 calendar eligibility accidentally included previously purged
  rows whose numeric labels were not exported; never fitted. Corrected02
  explicitly excludes those values, retains old01 and changes version1.0.1.
  Outer train297/450/597; outer diagnostic147/150/150. Three tests passed.
- Actual nested Ridge baseline01 uses four frozen factors and only inner
  alpha candidates[1,.1,10], no expanded search. Outer MSE8.166/17.519/10.417
  versus train-mean8.384/17.422/9.626, so only first segment improves. All
  EXPOSED development, no independent OOS or profit claim. Existing active
  Bayesian fit inputs/config unchanged. Artifact directory:
  outputs/hybrid_delivery/multifactor_nested_baseline_20260907_01.
- Crypto regression saved at outputs/hybrid_delivery/multifactor_regression_20260907_01/junit.xml:
  1034 passed,9 skipped,27 subtests passed,128.72s,exit0. Later eight focused
  exit/dependence/interval/deadline tests passed; git diff --check exit0.
- Exit-quality audit01 completed. BASE trend mean close-observed giveback:
  original0.6455R,T1 1.0413R,T2 1.0470R. Closed5m marks, not intrabar MFE;
  exit-bar future excluded. Post-hoc only, never a feature. No unavailable rows.
- Factor-lab01 uses450 TRAIN rows/150 UTC dates only:19 registered factors,
  training quintiles/correlation and symbol/state/time-half rank diagnostics.
  Four abs(correlation)>=.85 pairs flagged, no automatic removal/reselection.
  Population fit retains its four preregistered inputs, not19 simple weights.
- Source checkpoint01 archive SHA:
  e3bdadfbe705dc562d2a0ac96b165c59a691ae16f0406498fa37f7a4740700d8.
  Declared code hashes for dataset06,population01,fit01 and MC01 matched.
  Source-only checkpoint, not full data/model backup or deployable release.
- Prediction audit CLI prepared but NOT run: audit_multifactor_population_prediction_dev.py.
  It requires completed population artifact; recomputes preprocessing from frozen
  TRAIN rows, evaluates only exposed diagnostic rows, never fits/calibrates.
  Do not call unfinished model a completed artifact. Continue polling session70007.

2026-09-08 00:30 CST incremental checkpoint (prior entries below are historical):

- MC run outputs/hybrid_delivery/multifactor_mc_20260907_01 completed5000.
  Path SHA b29f9b66663278cf09dfb449e27560531d89fc83ff05bd0a18e79a66a13c96c4.
  One historical snapshot, no new entries, no model uncertainty addition.
  audit_multifactor_mc_dev.py audit01 failed: base interpreter lacks scipy.
  No environment modified. Audit02 succeeded using existing isolated
  work/hybrid_math_restore_env_20260906/Scripts/python.exe. Paired net-change
  means vs original: T1 -5.6722, T2 -4.4072. Zero budget events still has
  conditional upper bound0.0011401, not zero real-world risk. Not calibrated.
- Saved full-portfolio audit01 records original27, T1 24, T2 25; conservative
  information interval ends at exit-bar close, not intrabar timestamp.
  T1 longest37.583h, T2 longest24.167h. Dependency groups18 each versus21
  original. T1 mean-R95% interval[-.4431,.2735], T2[-.4902,.0115]. Exposed
  synchronized calendar bootstrap, not independent validation. Old6h embargo
  cannot certify new holding targets; 10R definition remains unresolved.
- Dataset06 adds core correlation/covariance and vol6/prior18 only. 18360
  hourly rows,19 registered factors; labels unchanged. Feature hash
  6e4b0c4906937c47547e551df7e3f0ee99633e9b72791df2c31e50d58553fbcc.
  Existing fitted input datasets remain untouched. Eight relevant tests pass.
- Population01 selects each UTC midnight independently of old fills. 765
  rows:450 eligible TRAIN,6 purged,306 exposed development diagnostic,3 censored.
  Original A technical regime reconstructed from5m+1h with entries suppressed;
  not portfolio-feedback state. Transition is retained without trading rights.
  Hash22c669fd0a18b40dbe689a63f8c112390bde6d0f52708df12fe588a84b2f5e47.
- Actual isolated population Student-t fit01 STARTED, not yet complete at
  this checkpoint. Command: work/hybrid_dev_fit_fast_env/Scripts/python.exe
  scripts/fit_multifactor_population_dev.py --population
  outputs/hybrid_delivery/multifactor_population_20260907_01 --output
  outputs/hybrid_delivery/multifactor_population_fit_20260907_01.
  Uses TRAIN only,4 fixed factors, symbol:technical_mode partial pooling,
  log-percent24h outcome NOT netR. Per-chain files/progress persist; each draw
  checks user02:00 deadline. Do not restart based on stale progress file;
  inspect actual process/session70007 first. No automatic parameter retries.
  Student-t log outcomes must not be exponentiated into expected gross return
  (moment does not exist); no calibrated probability or return claim.

Full capital-constrained research replay completed:
outputs/hybrid_delivery/multifactor_portfolio_20260907_02/report.json.
Original wrapper equals original27 trades and exact equity curve (identity tags
intentionally differ). T1 base24 trades,meanR-.1160,PF.6669; T2 base25 trades,
meanR-.2560,PF.3683. Full double-cost PF T1.4394,T2.2155. No profitability pass.
All scenarios preserve old reserve/risk code; longer holds change opportunities.
Explicit common original entry calendar still suppresses final6h entries, not
a valid new holding-period embargo. No independent OOS. Initial attempt01
failed before replay due rules-path location; retained. No process remains.

Independent ResearchPortfolio wrapper implemented, not yet full-history run:
inherits original reservation/cash/risk/fills, replaces only registered trend
exits, never stop/gap/daily-loss/terminal protection. Range preserved. Research
policy hash differs, so original portfolio refuses its checkpoint. T1/T2 hour
history restored explicitly; quote execution rejected. Two focused tests pass.
Next run authorized full portfolio and compare ORIGINAL wrapper with unchanged
CandidatePortfolio before trusting new candidate capital/holding outcomes.

Exit replay02 adds same-path double-cost recount with BASE denominator fixed,
policy/symbol/mode PF/payoff and overlap statistics. Seven exit tests passed;
original27/27 still match. This is NOT full stress portfolio replay. Actual
artifact: outputs/hybrid_delivery/multifactor_exit_replay_20260907_02.
No new policies or thresholds selected after observing losses.

Actual paired fixed-entry exit replay:
outputs/hybrid_delivery/multifactor_exit_replay_20260907_01.
Original27/27 exit timestamps/reasons/netR match audited A labels. Five policies
export135 paired rows, NOT135 independent trades. T1/T2 use new structural exits;
range unchanged. No portfolio risk/capital competition claim and no winner chosen.
Next: stress costs, pair diagnostics/holding overlap, full capital-constrained
research portfolio and shared MC integration. Original A/B code untouched.

Exit research pure contract added (not connected to portfolio/runtime yet):
config/hybrid_exit_research_v1.json; kquant_crypto/hybrid_exit_research.py.
T1 previous-six-hour-low breakdown at closed-hour close -> next bar exit.
T2 adds tightening-only prior-six-hour-low minus0.25 current WilderATR14.
Fixed2.5R/3R comparators solve NET target reference with BASE costs/risk.
Range unchanged. Three focused tests pass; no actual exit replay/MC claimed.
Next implement fixed-entry historical comparisons using original cash/fill
semantics and remeasure holding intervals before full portfolio/MC work.

Crypto regression after multifactor additions: actual command
work/hybrid_runtime_restore_env_20260906/Scripts/python.exe -m pytest -q
exited0,1019 passed,9 skipped,27 subtests passed in89.16s. git diff --check
exited0. This proves this test scope only, not strategy performance or full
research completion. No running fit/test process remains from this checkpoint.

dataset05 adds frozen baseline EMA50/Wilder ATR14 semantics via streaming
TrendFeatures: normalized EMA slope/distance, ATR fraction, positive-close
persistence and24h drawdown. New gap resets250h warmup; duplicate/forming bars
rejected. Original A/B code untouched. All18360 trend rows AVAILABLE; each
snapshot has15 explicit factor records. Three targeted tests passed.
No new factors added to already fitted models; original model inputs retained.
Artifact: outputs/hybrid_delivery/multifactor_dataset_20260907_05.

Saved-draw economic/group audit completed without refit:
`outputs/hybrid_delivery/multifactor_posterior_audit_20260907_01`.
Posterior hash unchanged. BTC trend has1 observation, SOL range2, ETH trend10,
SOL trend14. Group predictive intervals remain wide; no calibrated probabilities
or economic validity granted. Read full report for empirical impossible-loss
mass; zero sampled violations must not be interpreted as support proof.

Completed actual hierarchical four-factor Student-t fit at
`outputs/hybrid_delivery/multifactor_student_t_20260907_01`.
Command: work/hybrid_dev_fit_fast_env/Scripts/python.exe
scripts/fit_multifactor_entry_dev.py --output
outputs/hybrid_delivery/multifactor_student_t_20260907_01
Exit0;1078.64 seconds;4 chains x1000 posterior draws,1000 tune each.
Rhat1.0037003,bulk ESS1806.36,tail ESS1757.49,zero divergences,zero max-depth hits.
BFMI .9059-.9856. Prior/posterior predictive samples saved in posterior.nc.
Artifact integrity verified by explicit DEV_ONLY reader; runtime false.
A27 selected old-policy netR targets only, sparse range/currency coverage;
no independent OOS, mean/profit/tail validation or admission granted.
No sampler retry/retuning. Process finished; no fit remains running.
Next: economic-support and group predictive diagnostics, complete remaining
factor coverage, then preregistered structural exits and independent validation.

dataset04 additionally binds each of10 factors to formula/version/source/time/
missing status and a canonical snapshot hash. Old dataset03/model inputs retained.

Baseline02 adds training-only quintile/correlation and fixed leave-one-feature-out
diagnostics, no feature reselection. Actual predictions hash exactly matches
baseline01. Twelve focused tests pass, including evaluation-data perturbation
not changing fitted training parameters. Artifacts:
`outputs/hybrid_delivery/multifactor_baseline_20260907_02`.
Still DEV_ONLY descriptive opportunity regression, not net-R validation.

Actual four-factor Ridge DEV baseline completed:
`outputs/hybrid_delivery/multifactor_baseline_20260907_01`.
Fixed features return6h/ER24/relative volume24/relative core24; three expanding
calendar folds, training-only mean/std,24h label horizon plus24h embargo.
All inputs are authorized EXPOSED research. Ridge MSE worse than training-mean
baseline in all three folds; do not retune on these results or claim gain.
Artifact and predictions saved, no probability calibration or strategy result.
This advances partial MF2/MF3 but does not complete their factor experiments,
hierarchical fitting, source integrity tests or independent validation.

Holding-target increment: `outputs/hybrid_delivery/multifactor_holding_targets_20260907_01`
contains1434 mature conditional timestamps from27 original A trades. These
are correlated within trade, NOT1434 independent trades. Outcome compares
original realized exit with next-open sell (5bps slip,10bps fee), using frozen
BASE unit risk. Alternative is counterfactual, not another filled trade.
Dataset is DEV_ONLY exposed bar-proxy, not new T1/T2 policies or OOS evidence.
Ten focused factor/label tests passed. Next: complete factor metadata and
fold-only preprocessing/experiments; original entry/exit strategy unchanged.

2026-09-07 23:xx CST increment: dataset03 contains18360 exact-time core
cross-sections (BTC/ETH/SOL only, not whole-market breadth), with immutable
code hashes. Descriptive labels hash is unchanged from dataset02.
`outputs/hybrid_delivery/multifactor_entry_targets_20260907_01` separately
exports50 original-A candidates:27 audited mature net-R targets,23 unfilled
null targets, zero missing hourly joins. Original audit recomputed BASE risk,
fees and identity; B185 not merged. Cross-section unit suite:8 passed.
Actual output checks passed identity, timing and null-unfilled invariants.
No new fit or execution admission. MF1 remains incomplete: holding targets,
additional registered price factors and train-fold experiments remain next.
Do not confuse descriptive opportunity windows with forced holding exits.

Formal goal now verified active with the revised multifactor objective.
MF1 dataset02 has18360 feature rows and36720 descriptive opportunity labels:
6h18342 mature/18 censored;24h18288 mature/72 censored. Horizons overlap and
are not independent trades. Gross close-reference outcomes are NOT netR or
simulated executions. Three targeted leakage/gap/cutoff tests passed. Old
dataset01 and A/B evidence retained. Next: matched-time cross-sectional features
and distinct entry/holding labels; MF1 not complete, no training or gate upgrade.

Read `plan/hybrid_multifactor_dev_tasks_v1.json` in addition to the original
taskboard. MF1-MF6 are explicit authorized offline research tasks; online G3
does not block their DEV work. Preserve all original gates and A/B policies.
First dataset uses the existing authorized development loader and samples every
proven hourly close, not only A27 fills. Labels, cross-sectional factors,
entry/holding targets, experiments and actual multifactor fitting remain next.
Goal creation was attempted but rejected because the original goal is unfinished;
do not claim a new app Goal exists or complete the old one to bypass this.

## Terminal observation update: 2026-09-07

Read-only OS time check: `w32tm /query /status` exited1 with0x80070426;
`Get-Service W32Time` reports Stopped/Manual. This confirms no running Windows
Time service, NOT the sole cause of prior offsets or interval ambiguity.
Do not start/resync/change startup mode without owner approval and an impact
inventory of current services. Keep old clock sections immutable across any
approved time change. Public ticker E is native event time; documented JSON
bookTicker lacks it, and SBE access needs an API key, so neither is a silent
drop-in strict-evidence fix. No authentication or endpoint migration performed.

Quote rejection audit now explains the low strict coverage: all20662 rejected
archive quotes have source time INSIDE the receiver interval, none after upper.
Median source-minus-lower is18.3-19.2ms; receiver widths median~486ms.
They are ordering-uncertain under the frozen contract, not classified stale.
Evidence `outputs/hybrid_delivery/quote_rejections_20260907_01/report.json`,
two targeted tests pass. No rejected quote was relabeled or traded.
Full7200-second qualified coverage BTC37.86%, ETH61.24%, SOL30.89%.
Next investigate a tighter independently defensible clock contract or an
explicit receipt-time-only research branch. Merely waiting longer cannot
establish this contract's ordering for these messages. No tolerance expansion.

FINAL recovery_2h_20260907_01: COMPLETED7207.850 seconds, PID34092 absent,
39 clock segments,636 committed quotes,24 closed batches/commit observations,
zero opportunities and labels, no failure. Terminal ledger audit passed.
Evidence: `outputs/hybrid_delivery/recovery_2h_conclusion_20260907_01/report.json`
and source07 `outputs/hybrid_delivery/recovery_2h_audit_20260907_01/report.json`.
Engineering duration passed; DATA/G3 and performance did not. Mid-run funnel
confirmed63 actual decisions, all RANGE_NOT_TRIGGERED, not a dead strategy path.
Before extending observation, inspect strict-quote rejects/full-window coverage;
do not characterize zero opportunities as profitable or alter A parameters.
No observer is currently claimed running. Earlier RUNNING text is historical.

Latest development checkpoint: checkpoint_20260907_01 passed1002 tests,
9 skipped and27 subtests; isolated math, diff and protected-baseline audit
all exited0. Captured source hashes were unchanged during verification.
This supersedes checkpoint19 for the captured Crypto sources, not frontend,
market validity or exchange acceptance. Source07 two-hour observer remains
a separate fixed-source runtime; inspect PID34092 and its run, not this test
checkpoint, for liveness and data continuity. No gate is promoted.

Latest recovery increment: fixed source07 renewal_smoke_20260907_01 completed
408.190 seconds, three clock segments,29 committed valid quotes, one closed
batch and zero opportunities. Ledger audit passed; G3 false. Own child exited0.
New separate7200-second run recovery_2h_20260907_01 was launched from source07.
Receipt: `outputs/hybrid_delivery/observer_2h_launch_20260907_01/launch.json`.
Verify its actual PID and heartbeat before claiming it still runs; do not reuse
the old failed24h receipt. Terminal audit is required before24h promotion.
No original service restart, model activation or gate promotion occurred.

Latest fixed-source start/exit smoke: source_recovery_20260907_01, run
cleanup_smoke_20260907_01, requested30 seconds, elapsed39.016 seconds,
launcher42.063 seconds, exit0, no forced termination. External own-child
deadline120 seconds was configured but NOT exercised. One clock segment,
24 receipt-order rejects, zero valid consumed quotes/opportunities/labels.
This proves start and normal exit only, not renewal, failure cleanup or G3.
Evidence: `outputs/hybrid_delivery/frozen_smoke_20260907_01/acceptance.json`.
Child33356 exited; no new long-running observer is claimed. Next: same fixed
source bounded observation across two renewal boundaries, then audit before2h.

Development renewal cleanup now waits at most5 seconds for cooperative task
cancellation, then records TIMED_OUT/FAILED without granting restart. Evidence:
`outputs/hybrid_delivery/renewal_cleanup_20260907_01/report.json`;11 affected
tests passed, including a cancellation-resistant task. This bounds the renewal
wait only, not network context exits, asyncio.run shutdown, or OS scheduling.
Next: pre-context-unwind exception capture and a separate process exit deadline
before another frozen-source smoke. Source04 and original services unchanged.

Correction from raw-clock audit: the9537.531-second difference is last receipt
to TERMINAL REPORT, not a recorded exception instant. Terminal status is built
after cleanup. The last receipt used segment83 at age37.995 seconds; terminal
segment age is9575.526 seconds. No historical exception timestamp exists, so
neither the exact expired callsite nor time spent in cleanup is established.
Evidence: `outputs/hybrid_delivery/terminal_clock_scope_20260907_01/report.json`.
Development handler now captures monotonic and local time BEFORE cleanup,
explicitly not source-event time. Nine targeted tests passed. No run restarted.
This correction supersedes earlier receipt-to-failure wording below.

Diagnostic increment at approximately 14:23 Beijing: development observer now
archives bounded source traceback locations (no locals or exception-message
copying) and includes the helper in its source manifest. Eight targeted tests
passed; evidence: `outputs/hybrid_delivery/failure_locations_20260907_01/report.json`.
This is NOT a clock repair or a new observation. Source04 remains unchanged.
The old report has no traceback: bounds can fail after receive/timeout, during
renewal validation, or batch processing, so its precise call site cannot be
retrospectively established. A two-second asyncio timeout does not guarantee
the process was scheduled continuously. No OS suspend cause is established.
Next work is bounded recovery design and independent runtime-gap evidence;
do not immediately restart the identical run or widen the clock policy.

This update supersedes the previous RUNNING descriptions below.
The two-hour run completed 7209 seconds with ledger integrity verified, but
G3 remained false and natural opportunities/labels were zero.
The subsequent `fixed_source_24h_20260907_01`, also in source04, FAILED after
24708.920 seconds with `Clock segment expired or monotonic clock changed`.
Launcher27896 is absent at the latest OS check. It is not an active collector.
There were3300 committed quotes,50 closed batches and zero natural labels.
The last receipt-to-failure monotonic gap is approximately9537.531 seconds.
This establishes a processing/clock interval gap, not a proven OS sleep cause.
System power-event lookup returned no usable evidence. Do not claim clock repair.

Failure ledger audit is in the source04 restored root at
`outputs/hybrid_delivery/fixed_source_24h_failure_audit_20260907_01/report.json`.
Ledger integrity passed; continuous24h and G3 did not. Preserve all records.
Next: investigate the gap and define bounded recovery before another observation;
do not extend freshness, join runs, stop original services or modify OS power/time
settings without approval. No automatic restart was performed on this failure.

## Current recovery override: 2026-09-06

This section supersedes historical launch instructions below. Never launch the
old 72h series simply because a past paragraph names it.

- Current fixed-source run: `fixed_source_2h_20260906_02`.
- Source root: `crypto/outputs/hybrid_delivery/source_recovery_20260906_04/restored/crypto`.
- Launch receipt: `crypto/outputs/hybrid_delivery/source_recovery_20260906_04/observer_launch.json`.
- Last OS identity check matched launcher 5748 and child 22800; this is a past
  observation, not proof of future liveness. Recheck before action.
- From the development `crypto` directory, read-only probe:
  `./scripts/inspect_hybrid_observer.ps1 -LaunchReceipt outputs/hybrid_delivery/source_recovery_20260906_04/observer_launch.json`.
  It checks process birth, executable, run identity and child relationship;
  process working directory is not independently proven. No stop is requested.
- Wait for the existing 7200-second run's actual terminal state. Do not restart
  on a polling timeout or join segments to claim continuous uptime.
- After terminal state, run the snapshot audit from that fixed source root with
  its recorded isolated interpreter and a NEW audit output. The audit entry is
  `scripts/audit_hybrid_continuous_observer.py --run outputs/hybrid_regime_v1/fixed_source_2h_20260906_02 --output outputs/hybrid_delivery/<unique-audit-id>`.
  Ledger integrity alone is not the duration, data-quality or natural-label Gate.
- Advance to a separate 24h observation only after the two-hour requirements
  are actually checked. Then 72h remains a distinct requirement. Do not overwrite
  or hot-update the active source04 snapshot.

Current development recovery: source06 archive plus its model-restore repair
receipt. Checkpoint19 is 988 passed, 9 skipped, 27 subtests; later PowerShell
health-probe and checkpoint-manifest changes are not covered by that regression.
Model diagnostics remain DEV_ONLY/ABSTAIN. No warmup trace was archived; do not
repeat unchanged fitting to infer an adaptation root cause.

Local scoped task receipts T21/T31/T32/T33 are engineering evidence, not G4/G8
or exchange acceptance. T34 has a separate Testnet-integration gap; T40 external
notification/deployment acceptance still needs applicable A1 permission.
Use the existing `kquant` heartbeat; do not create another scheduler or poll each
minute with an LLM. Keep the full goal active; no Live or model gate is granted.

继续执行 `crypto/docs/HYBRID_TO_LIVE_MASTER_PLAN_V1_2.md`。

先读短版连续交付协议、`crypto/plan/hybrid_to_live_tasks.v1_2.json`、`crypto/work/hybrid_delivery/state.json` 与最近证据；核对工作区、任务锁和运行进程，接着做最高优先级可执行任务。

不重新设计计划，不重跑已验证且输入未变的全部工作，不等待我逐项指定下一步。数据/外部权限仅阻塞对应分支。按主计划自动验证、记录、继续；真实资金启用仍由用户控制，编码代理无生产下单权限。

状态缺失时仅恢复最后可核验checkpoint；不把聊天里的完成声明当证据。没有调度器存活证据，不宣称后台在运行。

## Latest Launch (2026-09-06, fixed source 04)

`outputs/hybrid_delivery/source_recovery_20260906_04/observer_launch.json`
records the new 7200-second observer, launch PID 5748, in
`source_recovery_20260906_04/restored/crypto`. It uses the rebuilt independent
runtime interpreter, not the shared collector environment. Status lives under
that restored crypto directory at
`outputs/hybrid_regime_v1/fixed_source_2h_20260906_02/status.json`.
Verify OS process/command before relying on it; no 2h/24h/72h pass is claimed.
The helper's status-only PermissionError retry was tested against an actual
Windows no-delete-share reader handle. This reproduces one failure class,
not the unknown old incident's exact IO path. Old runs remain terminal below.
Terminal report now takes priority over stale heartbeat in the control CLI.

## Previous Terminal Resume Entry (2026-09-06)

### New fixed-source two-hour check (supersedes terminal entry below)

TERMINAL UPDATE: PID 42444 is absent. The fixed-source run ended FAILED after
1140.79 seconds with PermissionError, 694 quotes, four closed batches and no
opportunities. Its old failure payload lacks a filename, so the specific IO
operation is not proven. Independent audit under the restored tree at
`outputs/hybrid_delivery/fixed_source_terminal_audit_20260906_01` passed ledger
integrity, not G3. Do not treat the historical launch paragraph as current
liveness. A new status-only bounded IO helper and sanitized filename diagnostics
are under verification in the development tree; no new long run launched.

Launch record: `outputs/hybrid_delivery/source_recovery_20260906_02/observer_launch.json`.
Launch PID 42444. Actual working directory is the restored crypto tree inside
that bundle, not the mutable repository crypto directory. Check OS command and
status under `restored/crypto/outputs/hybrid_regime_v1/fixed_source_2h_20260906_01`.
Do not start another observer: the restored tree has its own lock, so the
original checkout lock alone cannot detect this process. Source snapshot and
public rules are copied and hash checked; dependencies use existing Python312
with recorded versions, not a newly rebuilt environment. Only OS environment
variables are inherited. No model or account artifacts were copied.
Run budget 7200 seconds, no automatic retries. Two-hour acceptance remains false
until the terminal report and ledger audit prove it. The earlier 420-second
check completed three clock segments and 155 accepted quotes, no opportunities.
New checkpoint tests in this restored tree: 32 targeted tests passed; not a
claim of a new full regression. Existing scheduler and services unchanged.

Series `outputs/hybrid_regime_v1/series_72h_20260906_03` is now
`BLOCKED_NONRETRYABLE_FAILURE`, active_pid null. Manager 42976 and original
child 27840 are absent in the OS probe. Five segments are preserved. The first
ended ConnectError after 577.39 seconds with 532 qualified quotes and zero
opportunities; bounded connection retries followed. Segment 005 ended with
`ValueError: Invalid clock probe duration`; the manager correctly stopped at
907.56 seconds rather than relaxing the clock contract. Do not automatically
restart this contract failure or claim continuous observation remains active.
First-segment terminal audit is saved at
`outputs/hybrid_delivery/series_terminal_audit_20260906_03`.
Public connectivity/qualified clock observations must recover before a new
observation window; account authorization and numerical contracts remain
separate blockers. No original service was stopped and execution remains false.

## Historical Resume Entry (2026-09-06 19:46 +08:00)

- Current bounded public series: `outputs/hybrid_regime_v1/series_72h_20260906_03`.
  Manager PID 42976 and child PID 27840 were verified through Get-Process in
  this check. PIDs are observations, not durable proof of future liveness.
- Child `segment_001/status.json` at elapsed 294.37 seconds reported RUNNING,
  283 qualified quotes, 498 receipt-order-uncertain rejections, two clock
  segments and zero opportunities. No fills or mature labels were produced.
  Rejected quotes do not count as qualified execution evidence.
- Status command from crypto with the recorded Python312 interpreter:
  `scripts/control_hybrid_observer.py status --run outputs/hybrid_regime_v1/series_72h_20260906_03`.
  Also verify the actual manager/child processes before deciding to wait or
  restart. Never start a second writer based solely on a stale status file.
- Latest full checkpoint is `outputs/hybrid_delivery/checkpoint_20260906_14`:
  956 passed, 8 skipped, 27 subtests. The subsequent bounded ConnectError
  recovery change passed 23 affected tests; it is not covered by that earlier
  full checkpoint. Clock-contract and HTTP failures remain nonretryable.
- Execution and G3 remain false. Separate segments cannot establish an
  uninterrupted 72-hour interval. No new scheduler or original-service restart.

## Historical Resume Anchors (Not Current Liveness)

- Active independent public observer: `outputs/hybrid_regime_v1/continuous_24h_20260906_01`.
  Requested 86,400 seconds; PID 41956 was verified through Win32_Process after
  launch on 2026-09-06. Verify the current PID, creation time and command before
  relying on it; a saved heartbeat or launcher file is not a liveness check.
  Do not create a duplicate or modify its frozen source files while running.
- New engineering receipt: `outputs/hybrid_delivery/continuous_observer_20260906_01/receipt.json`.
  Checkpoint 11 code suites passed (938/8/27). Its baseline step failed because
  an addition touched the frozen M2 report; that addition was removed, and the
  separate `restored_baseline/audit.json` passed. Original failure remains saved.
- The continuous observer has immutable source copies, rolling clock segments,
  bounded storage and status/stop commands. It currently ends on a connection
  failure; do not claim automatic reconnection or 24/72h acceptance.

- Full regression: `outputs/hybrid_delivery/checkpoint_20260906_10/checkpoint.json`.
  929 passed, 8 skipped, 27 subtests; isolated math, diff check and baseline audit
  exited 0. Source hashes remained unchanged during this checkpoint.
- Latest rule/health targeted receipt: `outputs/hybrid_delivery/rule_health_20260906_02/evidence.json`.
- Fixed archive replay, no resampling: `outputs/hybrid_delivery/t21_archive_audit_20260906_01/evidence.json`.
- Durable synthetic stream recovery: `outputs/hybrid_delivery/t32_recovery_20260906_02/evidence.json`.
- Latest bounded quote segment: `outputs/hybrid_regime_v1/clock_segment_20260906_02/report.json`.
  80 accepted quotes, no opportunities/labels; this process ended normally.
- Current combined receipt: `outputs/hybrid_delivery/partial_checkpoint_20260906_10/partial.json`.
- Latest public rule receipt: `outputs/hybrid_delivery/public_rules_20260906_03/evidence.json`.
  Three core symbols were archived and indexed by local receipt milliseconds;
  this is not native exchange availability time or account authorization.

Run from the crypto directory with the explicit Python312 interpreter already
recorded in the receipts. `scripts/run_hybrid_delivery.py next` returns T21,
T32, T34 and T40 as dependency-ready, not acceptance-complete. Inspect their
remaining scope before adding work:

- T21: full-load independent synthetic protection evidence now exists at
  `outputs/hybrid_delivery/mc_process_load_20260906_03/result.json` (5,000 paths,
  480 parity checks); production scheduling/venue protection and formal numerical
  admission remain separate. Do not rerun merely to obtain better timings.
- T32: synthetic decoder/journal checks do not replace authorized account stream,
  manual-change reconciliation or testnet-reset evidence. A1 governs actual calls.
- T34: fixture/public-rule audits do not establish account permissions or complete
  dynamic reference-price coverage. Do not reinterpret a missing endpoint as a
  disabled exchange rule.
- T40: local HTTP/DEV metadata observations exist; actual order/protection health
  and approved external notification acceptance remain incomplete.

`scripts/run_hybrid_delivery.py prepare-live-approval` currently returns NOT_READY
with G2-G9 missing, no account/capital/expiry and live disabled. This is not a
claim all remaining engineering is finished. Keep original services unchanged;
do not create another scheduler or repeatedly ask for the already-consolidated A1.

## Continuous Observation Commands

Latest read-only audit: `outputs/hybrid_delivery/continuous_audit_20260906_01/receipt.json`.
The audit uses a separate SQLite snapshot, not the original writer. It verifies
ledger integrity and reports fill/label states separately; coverage remains
descriptive because this run has no exact bound preregistered monotonic origin.
Do not reinterpret its result as G3 or silently retrofit the active run's manifest.
For a meaningful new observation milestone, create a NEW audit output directory:
`scripts/audit_hybrid_continuous_observer.py --run outputs/hybrid_regime_v1/continuous_24h_20260906_01 --output outputs/hybrid_delivery/<new_audit_id>`.
Do not repeatedly snapshot unchanged evidence merely to show activity.

Working directory: `C:\Users\Administrator\Desktop\KQUANT-\crypto`.
The following status command was executed; STOP was separately verified to end
`continuous_stop_smoke_20260906_02` with exit 0 and state STOPPED/owner_stop.
Do not issue STOP merely to inspect a live observation.

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe' scripts/control_hybrid_observer.py status --run outputs/hybrid_regime_v1/continuous_24h_20260906_01
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe' scripts/control_hybrid_observer.py stop --run outputs/hybrid_regime_v1/continuous_24h_20260906_01
```

After a verified terminal run only, start a new independent run using a NEW
output directory and the same explicit interpreter:
`scripts/run_hybrid_continuous_observer.py --output outputs/hybrid_regime_v1/<new_run_id> --seconds 86400`.
Never reuse an old directory, fabricate fills across the downtime, or call a
collection restart continuation of uninterrupted availability. The existing
`kquant` two-hour heartbeat remains the only task scheduler; no extra scheduler
was created. Public observation is not mathematical admission or live approval.
# Recovery Checkpoint: 2026-09-06

The earlier `continuous_24h_20260906_01` run is TERMINAL FAILED after
6,949.55 seconds with ConnectionClosedError; PID 41956 is absent. Preserve it.
Its final ledger audit is `outputs/hybrid_delivery/continuous_terminal_audit_20260906_01`:
9,558 quotes, 23 closed batches, no opportunities or labels, integrity passed,
G3 false. Original logs did not retain WebSocket close codes; a specific network
root cause is unknown, not asserted to be server policy or a clock fault.

New active run: `outputs/hybrid_regime_v1/continuous_72h_20260906_01`, launched
as hidden independent PID 32672 with Python312 for 259,200 seconds. Verify OS
liveness and status on resumption; the PID here is historical launch evidence.
Use `scripts/control_hybrid_observer.py status --run outputs/hybrid_regime_v1/continuous_72h_20260906_01`.
Use the same command with `stop` only when stopping this specific run is needed.
No automatic reconnection has been implemented: failure ends a run and censors
unknown outcomes. Never join the old/new runs into uninterrupted availability.

New runner binds monotonic start/end before observation begins. Its manifest,
registration receipt and every committed event bind the window hash. Full planned
duration, including bootstrap and unobserved time, is the coverage denominator.
Legacy manifests are not retrofitted. Connection failures now record protocol
close codes without arbitrary remote reasons or URLs.

Actual short-run verification: `continuous_window_smoke_20260906_01`, exit 0,
53 qualified quotes; `outputs/hybrid_delivery/continuous_window_audit_20260906_01`
checks its 45-second full denominator. Cleanup made wall duration 54.44 seconds;
it is not 72-hour or label-lifecycle acceptance.
Full checkpoint `outputs/hybrid_delivery/checkpoint_20260906_12/checkpoint.json`:
948 passed, 8 skipped, 27 subtests; isolated math, diff and protected baseline
audit exit 0; tested source hashes unchanged. No model or trading gate granted.
# Current Online State: Repaired Series Relaunched, 2026-09-06

Current series: `outputs/hybrid_regime_v1/series_72h_20260906_03`, manager launch
PID 42976, 259,200-second total budget, max 12 segments. Recheck OS process and
child liveness on resume; no status JSON proves liveness. Use the existing
control CLI status/stop with this series path. Prior series below is terminal.
Post-fix real smoke `series_smoke_20260906_04` exited 0 with 147 qualified quotes,
owned child STOPPED at budget; audit `outputs/hybrid_delivery/series_smoke_audit_20260906_04`
passed. No opportunities or labels; no long-run or G3 acceptance inferred.
Latest regression `outputs/hybrid_delivery/checkpoint_20260906_14`: 956 passed,
8 skipped, 27 subtests; isolated math, diff and baseline checks passed.
Subsequent narrow transport repair: series_02 correctly ended on ConnectError
after 955 seconds, 819 quotes and no opportunities. Its manager source was archived
before edits. Both terminal ConnectError and ConnectionClosedError now permit a
new segment on unchanged public endpoints, under the same 12-segment/duration cap.
Clock ValueError and HTTPStatusError remain nonretryable. Targeted regression
after this change: 23 passed; the full checkpoint above predates this narrow change.
This does not authorize endpoint switching, time relaxation or uninterrupted-uptime claims.

Manager PID 42676 and child 27120 are both absent. The series heartbeat remains
stale RUNNING because an unhandled Windows PermissionError interrupted its atomic
status replacement. Authoritative traceback:
`outputs/hybrid_delivery/series_launch_20260906_01/launch.stderr.log`.
The child subsequently ended FAILED on clock probe duration after 1,504.38 seconds.
Final child ledger audit: `outputs/hybrid_delivery/series_terminal_audit_20260906_01`:
690 quotes, 5 closed batches, zero opportunities, integrity passed; G3 false.
Do not restart based on the stale JSON or claim either process is still alive.

The manager now retries transient PermissionError at most five writes with bounded
backoff. Persistent status IO failure requests its own child's STOP, waits 45s,
and terminates only its retained child handle if necessary; a separate terminal
`manager_failure.json` and stdout record the failure. Control prioritizes that
failure over stale heartbeat. The failed source was hash-verified and archived
as `series_72h_20260906_01/manager_source_before_io_fix.py` before edits.
This fix is engineering work, not continuous-observation acceptance. No new long
observer was launched during the repair. Existing scheduler and original services
remain unchanged. Historical restart details follow.

Public clock recheck passed five probes (1.851, 0.446, 0.706, 0.447, 0.453 seconds).
`series_smoke_20260906_03` exited 0 with 122 qualified quotes, child STOPPED on the
manager's duration stop, no failure, and independent audit passed at
`outputs/hybrid_delivery/series_smoke_audit_20260906_03`. Actual manager duration
was 129.04 seconds including cleanup for a 120-second budget.
New bounded series: `outputs/hybrid_regime_v1/series_72h_20260906_01`, manager
launch PID 42676, total budget 259,200 seconds and maximum 12 independent segments.
Probe OS liveness and current child status before claiming it is running.
Use `scripts/control_hybrid_observer.py status --run outputs/hybrid_regime_v1/series_72h_20260906_01`;
use `stop` for this owned series only when needed. Child paths/PIDs are in status.json.
No uninterrupted uptime, G3, natural labels or exchange fills are inferred from
restarting. Previous failures below remain historical evidence, not current status.

The previously launched PID 32672 is now absent. Run
`continuous_72h_20260906_01` ended FAILED after 11,401.82 seconds with
ConnectionClosedError and no received/sent close frame. It contains 5,731
qualified quotes, 38 closed batches, zero opportunities/fills/labels. Do not
describe that run as still active or join it to prior uptime.

Implemented bounded recovery manager `scripts/run_hybrid_observation_series.py`:
new independent ledger per verified terminal connection failure, exponential
backoff, at most 12 segments, fixed total duration, separate single-owner lock,
no inherited API secrets, and no uninterrupted-72h or G3 claim. Unknown exits
and contract failures stop retries. STOP propagates only to the owned child;
after a 45-second stop timeout, only its retained process handle is terminated,
recorded as failure, never as fabricated liquidation. This is not approved
continuous service or label-lifecycle acceptance.

Actual tests: `series_smoke_20260906_01` failed clock probe duration validation;
the initial manager misclassified deadline completion despite child failure.
That defect was corrected without editing old artifacts. The next real smoke,
`series_smoke_20260906_02`, correctly returned exit 1 / BLOCKED_NONRETRYABLE_FAILURE
for ConnectError before clock calibration. No observation process remains from
these smoke runs. DNS resolved; a separate public /api/v3/time request returned
200 in 8.855 seconds. This is not proof of qualified clock-probe latency.

Full regression evidence: `outputs/hybrid_delivery/checkpoint_20260906_13`:
954 passed, 8 skipped, 27 subtests; isolated math, diff check and original
baseline audit exit 0. No A/B, clock tolerance or execution gate was changed.

Recovery entry, only after current process ownership is rechecked, from crypto
using the recorded Python312 interpreter (always a NEW output directory):
`scripts/run_hybrid_observation_series.py --output outputs/hybrid_regime_v1/<new_series> --seconds 259200 --max-segments 12`.
Status/stop: `scripts/control_hybrid_observer.py status --run outputs/hybrid_regime_v1/<new_series>`
or `stop` for that owned series. Existing two-hour scheduler is unchanged.
Do not repeatedly retry a clock contract error or label a manager's mere exit
as successful data collection. All original market and protection services stay untouched.
