from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable


LATEST_SCHEMA_VERSION = 17


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    apply: Callable[[sqlite3.Connection], None] | None = None

    @property
    def checksum(self) -> str:
        return hashlib.sha256(f"{self.version}|{self.name}|{self.sql}".encode("utf-8")).hexdigest()


FOUNDATION_SQL = """
CREATE TABLE IF NOT EXISTS crypto_venues (
  venue_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  venue_type TEXT NOT NULL CHECK(venue_type IN ('cex','dex','chain','reference')),
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crypto_assets (
  asset_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  name TEXT NOT NULL,
  asset_kind TEXT NOT NULL CHECK(asset_kind IN ('native','token','stablecoin','unknown')),
  canonical_chain_id TEXT,
  canonical_contract_address TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(canonical_chain_id, canonical_contract_address)
);

CREATE TABLE IF NOT EXISTS crypto_instruments (
  instrument_id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL REFERENCES crypto_assets(asset_id),
  venue_id TEXT NOT NULL REFERENCES crypto_venues(venue_id),
  market_type TEXT NOT NULL CHECK(market_type IN ('spot','perpetual','future','dex_pool','reference')),
  provider_symbol TEXT NOT NULL,
  quote_asset TEXT NOT NULL,
  status TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(venue_id, market_type, provider_symbol)
);

CREATE TABLE IF NOT EXISTS crypto_universe_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  registry_version TEXT NOT NULL,
  as_of_time TEXT NOT NULL,
  available_at TEXT NOT NULL,
  member_count INTEGER NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  members_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  source_time TEXT,
  received_at TEXT NOT NULL,
  details_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_provider_events_provider_time
ON provider_events(provider, received_at DESC);

CREATE TABLE IF NOT EXISTS operational_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  component TEXT NOT NULL,
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  message TEXT NOT NULL,
  details_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
  token_hash TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  idle_expires_at TEXT NOT NULL,
  max_expires_at TEXT NOT NULL,
  revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS auth_login_attempts (
  attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_key TEXT NOT NULL,
  success INTEGER NOT NULL,
  attempted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_attempts_client_time
ON auth_login_attempts(client_key, attempted_at DESC);

CREATE TABLE IF NOT EXISTS notification_preferences (
  owner_email TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 0,
  web_push_enabled INTEGER NOT NULL DEFAULT 0,
  telegram_enabled INTEGER NOT NULL DEFAULT 0,
  quiet_start TEXT,
  quiet_end TEXT,
  timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS web_push_subscriptions (
  subscription_id TEXT PRIMARY KEY,
  owner_email TEXT NOT NULL,
  endpoint_hash TEXT NOT NULL UNIQUE,
  endpoint TEXT NOT NULL,
  p256dh TEXT NOT NULL,
  auth_key TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_events (
  notification_id TEXT PRIMARY KEY,
  severity TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  deep_link TEXT,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_delivery_attempts (
  attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
  notification_id TEXT NOT NULL REFERENCES notification_events(notification_id),
  channel TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT NOT NULL,
  attempted_at TEXT NOT NULL
);
"""


EVALUATION_SQL = """
CREATE TABLE IF NOT EXISTS crypto_trade_plan_drafts (
  plan_id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  proposed_stage TEXT NOT NULL,
  factor_snapshot_hash TEXT NOT NULL,
  source_snapshot_ids_json TEXT NOT NULL,
  identity_status TEXT NOT NULL,
  data_quality_status TEXT NOT NULL,
  security_status TEXT NOT NULL,
  liquidity_status TEXT NOT NULL,
  market_regime TEXT NOT NULL,
  model_status TEXT NOT NULL,
  entry_zone_json TEXT NOT NULL,
  stop_zone_json TEXT NOT NULL,
  target_zone_json TEXT NOT NULL,
  risk_reward REAL,
  valid_from TEXT,
  valid_until TEXT,
  invalid_conditions_json TEXT NOT NULL,
  factor_ids_json TEXT NOT NULL,
  requested_execution_class TEXT NOT NULL,
  material_state_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_trade_plans_asset_created
ON crypto_trade_plan_drafts(asset_id, created_at DESC);

CREATE TABLE IF NOT EXISTS crypto_evaluation_runs (
  evaluation_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES crypto_trade_plan_drafts(plan_id),
  evaluated_at TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('REJECTED','WATCH_ONLY','ARMED','PAPER_REVIEW','SHADOW_ELIGIBLE','INVALIDATED')),
  evaluation_status TEXT NOT NULL,
  execution_class TEXT NOT NULL,
  allowed_alert INTEGER NOT NULL,
  allowed_paper INTEGER NOT NULL,
  allowed_shadow INTEGER NOT NULL,
  evidence_grade TEXT NOT NULL,
  strategy_stage TEXT NOT NULL,
  factor_snapshot_hash TEXT NOT NULL,
  material_state_hash TEXT NOT NULL,
  evaluation_policy_version TEXT NOT NULL,
  expires_at TEXT,
  source_snapshot_ids_json TEXT NOT NULL,
  result_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_evaluations_plan_time
ON crypto_evaluation_runs(plan_id, evaluated_at DESC);

CREATE TABLE IF NOT EXISTS crypto_evaluation_evidence (
  evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
  evaluation_id TEXT NOT NULL REFERENCES crypto_evaluation_runs(evaluation_id),
  evidence_group TEXT NOT NULL,
  evidence_key TEXT NOT NULL,
  status TEXT NOT NULL,
  value_json TEXT NOT NULL,
  source_snapshot_id TEXT,
  recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crypto_evaluation_blockers (
  blocker_id INTEGER PRIMARY KEY AUTOINCREMENT,
  evaluation_id TEXT NOT NULL REFERENCES crypto_evaluation_runs(evaluation_id),
  precedence INTEGER NOT NULL,
  blocker_group TEXT NOT NULL,
  code TEXT NOT NULL,
  severity TEXT NOT NULL,
  message TEXT NOT NULL,
  details_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_evaluation_blockers_eval
ON crypto_evaluation_blockers(evaluation_id, precedence);

CREATE TABLE IF NOT EXISTS crypto_evaluation_decisions (
  evaluation_id TEXT PRIMARY KEY REFERENCES crypto_evaluation_runs(evaluation_id),
  decision TEXT NOT NULL,
  allowed_alert INTEGER NOT NULL,
  allowed_paper INTEGER NOT NULL,
  allowed_shadow INTEGER NOT NULL,
  decided_at TEXT NOT NULL,
  decision_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crypto_llm_advisory_reviews (
  review_id TEXT PRIMARY KEY,
  evaluation_id TEXT NOT NULL REFERENCES crypto_evaluation_runs(evaluation_id),
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  status TEXT NOT NULL,
  referenced_factor_ids_json TEXT NOT NULL,
  advisory_json TEXT NOT NULL,
  rejection_reasons_json TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


TRUST_AND_UNIVERSE_SQL = """
CREATE TABLE IF NOT EXISTS crypto_data_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  snapshot_type TEXT NOT NULL,
  asset_id TEXT,
  instrument_id TEXT,
  venue TEXT,
  source TEXT NOT NULL,
  source_time TEXT,
  available_at TEXT,
  fetched_at TEXT NOT NULL,
  trust_status TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(snapshot_type, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_crypto_data_snapshots_asset_time
ON crypto_data_snapshots(asset_id, source_time DESC);

CREATE TABLE IF NOT EXISTS crypto_universe_registry (
  asset_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  asset_kind TEXT NOT NULL,
  chain_id TEXT,
  contract_address TEXT,
  status TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crypto_universe_memberships (
  snapshot_id TEXT NOT NULL REFERENCES crypto_universe_snapshots(snapshot_id),
  asset_id TEXT NOT NULL,
  tier TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  membership_status TEXT NOT NULL,
  PRIMARY KEY(snapshot_id, asset_id)
);
CREATE INDEX IF NOT EXISTS idx_crypto_universe_membership_asset_time
ON crypto_universe_memberships(asset_id, effective_from DESC);

CREATE TABLE IF NOT EXISTS crypto_market_regime_snapshots (
  regime_snapshot_id TEXT PRIMARY KEY,
  universe_snapshot_id TEXT,
  data_snapshot_ids_json TEXT NOT NULL,
  regime TEXT NOT NULL,
  confidence TEXT NOT NULL,
  as_of_time TEXT NOT NULL,
  available_at TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  evidence_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_regime_time
ON crypto_market_regime_snapshots(as_of_time DESC);
"""


FACTOR_SQL = """
CREATE TABLE IF NOT EXISTS crypto_factor_definitions (
  factor_id TEXT PRIMARY KEY,
  factor_version TEXT NOT NULL,
  factor_group TEXT NOT NULL,
  formula TEXT NOT NULL,
  lookback TEXT NOT NULL,
  source_fields_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(factor_id, factor_version)
);

CREATE TABLE IF NOT EXISTS crypto_factor_snapshots (
  factor_snapshot_id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  factor_version TEXT NOT NULL,
  as_of_time TEXT NOT NULL,
  available_at TEXT NOT NULL,
  values_json TEXT NOT NULL,
  contributions_json TEXT NOT NULL,
  missing_factor_ids_json TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_factor_snapshots_asset_time
ON crypto_factor_snapshots(asset_id, as_of_time DESC);
"""


DEX_SECURITY_SQL = """
CREATE TABLE IF NOT EXISTS crypto_token_contracts (
  asset_id TEXT PRIMARY KEY,
  chain_id TEXT NOT NULL,
  contract_address TEXT NOT NULL,
  symbol TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  UNIQUE(chain_id, contract_address)
);

CREATE TABLE IF NOT EXISTS crypto_liquidity_pools (
  pool_id TEXT PRIMARY KEY,
  chain_id TEXT NOT NULL,
  dex_id TEXT NOT NULL,
  pair_address TEXT NOT NULL,
  base_asset_id TEXT NOT NULL,
  quote_asset_id TEXT NOT NULL,
  created_at_source TEXT,
  status TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  UNIQUE(chain_id, pair_address)
);

CREATE TABLE IF NOT EXISTS crypto_token_pool_memberships (
  pool_id TEXT NOT NULL REFERENCES crypto_liquidity_pools(pool_id),
  asset_id TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  membership_status TEXT NOT NULL,
  PRIMARY KEY(pool_id, asset_id, effective_from)
);

CREATE TABLE IF NOT EXISTS crypto_dex_market_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  pool_id TEXT NOT NULL REFERENCES crypto_liquidity_pools(pool_id),
  source TEXT NOT NULL,
  source_time TEXT,
  available_at TEXT,
  fetched_at TEXT NOT NULL,
  trust_status TEXT NOT NULL,
  price_usd REAL,
  liquidity_usd REAL,
  volume_5m_usd REAL,
  buys_5m INTEGER,
  sells_5m INTEGER,
  fdv_usd REAL,
  content_hash TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_dex_market_pool_time
ON crypto_dex_market_snapshots(pool_id, source_time DESC);

CREATE TABLE IF NOT EXISTS crypto_token_security_snapshots (
  security_snapshot_id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  chain_id TEXT NOT NULL,
  source TEXT NOT NULL,
  source_time TEXT,
  available_at TEXT,
  fetched_at TEXT NOT NULL,
  status TEXT NOT NULL,
  risk_level TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_security_asset_time
ON crypto_token_security_snapshots(asset_id, source_time DESC);

CREATE TABLE IF NOT EXISTS crypto_holder_snapshots (
  holder_snapshot_id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  source TEXT NOT NULL,
  source_time TEXT,
  holder_count INTEGER,
  top10_concentration REAL,
  creator_share REAL,
  lp_share REAL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


VALIDATION_SQL = """
CREATE TABLE IF NOT EXISTS crypto_validation_runs (
  run_id TEXT PRIMARY KEY,
  strategy_version TEXT NOT NULL,
  dataset_version TEXT NOT NULL,
  split_config_json TEXT NOT NULL,
  backtest_config_json TEXT NOT NULL,
  status TEXT NOT NULL,
  report_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crypto_validation_trades (
  trade_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES crypto_validation_runs(run_id),
  asset_id TEXT,
  symbol TEXT NOT NULL,
  signal_time TEXT NOT NULL,
  entry_time TEXT NOT NULL,
  exit_time TEXT NOT NULL,
  entry_price REAL NOT NULL,
  exit_price REAL NOT NULL,
  stop_price REAL NOT NULL,
  target_price REAL NOT NULL,
  realized_r REAL NOT NULL,
  exit_reason TEXT NOT NULL,
  setup_score REAL NOT NULL,
  factor_ids_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_validation_trades_run
ON crypto_validation_trades(run_id, signal_time);
"""


EVAL_BINDING_SQL = """
-- The apply hook adds these columns to databases created by schema v1/v2.
-- SQLite has no portable ALTER TABLE ... ADD COLUMN IF NOT EXISTS.
"""


def _apply_eval_binding_columns(conn: sqlite3.Connection) -> None:
    for table, column in (
        ("crypto_trade_plan_drafts", "snapshot_bindings_json"),
        ("crypto_evaluation_runs", "snapshot_bindings_json"),
    ):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT '{{}}'")


PAPER_SQL = """
CREATE TABLE IF NOT EXISTS crypto_paper_observations (
  observation_id TEXT PRIMARY KEY,
  evaluation_id TEXT NOT NULL REFERENCES crypto_evaluation_runs(evaluation_id),
  plan_id TEXT NOT NULL REFERENCES crypto_trade_plan_drafts(plan_id),
  asset_id TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  symbol TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('OPEN','CLOSED','INVALIDATED','REJECTED')),
  entry_price REAL NOT NULL,
  exit_price REAL,
  units REAL NOT NULL,
  risk_per_unit REAL NOT NULL,
  realized_r REAL,
  entry_snapshot_id TEXT NOT NULL,
  exit_snapshot_id TEXT,
  observed_at TEXT NOT NULL,
  closed_at TEXT,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_paper_observations_time
ON crypto_paper_observations(observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_crypto_paper_observations_asset
ON crypto_paper_observations(asset_id, observed_at DESC);
"""


INSTRUCTION_SQL = """
CREATE TABLE IF NOT EXISTS crypto_trade_instructions (
  instruction_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES crypto_trade_plan_drafts(plan_id),
  evaluation_id TEXT NOT NULL REFERENCES crypto_evaluation_runs(evaluation_id),
  asset_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('MONITORING','READY','TRIGGERED','INVALIDATED','EXPIRED','EXIT_REVIEW')),
  evaluation_decision TEXT NOT NULL,
  execution_class TEXT NOT NULL,
  allowed_alert INTEGER NOT NULL,
  allowed_paper INTEGER NOT NULL,
  allowed_shadow INTEGER NOT NULL,
  factor_snapshot_hash TEXT NOT NULL,
  material_state_hash TEXT NOT NULL,
  expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  UNIQUE(plan_id, material_state_hash)
);
CREATE INDEX IF NOT EXISTS idx_crypto_instructions_asset_time
ON crypto_trade_instructions(asset_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_crypto_instructions_state_time
ON crypto_trade_instructions(state, updated_at DESC);

CREATE TABLE IF NOT EXISTS crypto_instruction_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  instruction_id TEXT NOT NULL REFERENCES crypto_trade_instructions(instruction_id),
  evaluation_id TEXT NOT NULL REFERENCES crypto_evaluation_runs(evaluation_id),
  from_state TEXT,
  to_state TEXT NOT NULL,
  event_type TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_instruction_events_instruction_time
ON crypto_instruction_events(instruction_id, created_at DESC);
"""


MODEL_ARTIFACT_SQL = """
CREATE TABLE IF NOT EXISTS crypto_model_artifacts (
  model_id TEXT PRIMARY KEY,
  model_version TEXT NOT NULL,
  model_type TEXT NOT NULL,
  dataset_version TEXT NOT NULL,
  dataset_hash TEXT NOT NULL,
  feature_order_hash TEXT NOT NULL,
  test_partition_hash TEXT NOT NULL,
  artifact_hash TEXT NOT NULL,
  calibration_gate TEXT NOT NULL,
  status TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  frozen_at TEXT,
  UNIQUE(model_version, dataset_hash, feature_order_hash, test_partition_hash)
);
CREATE INDEX IF NOT EXISTS idx_crypto_model_artifacts_version
ON crypto_model_artifacts(model_version, created_at DESC);
"""


ROLL_RESEARCH_SQL = """
CREATE TABLE IF NOT EXISTS crypto_roll_plans (
  roll_id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  action TEXT NOT NULL,
  status TEXT NOT NULL,
  as_of_time TEXT NOT NULL,
  data_cutoff_time TEXT NOT NULL,
  source_status TEXT NOT NULL,
  coverage REAL NOT NULL,
  hard_veto INTEGER NOT NULL,
  roll_capital REAL NOT NULL,
  remaining_risk REAL NOT NULL,
  feature_snapshot_id TEXT,
  model_version TEXT,
  source_snapshot_ids_json TEXT NOT NULL,
  blockers_json TEXT NOT NULL,
  warnings_json TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_roll_plans_asset_time
ON crypto_roll_plans(asset_id, as_of_time DESC);

CREATE TABLE IF NOT EXISTS crypto_roll_ledger (
  ledger_id TEXT PRIMARY KEY,
  roll_id TEXT,
  asset_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  event_type TEXT NOT NULL,
  realized_profit REAL NOT NULL,
  rolled_capital REAL NOT NULL,
  remaining_risk REAL NOT NULL,
  user_note TEXT NOT NULL DEFAULT '',
  occurred_at TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_crypto_roll_ledger_asset_time
ON crypto_roll_ledger(asset_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS crypto_bayesian_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  model_version TEXT NOT NULL,
  signal_time TEXT NOT NULL,
  available_at TEXT NOT NULL,
  source_status TEXT NOT NULL,
  evidence_status TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_bayesian_asset_time
ON crypto_bayesian_snapshots(asset_id, signal_time DESC);

CREATE TABLE IF NOT EXISTS crypto_monte_carlo_runs (
  run_id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  model_version TEXT NOT NULL,
  status TEXT NOT NULL,
  sample_count INTEGER NOT NULL,
  as_of_time TEXT,
  config_json TEXT NOT NULL,
  result_hash TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_monte_carlo_asset_time
ON crypto_monte_carlo_runs(asset_id, created_at DESC);
"""


EXTERNAL_EVIDENCE_SQL = """
CREATE TABLE IF NOT EXISTS crypto_external_evidence (
  evidence_id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  category TEXT NOT NULL CHECK(category IN ('etf_flow','exchange_derivatives','onchain','whale','market_structure','protocol_metric')),
  source TEXT NOT NULL,
  source_status TEXT NOT NULL,
  source_time TEXT,
  published_at TEXT,
  available_at TEXT NOT NULL,
  trust_status TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_external_evidence_asset_category_time
ON crypto_external_evidence(asset_id, category, available_at DESC);
"""


ROLL_VALIDATION_SQL = """
CREATE TABLE IF NOT EXISTS crypto_roll_validation_runs (
  run_id TEXT PRIMARY KEY,
  strategy_version TEXT NOT NULL,
  validation_version TEXT NOT NULL,
  dataset_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  report_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_roll_validation_created
ON crypto_roll_validation_runs(created_at DESC);
"""


SHADOW_SQL = """
CREATE TABLE IF NOT EXISTS crypto_shadow_observations (
  observation_id TEXT PRIMARY KEY,
  asset_scope TEXT NOT NULL CHECK(asset_scope IN ('crypto','stock')),
  asset_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  action TEXT NOT NULL,
  strategy_stage TEXT NOT NULL,
  as_of_time TEXT NOT NULL,
  data_cutoff_time TEXT NOT NULL,
  source_status TEXT NOT NULL,
  coverage REAL NOT NULL,
  hard_veto INTEGER NOT NULL,
  feature_snapshot_id TEXT,
  model_version TEXT,
  factor_snapshot_hash TEXT,
  source_snapshot_ids_json TEXT NOT NULL,
  entry_zone_json TEXT NOT NULL,
  stop_zone_json TEXT NOT NULL,
  target_zone_json TEXT NOT NULL,
  bayesian_json TEXT NOT NULL,
  monte_carlo_json TEXT NOT NULL,
  ai_rank REAL,
  evaluation_id TEXT,
  roll_id TEXT,
  user_status TEXT NOT NULL CHECK(user_status IN ('pending','reviewed','skipped','paper_observed','manual_note')),
  user_note TEXT NOT NULL DEFAULT '',
  outcome_status TEXT NOT NULL CHECK(outcome_status IN ('pending','completed','invalidated','unavailable')),
  outcome_json TEXT NOT NULL DEFAULT '{}',
  content_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_shadow_asset_time
ON crypto_shadow_observations(asset_id, as_of_time DESC);
CREATE INDEX IF NOT EXISTS idx_crypto_shadow_date_scope
ON crypto_shadow_observations(asset_scope, substr(as_of_time, 1, 10));

CREATE TABLE IF NOT EXISTS crypto_shadow_audit_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  observation_id TEXT NOT NULL REFERENCES crypto_shadow_observations(observation_id),
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_shadow_audit_time
ON crypto_shadow_audit_events(observation_id, created_at ASC, event_id ASC);
"""


ROLL_JOURNAL_PREVIEW_SQL = """
CREATE TABLE IF NOT EXISTS crypto_roll_journal_previews (
  preview_id TEXT PRIMARY KEY,
  content_hash TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK(status IN ('preview_ready','confirmed','expired')),
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  confirmed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_crypto_roll_journal_previews_status_time
ON crypto_roll_journal_previews(status, created_at DESC);
"""


VALIDATION_OOS_SQL = """
-- The apply hook adds evidence partition columns to existing validation rows.
-- Keeping this migration additive preserves all v1 validation history.
"""


def _apply_validation_oos_columns(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(crypto_validation_trades)")}
    if "evidence_partition" not in columns:
        conn.execute(
            "ALTER TABLE crypto_validation_trades "
            "ADD COLUMN evidence_partition TEXT NOT NULL DEFAULT 'legacy'"
        )
    if "oos_fold" not in columns:
        conn.execute("ALTER TABLE crypto_validation_trades ADD COLUMN oos_fold INTEGER")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_crypto_validation_trades_evidence "
        "ON crypto_validation_trades(run_id, evidence_partition, oos_fold, signal_time)"
    )


VALIDATION_FACTOR_VALUES_SQL = """
-- Factor values are captured at the signal bar for leakage-safe model
-- benchmarking. Existing historical rows intentionally remain empty.
"""


def _apply_validation_factor_values_column(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(crypto_validation_trades)")}
    if "factor_values_json" not in columns:
        conn.execute(
            "ALTER TABLE crypto_validation_trades "
            "ADD COLUMN factor_values_json TEXT NOT NULL DEFAULT '{}'"
        )


MIGRATIONS = (
    Migration(1, "crypto_foundation", FOUNDATION_SQL),
    Migration(2, "crypto_evaluation_v1", EVALUATION_SQL),
    Migration(3, "crypto_trust_universe_v1", TRUST_AND_UNIVERSE_SQL),
    Migration(4, "crypto_factor_registry_v1", FACTOR_SQL),
    Migration(5, "crypto_dex_security_v1", DEX_SECURITY_SQL),
    Migration(6, "crypto_validation_v1", VALIDATION_SQL),
    Migration(7, "crypto_eval_snapshot_bindings_v1", EVAL_BINDING_SQL, _apply_eval_binding_columns),
    Migration(8, "crypto_paper_observations_v1", PAPER_SQL),
    Migration(9, "crypto_trade_instructions_v1", INSTRUCTION_SQL),
    Migration(10, "crypto_model_artifacts_v1", MODEL_ARTIFACT_SQL),
    Migration(11, "crypto_validation_oos_evidence_v1", VALIDATION_OOS_SQL, _apply_validation_oos_columns),
    Migration(12, "crypto_validation_factor_values_v1", VALIDATION_FACTOR_VALUES_SQL, _apply_validation_factor_values_column),
    Migration(13, "crypto_roll_bayesian_monte_carlo_v1", ROLL_RESEARCH_SQL),
    Migration(14, "crypto_external_evidence_v1", EXTERNAL_EVIDENCE_SQL),
    Migration(15, "crypto_roll_validation_v1", ROLL_VALIDATION_SQL),
    Migration(16, "crypto_shadow_observation_v1", SHADOW_SQL),
    Migration(17, "crypto_roll_journal_preview_v1", ROLL_JOURNAL_PREVIEW_SQL),
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # WAL is initialized once by migrate(). Re-running PRAGMA journal_mode on
    # every short-lived read connection can wait behind a DEX write batch and
    # make otherwise cheap health requests appear hung.
    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _ensure_ledger(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          checksum TEXT NOT NULL,
          applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schema_migration_audit (
          audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
          version INTEGER NOT NULL,
          name TEXT NOT NULL,
          checksum TEXT NOT NULL,
          status TEXT NOT NULL,
          details_json TEXT NOT NULL,
          recorded_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schema_fingerprints (
          fingerprint TEXT PRIMARY KEY,
          schema_version INTEGER NOT NULL,
          object_count INTEGER NOT NULL,
          computed_at TEXT NOT NULL
        );
        """
    )


def schema_fingerprint(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        """
        SELECT type, name, COALESCE(sql, '') AS sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    ).fetchall()
    payload = [dict(row) for row in rows]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def migrate(db_path: Path) -> dict[str, object]:
    conn = connect(db_path)
    try:
        journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if journal_mode != "wal":
            conn.execute("PRAGMA journal_mode=WAL")
        _ensure_ledger(conn)
        applied = {int(row["version"]): dict(row) for row in conn.execute("SELECT * FROM schema_migrations")}
        for migration in MIGRATIONS:
            prior = applied.get(migration.version)
            if prior:
                if prior["name"] != migration.name or prior["checksum"] != migration.checksum:
                    raise MigrationError(f"Migration {migration.version} checksum mismatch.")
                continue
            try:
                # Keep the DDL transaction explicit.  sqlite3.executescript
                # commits any pending transaction before executing, so the
                # BEGIN/COMMIT pair must be part of the script itself.
                conn.executescript(f"BEGIN;\n{migration.sql}\nCOMMIT;")
                if migration.apply:
                    migration.apply(conn)
                    conn.commit()
                conn.execute(
                    "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)",
                    (migration.version, migration.name, migration.checksum, _now()),
                )
                conn.execute(
                    """
                    INSERT INTO schema_migration_audit(version,name,checksum,status,details_json,recorded_at)
                    VALUES(?,?,?,?,?,?)
                    """,
                    (migration.version, migration.name, migration.checksum, "applied", "{}", _now()),
                )
                conn.commit()
            except Exception as exc:
                conn.rollback()
                raise MigrationError(f"Migration {migration.version} failed: {exc}") from exc
        fingerprint = schema_fingerprint(conn)
        object_count = int(
            conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchone()[0]
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_fingerprints(fingerprint,schema_version,object_count,computed_at) VALUES(?,?,?,?)",
            (fingerprint, LATEST_SCHEMA_VERSION, object_count, _now()),
        )
        conn.commit()
        return migration_status(db_path)
    finally:
        conn.close()


def migration_status(db_path: Path) -> dict[str, object]:
    conn = connect(db_path)
    try:
        # This function is used by the health endpoint and must remain a
        # read-only operation.  Creating the ledger tables here would acquire
        # a DDL/write lock while the DEX discovery worker is persisting a
        # batch, making health checks wait behind unrelated market writes.
        try:
            rows = [dict(row) for row in conn.execute("SELECT * FROM schema_migrations ORDER BY version")]
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            rows = []
        current = max((int(row["version"]) for row in rows), default=0)
        expected = {migration.version: migration for migration in MIGRATIONS}
        integrity = all(
            row["name"] == expected[int(row["version"])].name
            and row["checksum"] == expected[int(row["version"])].checksum
            for row in rows
            if int(row["version"]) in expected
        )
        return {
            "status": "ready" if current == LATEST_SCHEMA_VERSION and integrity else "blocked",
            "current_version": current,
            "latest_version": LATEST_SCHEMA_VERSION,
            "integrity": integrity,
            "fingerprint": schema_fingerprint(conn),
            "migrations": rows,
        }
    finally:
        conn.close()
