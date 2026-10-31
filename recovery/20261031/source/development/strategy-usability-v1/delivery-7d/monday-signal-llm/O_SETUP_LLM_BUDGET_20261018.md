# O-SETUP: limited research LLM budget proposal

Status: PROPOSED, not accepted. The exact JSON configuration is
`config/research_ai.json`; its file SHA-256 will be supplied with the decision.

Endpoint: https://api.openai.com/v1. Primary: gpt-5.6-sol, medium.
Complex cases may explicitly request gpt-6-astra; no automatic model substitution.
Model access and returned model identity must be verified using the local key.

Shared limit: USD5 per Asia/Shanghai calendar day, across both models and tests.
Whole-task limit: USD1, including all tool rounds. Initial capability acceptance
tests together have an additional USD1 total cap, included in the daily limit.
Valid only until 2026-10-23T14:30:22Z. Unused allowance does not carry over.
Use the existing signal_copilot budget ledger; no extra database or account.
Unknown provider usage retains its reservation. No automatic retry after an
uncertain request. One in-flight task globally for this initial bounded rollout.

Before production release, paid capability tests use explicitly TEST_ONLY
business input, yet record genuine API usage in the shared budget. They do not
count as natural signals, historical delivery, or strategy returns.
This fee choice allows those capability tests and authorizes the cost limits;
deployment into the live observation service still needs the final exact O-LAUNCH.

Only supplied event evidence, saved contract data, deterministic math/cost
diagnostics and existing event-source documents may be provided to the model.
No credential, order, account balance, or private holdings are supplied.
The model cannot change strategy, source qualification, approval or any ledger.
Delayed, revised, expired or stale-quote results cannot become current signals.

Reference prices checked on official documentation on 2026-10-18:
- https://developers.openai.com/api/docs/models/gpt-5.6-sol
- https://developers.openai.com/api/docs/models/gpt-6-astra
- https://developers.openai.com/api/docs/guides/function-calling

Private setup (no API call): run the adjacent `configure_llm_key.py` using the
existing root `.venv\Scripts\python.exe`. Do not send the key in chat.
