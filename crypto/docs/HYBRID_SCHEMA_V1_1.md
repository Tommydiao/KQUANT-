# Hybrid Identity and Storage Contract V1.1

M1 synthetic specification; NOT a production migration. Owner: current integration
task. Existing candidate, EVAL, validation, PAPER and SHADOW databases are untouched.

## Identity

- economic_signal_id: strategy + original policy + symbol + mode + closed 5m
  signal time + opportunity sequence. News/model changes cannot create a new
  economic opportunity.
- evaluation_id: economic signal + complete immutable evidence bundle, times,
  portfolio version/hash, approved quantity and reservation. Changed news or
  models create another evaluation, not another entry opportunity.
- entry_intent_id: run + experimental arm + economic signal. Database uniqueness
  is stronger than one active intent: at most one activated intent per opportunity
  in the synthetic reference. Partial fills remain attached to that intent.

All hashes use canonical sorted JSON, finite values and SHA256. These are content
identities, not signatures or proof of model validity.

## Implemented Synthetic Tables

`hybrid_transaction_contract.SyntheticLedger` accepts a caller-owned, isolated
SQLite connection, refuses foreign tables, and labels every account
SYNTHETIC_CONTRACT_ONLY. Tests use memory or pytest temporary directories.

| Table | Key and purpose |
| --- | --- |
| hybrid_contract_accounts | (run,arm), version, cash, reserved cash/risk, pending protection |
| hybrid_evaluations | immutable evaluation_id, signal, all evidence bindings and timing |
| hybrid_decisions | one committed/rejected decision per evaluation |
| hybrid_entry_intents | unique(run,arm,signal), quantity, filled quantity and cash |
| hybrid_fills | unique(intent,event), immutable synthetic fill payload |
| hybrid_ledger_events | unique(run,arm,event), transactional audit/checkpoint identity |

BEGIN IMMEDIATE serializes account mutation. A successful commit compares the
entire portfolio state hash and version, checks pending protection and budgets,
then writes the intent, reservations, decision and audit atomically. Injected
failure rolls all of them back. Fill duplication is checked before mutation;
changed duplicate payloads are errors. A model worker owns no connection.

The logical writer never waits on model Futures. Same-timestamp protection
precedes entry. Writer callback failure halts the fixture; it cannot continue
or silently replay the failed callback. Recovery is explicit from committed DB
state. Missing quote records pending protection and zero fabricated fills.

## Explicit M5 Gaps

This is not a market-ready ledger: full positions, fees, exit accounting, intent
expiration/release, reader APIs, migration checksums, leases, cross-process writer
ownership, hard-risk fill recheck, fixed BTC/ETH/SOL batch arbitration, latest
registry version matching and crash restoration of unprocessed protection events
still require M5. Evidence hashes are stored but do not certify matching live
model/policy registries. A passing CAS test cannot be described as this full Gate.

Proposed production database: `work/hybrid_candidate_v1.sqlite3`. Creation and
schema migration are not performed in M0/M1. Use distinct hybrid run/arm IDs,
append-only audit events, foreign keys and uniqueness constraints; never migrate
or attach original running stores. M5 needs fixture backup/restore and rollback
proof before any persistent writer.

## Label Schema

`hybrid_label_contract.LabelRecord` requires economic identity, execution policy,
source population, signal/availability times, dependence group and execution
quality. Sources: executed_virtual, counterfactual, termination_liquidation.
Statuses: mature, censored, unavailable, terminated. Censored/unavailable requires
net_r=null, not zero. Termination is excluded from mature strategy labels.

Training selection uses one source and execution policy, availability <= cutoff,
mature outcomes only, no synthetic fixtures and no duplicate economic signal.
Historical OHLC proxy is never named an exchange fill. The selector is a contract
test helper, not a full PIT dataset builder or label generator. Reference quantity,
selection population and overlap weighting remain unfrozen before M2/M3 training.
