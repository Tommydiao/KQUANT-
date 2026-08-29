# KQUANT Unified Platform Contract v1

## Purpose

KQUANT presents Stocks and Crypto through one local shell without mixing their
market data, strategy state, authentication or persistence.

## Public platform endpoints

- `GET /api/version`
- `GET /api/platform/health`
- `GET /api/platform/summary`
- `GET /api/gateway/config` (compatibility)
- `GET /api/gateway/health` (compatibility alias)

## Separation guarantees

- Stock API and database remain owned by the stock backend.
- Crypto API and database remain owned by the crypto backend.
- The shell does not copy or normalize business payloads between products.
- No account, wallet, position or order API is introduced.
- Platform health may report availability and version metadata only.

## Build identity

All runtimes read build metadata from:

1. `KQUANT_BUILD_SHA`, otherwise CI/provider commit variables;
2. `KQUANT_ENVIRONMENT`;
3. `KQUANT_BUILD_TIME`.

A deployable release must show the same non-`local` build SHA in the gateway,
stock API and crypto API. A mismatch is a deployment failure.

## Current local topology

```text
http://127.0.0.1:8020  unified shell and platform health
http://127.0.0.1:8001  stock application and API
http://127.0.0.1:8010  crypto application and API
```

The browser loads each independent application inside the shell. This topology
is suitable for local integration testing, not public production hosting.

## Production prerequisites

- stable hosted API endpoints;
- Postgres migration and restore proof;
- shared user identity without shared strategy data;
- HTTPS and explicit CORS policy;
- provider, ingestion and model observability;
- backup and rollback rehearsal;
- matching GitHub, frontend and API build SHA;
- all strategy and Shadow Go gates passed.
