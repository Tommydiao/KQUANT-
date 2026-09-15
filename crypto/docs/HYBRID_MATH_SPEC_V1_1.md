# Hybrid Mathematics Specification V1.1

Status: M1 design, NOT model activation. Owner: integration task. No training,
paid model request, real forecast or MC path run has been performed by this spec.

## Frozen Targets

Source: Hybrid V1.1 sections 6.2-6.6. Signals and A/B thresholds remain unchanged.
The proposed first Bayesian research family is the non-dynamic hierarchical
Student-t regression: R_j ~ StudentT(nu, mu_j, sigma_mode), nu>2;
mu_j=alpha_mode+u_symbol,mode+beta_mode*x_j;
u_symbol,mode ~ Normal(0,tau_mode^2). No AR(1) in the first model.

- p_win=P(R_new>0|x,D), a posterior predictive trade outcome probability.
- p_edge=P(E[R_new|x,theta]>0|D), posterior credibility of positive mean edge.
- q05_mu is the fifth percentile of posterior conditional means, NOT the fifth
  percentile of new trade returns.
- mu_pred is expected new net R; predictive_quantiles refer to the new outcome.

At most eight preregistered technical features; transforms fitted on authorized
training data only. Missing mode-inapplicable fields retain masks. Events are
post-technical-signal additions for a later independently registered experiment.
Old fixed-likelihood Bayesian state probabilities are not this fitted posterior.

Labels distinguish actual executed virtual trades, counterfactual single-signal
labels and termination liquidations. Only fully observed strategy exits mature.
Missing future coverage is censored/unavailable, never zero. One economic signal
cannot count twice through actual and counterfactual rows. Label execution policy
must match the latency experiment. Overlapping multi-asset labels need dependency
groups and a predeclared sampling/likelihood-dependence assessment.

## Cost and Risk Unit

For signal close C, stop S, target T, fee f and adverse execution proxy s:
E=C(1+s); Xs=S(1-s); Xt=T(1-s);
Lnet=E-Xs+f(E+Xs); Gnet=Xt-E-f(E+Xt).
Planned net RR=Gnet/Lnet. Actual net R=net money PnL/(filled quantity * frozen
signal-time BASE Lnet). Reject nonfinite or nonpositive denominator.
Pressure sizing uses pressure projected losses, without enlarging BASE R.
Observed bid/ask already represents spread; extra slippage is not a second spread.

## Monte Carlo Risk Meaning

Research horizon: six hours, matching longest original trend holding time;
range maximum is three hours. Paths advance future UTC time and preserve existing
positions, pending intents, protection prices, remaining duration, fees and exits.
No imagined future signals, news or recursive models. BTC/ETH/SOL blocks must be
sampled together from consecutive legal five-minute OHLC history. OHLC reconstruction
is a proxy with unknown intrabar cross-asset ordering, not executable quote evidence.

V=cash+sum(quantity*liquidation_mark-estimated_exit_cost).
Daily loss line=V_day*(1-0.01). Remaining distance=max(0,V_now-daily_loss_line).
Incremental MDD uses max(V_now, subsequent path peaks); cumulative HWM drawdown
uses max(H_now, subsequent path peaks). Terminal loss=(V_now-V_terminal)/V_now.
Never reset V_day to V_now per evaluation. `RiskLines` tests the distinct references:
10,000 day start and 9,910 current leaves only 10 to the 9,900 loss line.
Budget distance is not interchangeable with permitted new-position risk.

At midnight retain old pending exits and first evaluate old-day risk. New day
baseline needs a valid new opening mark; absence is DAY_BASELINE_PENDING and blocks
new risk. Unknown held-symbol valuations cannot become complete equity snapshots.

Report historical_bootstrap_risk, current_state_sensitivity and stress_risk apart.
Stress scenarios have no inferred occurrence probability. Current-state conditioning
is unproven until separately validated. No risk minimum is selected across windows.

## Numerical Contract To Validate

Offline design starting point: 5,000 independently drawn synchronized paths;
size grid {0,0.25,0.5,1} using common random paths. One-sided exact binomial
upper bound is the proposed numerical method; k=0 must have a positive upper
bound and k=N gives 1. Confidence allocation across size comparisons and any
additional sampling must be frozen before use. This bound controls sampling
computation, not market/model calibration. No repeated seeds until success.

ES95 definition: average worst 5% probability mass of terminal losses, using
floor(N*0.05) full observations plus the remaining fractional observation weight.
Quantile interpolation convention, path count sensitivity, block/window selection,
confidence allocation and actual timing budgets still require synthetic tests.

## Explicit Unfrozen Fields

Prior scales; nu prior; reference quantity; label selection policy; dependence
diagnostics; Rhat/ESS/divergence limits; support-mismatch tolerances; calibration
and group sample thresholds; model freshness; q05_mu admission approval; MC block
length/window/seed/error allocation; runtime resource limits; original 10R basis.
No concrete number for these may be inferred from test-set profits. These items
block the dependent model/admission Gate, not unrelated offline contract tests.

## M1 Numerical Evidence Update

`hybrid_numerical_contract.py` implements exact one-sided binomial inversion,
linear empirical quantiles at (n-1)*p and fractional-tail ES. Actual synthetic
tests cover zero/all exceedances, 245/5000 (4.9%) whose upper bound exceeds 5%,
enumerated binomial coverage, finite inputs, separate predictive/mean posterior
fixtures, and a 12-comparison conservative allocation. No scipy installation or
shared-environment change was needed. These tests passed in the 46-test contract
run; this is NOT an actual Monte Carlo run or calibrated model.

Frozen mathematical definitions: exact-binomial upper-bound method, linear
quantile convention and fractional ES mass. The 12-way allocation and 5,000 paths
are test/design examples until window, block length, comparisons and stopping
budget are jointly approved. Numerical bounds quantify simulation sampling only.
There has been no prior-predictive simulation; priors are deliberately null and
model fitting remains blocked. Do not label posterior fixture arithmetic as
Bayesian training or claim that numerical tests freeze runtime performance.

The original 10R implementation has now been located, but transfer equivalence
is unresolved; see the baseline audit for the denominator/order difference.

MODEL_STATUS=NOT_TRAINED. MATHEMATICAL_FILTERING_ENABLED=false.
