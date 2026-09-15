# Hybrid V1.1 Blockers and Freeze Register

## RX07 independent clock diagnosis, 2026-09-09

Evidence: `outputs/hybrid_delivery/rx07_clock_probe_20260909_01/clock_probes.json`
and `independent_time_check.json`. Five advancing native millisecond Binance
serverTime responses place the remote clock approximately 326.7 seconds ahead
of local UTC. Read-only `w32tm /stripchart` independently returned +326.689 to
+326.787 seconds from time.windows.com and +326.689 to +326.982 seconds from
time.cloudflare.com (three samples each, both exit 0). W32Time is Stopped/Manual.
This supports local wall-clock offset, not a five-minute bar offset, seconds/
milliseconds confusion or a stationary cached response. The reason W32Time
stopped and any host/hypervisor clock interference remain unproven.

Owner: runtime/time integration owner; system maintenance approval: user.
Proposed maintenance, NOT executed:

1. Inventory current listeners, processes, writers and monotonic/UTC anchors;
   preserve their raw logs and establish a maintenance boundary. Do not stop
   existing collectors without separate confirmation of exact process scope.
2. With administrator approval, inspect `w32tm /query /configuration`; retain
   existing domain/time-provider policy. Start W32Time and request
   `w32tm /resync /rediscover` only when compatible with that configuration.
   Do not overwrite NTP policy or silently enable automatic startup.
3. A roughly +327-second adjustment can invalidate sessions, expiry decisions,
   freshness checks and old monotonic/UTC mappings. Mark affected observation
   segments discontinuous. Existing observers must fail closed across the step;
   resume strict evidence only with a newly verified clock segment and warmup.
4. Repeat Binance and both independent probes, verify original clock bounds,
   and capture actual closed 5m/1H boundaries. No widening freshness, no repair
   of old quotes and no synthesized source event timestamps.

Pending user approval blocks OS maintenance, not offline research or raw
receive-only archival. Existing provider-aligned research segments retain their
own explicit uncertainty contract; this diagnosis does not upgrade any old
label to strict QUOTE_AWARE or prove continuous receiver operation.

## Current parallel authorization, 2026-09-05

This section supersedes the blanket development-training restrictions in the
dated investigation entries below. Existing runs, prior configs and historical
labels are not rewritten. Latest evidence: `HYBRID_M2_DELIVERY_V1_1.md`.

| Issue | Owner / evidence | Current resolution | Remaining blocked scope |
| --- | --- | --- | --- |
| B-CLOCK | M2 integration owner; raw E/1000 vs Python receipt, repeated public time probes, W32Time read-only status | New isolated receiver-clock segment, raw local UTC retained, provider-aligned interval anchored to a high-resolution monotonic clock; never substitutes source E | Old conflicting records remain invalid; strict fills with uncertain ordering remain rejected. OS synchronization cause/maintenance is separate and unapproved |
| B-QUOTE | M2 integration owner; official payload schemas and actual captures | Native ticker E and b/B/a/A preserved with 1-second sampling limitation | Old missing-E/quantity records cannot be upgraded; complete order-book path and exchange-fill claims unavailable |
| B-10R | Quant contract owner plus user; BASE vs legacy denominator audit | Preserve original formulas and report separately | Performance PASS and translated risk limits; NOT DEV_ONLY fitting |
| B-EXPOSURE | Data governance owner; authorized M2 manifest and old partitions | All 27 selected A labels marked EXPOSED_RESEARCH; retain old 12/5/10 partition metadata | Independent OOS, calibration and generalization claims; NOT the authorized development fit |
| B-PRIOR-MC | Math owner plus user; new `config/hybrid_dev_fit_v1.json` and immutable run preregistration | One-feature Student-t development priors/seed/diagnostics preregistered; M4 stays synthetic | Formal Bayesian admission, MC selection/size policy and real-time consumers remain unapproved |
| B-ENV | Runtime owner; explicit-root scripts, preserved slow environment and `work/hybrid_dev_fit_fast_env` | Separate compiled NumPyro CPU environment produced run03; shared collector dependencies unchanged | Unbound old editable paths still unsafe; use documented interpreter and cwd |

First real development fit completed in `dev_fit_20260905_03`: 4x1500 posterior
draws and immutable prior/predictive checks. The preregistered sampler checks
pass; 341/6000 retained trajectories reach the default tree-step cap and remain
a numerical warning. `TRAINED_DEV_ONLY` does not remove B-EXPOSURE, B-10R,
online label coverage, calibration or production-admission restrictions.

The online clock segment is not a migration of the original collector. No
system-time change, collector restart or production consumer activation is
authorized by this register. Actual fit success/failure and diagnostics must be
read from the current delivery report, not inferred from development permission.

## M2 follow-up update, 2026-09-05

Authoritative latest scope/evidence: `HYBRID_M2_DELIVERY_V1_1.md`, sections A-H.
The older register below is retained as investigation history, not a claim that
the new observer or synthetic preflight work remains unimplemented.

| Issue | Owner / evidence | Resolution | Dependent scope only |
| --- | --- | --- | --- |
| B-CLOCK | Data-time owner; 88 final-version live ticker samples and three public serverTime probes | Freeze an observer-specific UTC/monotonic mapping with uncertainty and raw-clock retention, or explicitly coordinate system-clock maintenance | Strict quote fills blocked: local clock trails provider by about 320 seconds. No system time changed; audits/storage continue |
| B-QUOTE | M2 data owner; 1000 original candidate quote records omit event time and sizes | New public ticker capture preserves E,b/B,a/A; do not repair old records with fabricated fields | Old records cannot become QUOTE_AWARE labels; new observations still blocked by B-CLOCK |
| B-10R | Quant contract owner plus user; old backtest/validation vs candidate_metrics | Confirm cross-system denominator and chronological ordering without rewriting history | Performance equivalence and translated risk lines; not ingestion |
| B-EXPOSURE | Data governance owner; old loader and run manifests | Preserve EXPOSED classification; preregister a new prospective window | Independent OOS claims; not development audit |
| B-PRIOR-MC | Math contract owner plus user; specification/config null parameters | Approve targets, priors, block/window/allocation and diagnostics; synthetic preflight is not approval | DEV_ONLY fitting and mathematical selection, not fixture testing |
| B-ENV | Runtime owner; editable-path audit | Explicit Python312/Crypto cwd/root-bound scripts; isolated no-pip math venv | Unbound console launches; no shared collector environment change |

Independent SQLite event/checkpoint/immutable-label transaction and rollback tests
now exist. Production 24/7 writer/resource/crash qualification is NOT implied.
There are zero new eligible quote-aware outcomes and no trained/calibrated model.
No blocker authorizes relaxing an original Gate.

## Earlier M0/M1 register

2026-09-05. Owner: current integration task for investigation; user approval is
required for unresolved original-policy interpretations. No test profit chooses
an unresolved value. First M0/M1 delivery can complete with these dependencies
explicitly blocked; this is not an M1 full release or model-admission certificate.

| ID | Reverified finding | Blocked scope | Resolution / owner |
| --- | --- | --- | --- |
| B-10R | Old 10R code found: cost-adjusted actual entry minus stop; caller/asset-order cumulative R. Dual uses signal BASE net loss and chronological exits. Not equivalent | Complete performance PASS, any translated R risk line | Present both formulas; user confirms authoritative cross-system metric, retain old reports |
| B-EXPOSURE | Existing history exposed; old loader materialized entire frozen files before evaluation date restriction | Independent OOS advantage claim | New prospective frozen window; no retrospective relabel as unseen |
| B-PROVENANCE | A/B module hashes and complete core traces reproduced; old A/B metadata lacks CLI hash | Claim of complete original executable/environment binding | Record limitation; bind all future code/CLI/dependencies, do not backfill old metadata |
| B-BASELINE-INTEGRATION | Existing A/B golden trace PASS; no Hybrid runtime plugin exists | BASELINE_COMPATIBILITY_PASS for OFF/SHADOW plugin | M2/M5 exact per-bar OFF/SHADOW comparison, unchanged baseline |
| B-TIME-RUNTIME | Offline strict post-commit tests pass; actual worker timeout/queue resources unmeasured | Runtime entry admission | M5 bounded resource tests and measured expiry/queue budget |
| B-TRANSACTION | Synthetic uniqueness, CAS, rollback, partial fill and recovery pass; no full position/exit ledger, process lease or latest registry binding | Production hybrid writer | M5 isolated schema/migrations, fill hard-risk checks and process crash drill |
| B-PRIOR-LABEL | Family/targets defined, prior scales/nu, reference quantity, population/overlap policy and diagnostics not approved; no prior-predictive simulation | Bayesian training/admission | M2 labels; M3 preregistration plus prior checks, no held-out tuning |
| B-MC | Daily/HWM/6h targets and numerical definitions frozen; window, synchronized block length, seed, allocation, stopping budget and probability cutoffs unset | MC gate or position shrinking | M4 joint numerical/risk policy freeze and path tests |
| B-LLM | No provider, authorized sources, paid budget or freshness rules chosen | Paid LLM/event-based admission | M6 explicit approval; offline fixtures only until then |
| B-ENV | Python editable discovery from an unbound script resolves old Desktop/KQUANT-CRYPTO; crypto-cwd python -m and explicit-root candidate CLI resolve this repo | New unbound launch scripts or bare installed console entry | Pin interpreter/workdir/module origin; separate future environment; do not alter collector environment |

Resolved investigation items: parent directory rules checked absent; current
writer lease inspected read-only; old source hashes matched; data manifest/file
hashes checked; actual development replay identical; three-way identity and time
contract synthetic evidence available. No old lease, schema or source changed.

## Frozen Versus Proposed

Frozen for offline M1: three Spot symbols, original A/B/cost/risk/protection
unchanged; separated identities; strict later-than-commit fills; original daily
baseline and HWM references; p_win/p_edge/q05_mu distinction; one-sided exact
binomial method; linear quantiles and fractional-tail ES; source-separated labels.
Evidence: user V1.1/V2 sources and actual tests. Approval scope: this M0/M1 request.

Proposed only: Student-t prior settings, <=8 actual feature list/transforms,
reference sizing, MC5,000/size grid/allocation, thresholds and worker budgets.
`config/hybrid_contract_v1_1.json` leaves approval-dependent values null and every
activation flag false. Its file hash is in the final inventory. Neither a null
field nor a synthetic successful result is authority to change an execution Gate.
