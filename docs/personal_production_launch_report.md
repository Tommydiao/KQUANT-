# KQUANT Personal Production Launch Report

Generated: 2026-07-24T00:39:52.326830+00:00
Strategy: `swing_long_v1.1.0`
Decision: **NO_GO**

## Required Answers

1. Is KQUANT stable? Not yet proven for production; review failed gates.
2. Is data trustworthy? Only within the recorded clean forward days.
3. Is there out-of-sample positive expectancy? Not established.
4. Did execution follow the plan? No paper execution record is available.
5. Did KQUANT reduce user mistakes? Not established until sufficient Decision Ledger evidence exists.
6. Which losses are normal strategy losses? Use the Ledger error_owner classification.
7. Which losses are user violations? Use the Ledger user_* classifications.
8. Continue small-capital operation? No. Continue paper-observed work only.
9. Increase size? No. Size expansion is outside this report and requires a later evidence review.
10. Single most important next objective: close the highest-priority failed gate without changing a frozen strategy.

## Gate Results

- FAIL `frozen_strategy`: Strategy version is frozen with a validation manifest.
- FAIL `historical_sample_count`: At least 100 completed historical samples are required.
- FAIL `out_of_sample_average_r`: Historical/out-of-sample average R must be positive.
- FAIL `profit_factor`: Historical/out-of-sample Profit Factor must exceed 1.
- FAIL `conservative_costs`: Conservative execution-cost result must remain positive.
- FAIL `forward_market_days`: At least 15 complete forward observation or simulation days are required.
- FAIL `forward_traceability`: Every forward candidate must be traceable.
- PASS `forward_data_incidents`: No material forward data incident is allowed.
- FAIL `paper_execution`: At least one completed simulated position must be recorded before execution comparison.
- FAIL `user_discipline`: Manual stop/size discipline must be reviewed and confirmed.
- PASS `security_boundary`: Secrets must remain private and no execution route may exist.

KQUANT remains a read-only research and manual-decision tool. This report never enables broker access or automatic execution.
