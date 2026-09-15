# Hybrid Experiment Protocol V1.1

Status: research design; execution of model arms not enabled by this document.
Owner: integration task. Scope: BTC/ETH/SOL Spot only, original A/B parameters.

Base reference: saved dev_A_base_v4 and dev_B_base_v4; saved selection says both
failed and A is an engineering reference. Never present A as a profitable winner.
All source hashes and run metadata must match before any compatibility claim.
No v4 report may be overwritten; bug corrections require a new explicit run.

Existing frozen historical calendar is conservatively EXPOSED_RESEARCH. The
sealed final portion remains unopened. Hashing a file for integrity is not
permission to consume its market rows for training or test selection. No new
date split restores independence to already exposed market outcomes.

Plan exactly eight attribution arms, not a search over new A/B thresholds:
T, T_latency, T+B, T+M, T+B+M, T+B+M+L, T_exposure_control, Cash.
T preserves baseline behavior. T_latency shares delayed execution policy with
mathematical arms. Exposure-control multiplier must be fixed on authorized
development data before evaluation; no hindsight matching of actual exposure.
Cash is a reference, not evidence of forecasting success.

One immutable dataset/policy/artifact bundle per preregistered run. BASE,
fixed-trade recosting and complete stress replay are separate scenarios for each
eligible arm. M0/M1 authorizes only read-only audit and synthetic tests: zero
model-arm market runs, zero training runs and zero paid LLM calls in this stage.
Any additional model/window/seed search needs a separately recorded budget.

Future chronological development, calibration and evaluation intervals must be
registered before reading labels. Purge actual label information intervals;
embargo at least maximum six-hour holding plus registered processing delay.
Cross-symbol same-UTC-time rows share partitions. Matured labels must be available
before model_training_cutoff; fitted transforms and artifact availability are
tracked separately. No online refit during a frozen run.

Counterfactual labels and independent virtual accounts have different cash,
cooldown and opportunity paths. Record rejected and expired opportunities, do
not manufacture a common tradable set. Report acceptance, duration, exposure,
turnover, latency and cost alongside returns.

Independent performance evidence must come from an actually untouched authorized
interval or new forward observations after policy/artifact freeze. Today's LLM
knowledge of old events disqualifies historical LLM results as strict PIT evidence.
No future sample, profitability or model benefit is promised by this protocol.
