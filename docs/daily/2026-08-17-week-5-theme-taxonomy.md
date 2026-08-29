# KQUANT v2 Week 5 - Theme Taxonomy v1

## 1. Goal and completion

**Completion: implementation complete; taxonomy Gate PASS.**

This week converts the old flat stock tags into a versioned, point-in-time
taxonomy. It does not calculate theme returns, rank themes, train a model, or
use future performance to define membership.

## 2. Delivered modules

- `kquant/db/migrations.py`: schema v5 adds taxonomy runs, versioned
  definitions, memberships, effective dates, and membership audit records.
- `config/theme_taxonomy_v1.yml`: taxonomy release `theme_taxonomy_v1.0.1`
  with theme, industry, risk-style, liquidity and instrument dimensions.
- `kquant/theme_taxonomy.py`: YAML validation, taxonomy/content hashes,
  deterministic point-in-time rule mapping, explicit `needs_review` fallback,
  idempotent materialization and read-only detail queries.
- `GET /api/themes` and `GET /api/themes/{theme_id}`: read the latest
  materialized taxonomy without silently writing a new run.
- CLI: `build-theme-taxonomy` and `theme-taxonomy-status`.
- Frontend Settings: taxonomy version, as-of date, mapped coverage, review
  count and definition membership summary.

## 3. Current taxonomy result

The materialized run is `ttr_da00cfeaa4857b77194c`, based on registry
`usr_49f29d1d945a9b574511` and as-of date `2026-08-17`.

| Measure | Result |
| --- | ---: |
| Registry symbols | 296 |
| Theme-mapped symbols | 294 |
| Theme coverage | 99.32% |
| Explicit review symbols | 2 |
| Theme definitions | Versioned v1.0.1 |

The two explicit review symbols are `ARKK` and `MSTR`. They retain risk-style
memberships but have no reliable v1 theme rule; they are not silently assigned
to a theme. Membership dimensions are separately stored for theme, industry,
risk style, liquidity and instrument type.

## 4. Verification

- Taxonomy tests, dashboard tests and migration tests: 15 passed
- Frontend tests: 2 passed
- Frontend production build: passed
- Live API smoke: health reports schema v5 and API contract
  `kquant-api-2026-08-16-data-trust-v1`; `/api/themes` reports materialized
  `theme_taxonomy_v1.0.1`
- No broker, account, positions or order route introduced

## 5. Leakage and product risks

- Rules use only registry metadata and an explicit effective date. Historical
  classification is not backfilled from future returns.
- A taxonomy hash, registry hash, run ID and membership evidence are stored for
  every materialization.
- Existing Yahoo and Longbridge candle data are not used to define membership.
- Multi-dimensional memberships are descriptive metadata, not predictive
  scores. Week 6 must not treat membership count as theme performance.
- Two review symbols remain visible as review-required rather than being
  forced into a category.

## 6. Gate decision

**PASS:** 99.32% of the eligible Universe is mapped to a formal v1 theme and
the remainder is explicitly marked for review. The taxonomy is ready as an
input to Week 6 Capital Rotation V0.1, but no prediction probability is
allowed to appear in the product yet.

## 7. Rollback point

Source rollback is the Week 5 taxonomy commit. Database schema is forward-only;
restore the verified `2026-08-17` SQLite backup if the v5 migration itself must
be rolled back. The v1.0.1 run is content-addressed and can be ignored by a
later taxonomy version without deleting historical membership evidence.
