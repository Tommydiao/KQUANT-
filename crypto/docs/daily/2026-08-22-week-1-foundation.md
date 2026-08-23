# Week 1 Foundation Report

## 1. Goal and completion

The independent `KQUANT-CRYPTO` project was created with its own port,
database, environment variables, package namespace and output/data paths.
The deterministic EVAL Agent, local email/password session skeleton and
notification skeleton are implemented. Provider adapters remain disabled.

## 2. Code, schema and API

- `kquant_crypto/config.py`: isolated settings and provider flags.
- `kquant_crypto/db/migrations.py`: ordered migrations, checksums,
  fingerprints and audit tables.
- `evaluation_models.py`, `evaluation_policy.py`, `evaluation_agent.py` and
  `evaluation_store.py`: immutable plan input and deterministic review.
- `security.py`: scrypt password verification and HttpOnly session records.
- `notifications.py`: disabled-by-default event and SSE foundation.
- `dashboard/app.py`: authenticated read-only API surface.
- `scripts/verify_read_only_boundary.py`: exact-segment route scan.

## 3. EVAL result

The foundation policy returns `REJECTED` for unknown or blocked security and
`WATCH_ONLY` for incomplete or untrusted evidence. It never allows alerts,
Paper or Shadow. The LLM advisory module validates factor references and
returns a copy of the deterministic result without changing its decision.

## 4. Risk and Gate

No market data has been collected yet, so coverage is zero and no trading
performance claim is made. The main risks are provider timestamp contracts,
future data leakage, identity collisions and accidental expansion of the
read-only boundary. Week 1 is `NO-GO` for any execution and is eligible for
Week 2 only after tests, build and route scan are green.
