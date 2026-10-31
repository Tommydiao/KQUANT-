# Official API Contract, 2026-10-31

These are public documentation facts, not proof of this account's model access.

- Endpoint: `https://api.openai.com/v1/responses`; Sol `gpt-6.1-sol`, Astra `gpt-6-astra`, explicit medium reasoning. Function calling uses Responses. No fallback model or hosted paid tools.
- Standard short-context token rates per million: Sol input2/cached0.1/cache-write2.5/output10 USD; Astra10/1/12.5/50 USD. Requests explicitly select `service_tier=default`; an unexpected returned model/tier retains an unknown-cost reservation. Usage-based totals are not provider invoices.
- Output token usage includes reasoning tokens, so reasoning details are not charged again. Encrypted reasoning response items needed for stateless continuation are kept only in memory; no reasoning content is written to evidence.
- Local bounded policy remains three responses and four tool executions (the earlier four-call bound is stricter than the new six-call ceiling), one concurrent paid task, no automatic retry. Unknown fees/usage stay unknown.
- The new direct instruction authorizes aggregateUSD5 and per-taskUSD1 through2026-11-01T16:00:00Z for isolated real API tests only. It does not renew minute methods, start production or renew routine paid AI use.

Fetched official references:

1. https://developers.openai.com/api/docs/models/gpt-6.1-sol
2. https://developers.openai.com/api/docs/models/gpt-6-astra
3. https://developers.openai.com/api/docs/pricing
4. https://developers.openai.com/api/docs/guides/function-calling
5. https://developers.openai.com/api/docs/guides/reasoning

Installed implementation uses the existing requests HTTP adapter, not a new SDK dependency. Requests and runtime versions are recorded separately. No dependency upgrade is implied.
