# KQUANT Deployment and Version Audit

Audit date: 2026-08-01

## Finding

GitHub `main`, the Vercel frontend, and the API were not a single traceable
release. The Vercel bundle referenced an expired Cloudflare Quick Tunnel, and
`/api/health` on the Vercel host returned the SPA rather than a Python health
payload. The public page therefore looked deployed while its live backend was
offline.

## Release identity contract

Every build now exposes the same immutable identity:

- API: `GET /api/version`
- API health: `GET /api/health`
- Frontend build globals: `build_sha`, `build_time`, `environment`
- Settings UI: abbreviated SHA and build timestamp

The values come from `KQUANT_BUILD_SHA`, `KQUANT_BUILD_TIME`, and
`KQUANT_ENVIRONMENT` in deployment environments, with a local Git fallback for
development. A release is not production-ready unless GitHub, frontend, and API
report the same full SHA.

## Quick Tunnel policy

`*.trycloudflare.com` URLs are temporary demonstration endpoints. Production
frontend builds now reject a configured Quick Tunnel API URL instead of silently
depending on it. A stable hosted API or a named, monitored tunnel is required
before online market data can be represented as available.

## Market-data trust contract

Configuration is not health. The health payload now classifies data as:

- `live_primary`: recent successful Longbridge primary data
- `stale_primary`: Longbridge data exists but is outside the freshness window
- `reference_only`: a non-primary provider such as Yahoo is selected
- `unavailable`: primary credentials, SDK, or successful data are missing

The UI may display reference data for research, but it must not imply that it
supports a buy-class decision. Missing primary data is shown as "unable to
assess", while the deterministic hard veto remains active internally.

## Current release gate

This repository is still in observation and validation mode. Production release
remains blocked until:

1. GitHub, frontend, and API SHAs match.
2. A stable HTTPS backend replaces the Quick Tunnel.
3. Longbridge meets the five-day availability and freshness SLO.
4. `swing_long_v1` passes out-of-sample validation.
5. Monitoring, backup, rollback, and hosted database drills pass.
