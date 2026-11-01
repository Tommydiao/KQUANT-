# Real LLM capability closeout, November 1, 2026

Scope: existing authorized isolated real OpenAI API acceptance. Business inputs
are TEST_ONLY, API responses and costs are real. No natural Signal, production
startup, new approval, strategy change or renewed permission is claimed.

## Actual results

| Task | Returned model | Result | Seconds | Usage-priced USD |
| --- | --- | --- | ---: | ---: |
| Sol math revision 1 | gpt-6.1-sol | FAILED / REQUEST_ROUND_LIMIT | 10.688 | 0.0063991 |
| Sol math revision 2 | gpt-6.1-sol | COMPLETED | 9.125 | 0.0088058 |
| Astra math revision 1 | gpt-6-astra | COMPLETED | 8.312 | 0.0454175 |

Total USD0.0606224, including the failed task. This is calculated from provider
usage and the documented token rates, not an invoice or future cost guarantee.
All three budget reservations returned SETTLED, reservation_retained=false.
No automatic retry was made. The explicit Sol repair revision used the same
event candidate identity, so shared per-candidate/task and aggregate budgets
remain enforced rather than being reset for another event.

Both successful tasks completed three Responses rounds on the official endpoint
with requested/returned model identity matching. They executed
compute_price_components and read_event_evidence, then returned the structured
support/opposition references, missing inputs and review reason codes.
For the supplied test OHLC (10,12,9,11), the local read-only tool produced
M=1/3 and Q=2/3. These numbers came from code, not invented market observations.
Response metadata retains request IDs, model, usage, status, elapsed time and
tool call IDs/results. It does not retain keys or internal reasoning content.
Results remain REVALIDATION_REQUIRED, qualified_signal=false, and do not renew
BBO freshness. Unknown contract/cost/source facts remain unknown.

## Repairs supported by actual evidence

1. The saved DPAPI file existed, but inherited PSModulePath caused Windows
   PowerShell to fail locally: CommandNotFoundException /
   CouldNotAutoloadMatchingModule. A bounded diagnostic that emitted only an
   exception type/error ID and a nonempty boolean succeeded for the same file
   after removing that inherited environment variable. No secret was output.
   The isolated credential loader now follows the existing configurator's
   module-path hygiene. It still uses the current user and fails closed.
2. The first Sol task spent all three rounds requesting tools, leaving no final
   structured result. The client now reserves its last existing round for
   tool_choice=none. No round/token/timeout/monetary ceiling was increased.
3. The capability runner distinguishes local MISSING_LOCAL_KEY (no provider
   request) from failed remote probes. Unchanged-key remote failures still do
   not retry. Explicit bounded input revisions allow a documented repaired
   test while preserving shared candidate budget; repeated same revision stays
   idempotent.

Files changed only under weekend-20261031:
- patches/kquant/options_llm_credentials.py
- patches/kquant/options_research_ai.py
- run_real_capability.py
- test_llm_local_loader.py
- test_weekend_ai.py

Affected regression: 40 passed, 1 dependency deprecation warning, 10.71s.
`evidence/llm-final-round-20261101.xml` includes final-round and loader regressions
plus existing budget, worker, expiry, model and authenticated-route cases.

## Raw evidence

- `evidence/real-sol-math-20261101T085522466663Z.json`: local loader failure;
  top-level MODEL_ACCESS_NOT_VERIFIED was not a provider/model rejection.
- `evidence/real-sol-math-20261101T085639221768Z.json`: first real paid failure.
- `evidence/real-sol-math-20261101T085741558838Z.json`: repaired Sol completion.
- `evidence/real-astra-math-20261101T085808676789Z.json`: Astra completion.

The existing signal_copilot budget tables were used for preallocation/settlement
under the real test authorization. No database was copied, rebuilt or migrated;
no strategy evaluation, manual position or approved runtime payload was changed.

## Remaining boundary

The original aggregate USD5 / complete-task USD1 isolated authorization expires
2026-11-01T16:00:00Z. This success does not approve routine production spending,
new publication or a source-method renewal. Future production operation still
requires accurate consolidated acceptance. No real-market event was sent to a
model in this acceptance. Actual webpage display of these real responses and
an integrated frozen release are not established by this CLI evidence.

Queue performance remains FAIL, as does the historical seven-day verdict.
All invoked processes finished. No persistent AI worker or service was started.
