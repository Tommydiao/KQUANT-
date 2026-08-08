from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS stock_universe (
  symbol TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  sector TEXT NOT NULL,
  layer TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  rank INTEGER NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_universe_snapshots (
  universe TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  definition_hash TEXT NOT NULL,
  membership_count INTEGER NOT NULL,
  source TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  PRIMARY KEY (universe, as_of_date, definition_hash)
);
CREATE INDEX IF NOT EXISTS idx_stock_universe_snapshots_date
ON stock_universe_snapshots(universe, as_of_date);
CREATE TABLE IF NOT EXISTS stock_universe_memberships (
  universe TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  definition_hash TEXT NOT NULL,
  symbol TEXT NOT NULL,
  name TEXT NOT NULL,
  sector TEXT NOT NULL,
  layer TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  rank INTEGER NOT NULL,
  liquidity_tier TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  PRIMARY KEY (universe, as_of_date, definition_hash, symbol),
  FOREIGN KEY (universe, as_of_date, definition_hash)
    REFERENCES stock_universe_snapshots(universe, as_of_date, definition_hash)
);
CREATE INDEX IF NOT EXISTS idx_stock_universe_memberships_lookup
ON stock_universe_memberships(universe, as_of_date, symbol);
CREATE TABLE IF NOT EXISTS stock_candles (
  symbol TEXT NOT NULL,
  interval TEXT NOT NULL,
  open_time TEXT NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume REAL NOT NULL,
  source TEXT NOT NULL,
  provider_status TEXT NOT NULL,
  freshness_seconds INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  PRIMARY KEY (symbol, interval, open_time, source)
);
CREATE TABLE IF NOT EXISTS market_candles (
  symbol TEXT NOT NULL,
  interval TEXT NOT NULL,
  open_time TEXT NOT NULL,
  adjustment_mode TEXT NOT NULL,
  dataset_version TEXT NOT NULL,
  primary_source TEXT NOT NULL,
  provider_symbol TEXT NOT NULL,
  provider_status TEXT NOT NULL,
  freshness_seconds INTEGER NOT NULL,
  bar_state TEXT NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume REAL NOT NULL,
  fetched_at TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (symbol, interval, open_time, adjustment_mode, dataset_version)
);
CREATE INDEX IF NOT EXISTS idx_market_candles_lookup
ON market_candles(symbol, interval, open_time DESC);
CREATE TABLE IF NOT EXISTS market_candle_observations (
  symbol TEXT NOT NULL,
  interval TEXT NOT NULL,
  open_time TEXT NOT NULL,
  adjustment_mode TEXT NOT NULL,
  dataset_version TEXT NOT NULL,
  source TEXT NOT NULL,
  provider_symbol TEXT NOT NULL,
  provider_status TEXT NOT NULL,
  freshness_seconds INTEGER NOT NULL,
  bar_state TEXT NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume REAL NOT NULL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (symbol, interval, open_time, adjustment_mode, dataset_version, source)
);
CREATE TABLE IF NOT EXISTS corporate_action_events (
  symbol TEXT NOT NULL,
  effective_time TEXT NOT NULL,
  interval TEXT NOT NULL,
  adjustment_mode TEXT NOT NULL,
  dataset_version TEXT NOT NULL,
  action_type TEXT NOT NULL,
  price_ratio REAL NOT NULL,
  source TEXT NOT NULL,
  status TEXT NOT NULL,
  details_json TEXT NOT NULL,
  detected_at TEXT NOT NULL,
  PRIMARY KEY (symbol, effective_time, interval, adjustment_mode, dataset_version, action_type)
);
CREATE INDEX IF NOT EXISTS idx_corporate_action_events_symbol_time
ON corporate_action_events(symbol, effective_time DESC);
CREATE TABLE IF NOT EXISTS stock_signal_runs (
  run_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  universe TEXT NOT NULL,
  profile TEXT NOT NULL,
  strategy_version TEXT NOT NULL DEFAULT 'legacy_unversioned',
  strategy_config_hash TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL,
  completed_at TEXT NOT NULL,
  provider_status TEXT NOT NULL,
  provider_error_count INTEGER NOT NULL,
  buy_setup_count INTEGER NOT NULL,
  watch_count INTEGER NOT NULL,
  pass_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_signals (
  run_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  strategy_version TEXT NOT NULL DEFAULT 'legacy_unversioned',
  strategy_config_hash TEXT NOT NULL DEFAULT '',
  score REAL NOT NULL,
  level TEXT NOT NULL,
  trend_summary TEXT NOT NULL,
  trigger_summary TEXT NOT NULL,
  risk_warnings_json TEXT NOT NULL,
  manual_checklist_json TEXT NOT NULL,
  data_status_json TEXT NOT NULL,
  features_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (run_id, symbol)
);
CREATE TABLE IF NOT EXISTS stock_features (
  run_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  feature_time TEXT NOT NULL,
  profile TEXT NOT NULL,
  strategy_version TEXT NOT NULL DEFAULT 'legacy_unversioned',
  strategy_config_hash TEXT NOT NULL DEFAULT '',
  features_json TEXT NOT NULL,
  data_status_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (run_id, symbol)
);
CREATE TABLE IF NOT EXISTS factor_definitions (
  factor_id TEXT NOT NULL,
  registry_version TEXT NOT NULL,
  definition_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (factor_id, registry_version)
);
CREATE TABLE IF NOT EXISTS factor_snapshots (
  snapshot_hash TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  profile TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  strategy_config_hash TEXT NOT NULL,
  as_of_time TEXT NOT NULL,
  registry_version TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_factor_snapshots_symbol_time
ON factor_snapshots(symbol, as_of_time DESC);
CREATE TABLE IF NOT EXISTS stock_labels (
  run_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  signal_time TEXT NOT NULL,
  forward_return_3d REAL NOT NULL,
  forward_return_5d REAL NOT NULL,
  forward_return_10d REAL NOT NULL,
  max_drawdown_5d REAL NOT NULL,
  hit_target_before_stop INTEGER NOT NULL,
  close_above_entry_after_5d INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (run_id, symbol, signal_time)
);
CREATE TABLE IF NOT EXISTS stock_backtest_runs (
  run_id TEXT PRIMARY KEY,
  profile TEXT NOT NULL,
  strategy_version TEXT NOT NULL DEFAULT 'legacy_unversioned',
  strategy_config_hash TEXT NOT NULL DEFAULT '',
  sample_count INTEGER NOT NULL,
  win_rate_5d REAL NOT NULL,
  avg_forward_return_5d REAL NOT NULL,
  avg_max_drawdown_5d REAL NOT NULL,
  buy_setup_count INTEGER NOT NULL,
  watch_count INTEGER NOT NULL,
  pass_count INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_action_events (
  event_key TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  profile TEXT NOT NULL,
  action TEXT NOT NULL,
  signal_time TEXT NOT NULL,
  decision_price REAL NOT NULL,
  entry_price REAL,
  stop_price REAL,
  target_price REAL,
  risk_reward REAL NOT NULL DEFAULT 0,
  market_regime TEXT NOT NULL DEFAULT '',
  data_source TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_action_events_symbol_time
ON ai_action_events(symbol, signal_time DESC);
CREATE TABLE IF NOT EXISTS ai_action_outcomes (
  event_key TEXT NOT NULL,
  horizon_bars INTEGER NOT NULL,
  entry_time TEXT,
  entry_price REAL,
  exit_time TEXT,
  exit_price REAL,
  outcome TEXT NOT NULL,
  realized_r REAL NOT NULL DEFAULT 0,
  max_drawdown_pct REAL NOT NULL DEFAULT 0,
  max_runup_pct REAL NOT NULL DEFAULT 0,
  target_first INTEGER NOT NULL DEFAULT 0,
  stop_first INTEGER NOT NULL DEFAULT 0,
  completed INTEGER NOT NULL DEFAULT 0,
  evaluated_at TEXT NOT NULL,
  PRIMARY KEY (event_key, horizon_bars)
);
CREATE TABLE IF NOT EXISTS ai_decision_cache (
  cache_key TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  profile TEXT NOT NULL,
  model TEXT NOT NULL,
  material_state_hash TEXT NOT NULL,
  response_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_decision_cache_lookup
ON ai_decision_cache(symbol, profile, model, material_state_hash, created_at DESC);
CREATE TABLE IF NOT EXISTS strategy_validation_runs (
  run_id TEXT PRIMARY KEY,
  profile TEXT NOT NULL,
  action TEXT NOT NULL,
  split_name TEXT NOT NULL,
  sample_count INTEGER NOT NULL,
  win_rate REAL NOT NULL,
  average_r REAL NOT NULL,
  profit_factor REAL NOT NULL,
  max_drawdown_r REAL NOT NULL,
  confidence_low REAL NOT NULL,
  confidence_high REAL NOT NULL,
  strategy_version TEXT NOT NULL DEFAULT 'legacy_unversioned',
  strategy_config_hash TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_validation_datasets (
  dataset_id TEXT PRIMARY KEY,
  evidence_source TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  universe TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  symbols_json TEXT NOT NULL,
  config_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_validation_trades (
  trade_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  evidence_source TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  strategy_version TEXT NOT NULL DEFAULT 'legacy_unversioned',
  strategy_config_hash TEXT NOT NULL DEFAULT '',
  profile TEXT NOT NULL,
  action TEXT NOT NULL,
  symbol TEXT NOT NULL,
  signal_time TEXT NOT NULL,
  entry_time TEXT,
  exit_time TEXT,
  split_name TEXT NOT NULL,
  market_regime TEXT NOT NULL,
  sector TEXT NOT NULL,
  stock_layer TEXT NOT NULL,
  volatility_bucket TEXT NOT NULL,
  data_source TEXT NOT NULL,
  outcome TEXT NOT NULL,
  realized_r REAL NOT NULL,
  target_first INTEGER NOT NULL,
  stop_first INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_strategy_validation_trades_action
ON strategy_validation_trades(evidence_source, profile, action, signal_time);
CREATE TABLE IF NOT EXISTS stock_signal_journal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  strategy_profile TEXT NOT NULL DEFAULT '',
  strategy_version TEXT NOT NULL DEFAULT 'legacy_unversioned',
  strategy_config_hash TEXT NOT NULL DEFAULT '',
  rule_conclusion TEXT NOT NULL DEFAULT '',
  ai_review_verdict TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  notes TEXT NOT NULL DEFAULT '',
  planned_entry REAL,
  planned_stop REAL,
  planned_target REAL,
  outcome TEXT NOT NULL DEFAULT '',
  reviewed_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stock_signal_journal_symbol_time
ON stock_signal_journal(symbol, reviewed_at DESC);
CREATE TABLE IF NOT EXISTS strategy_versions (
  strategy_id TEXT NOT NULL,
  strategy_version TEXT PRIMARY KEY,
  profile_name TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  config_json TEXT NOT NULL,
  specification_path TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_strategy_versions_id_hash
ON strategy_versions(strategy_id, config_hash);
CREATE TABLE IF NOT EXISTS provider_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  instrument TEXT NOT NULL,
  symbol TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_calendar_cache (
  market_date TEXT PRIMARY KEY,
  is_trading_day INTEGER NOT NULL,
  is_half_day INTEGER NOT NULL,
  source TEXT NOT NULL,
  regular_open_utc TEXT,
  regular_close_utc TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_freezes (
  strategy_version TEXT PRIMARY KEY,
  strategy_id TEXT NOT NULL,
  profile_name TEXT NOT NULL,
  strategy_config_hash TEXT NOT NULL,
  validation_fingerprint TEXT NOT NULL,
  evidence_score REAL NOT NULL,
  status TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  frozen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decision_ledger (
  ledger_id TEXT PRIMARY KEY,
  signal_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  data_snapshot_json TEXT NOT NULL,
  system_decision_json TEXT NOT NULL,
  user_decision TEXT NOT NULL,
  entry_plan_json TEXT NOT NULL,
  veto_status TEXT NOT NULL,
  final_execution TEXT NOT NULL,
  outcome TEXT NOT NULL,
  outcome_r REAL,
  error_owner TEXT NOT NULL,
  lesson TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decision_ledger_symbol_time
ON decision_ledger(symbol, created_at DESC);
CREATE TABLE IF NOT EXISTS manual_trade_journal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ledger_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  stage TEXT NOT NULL,
  reason TEXT NOT NULL,
  plan_followed INTEGER,
  actual_entry REAL,
  actual_exit REAL,
  result_r REAL,
  emotion TEXT NOT NULL,
  screenshot_ref TEXT NOT NULL,
  notes TEXT NOT NULL,
  review TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_manual_trade_journal_ledger
ON manual_trade_journal(ledger_id, created_at DESC);
CREATE TABLE IF NOT EXISTS scheduled_task_runs (
  run_id TEXT PRIMARY KEY,
  task_name TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  detail_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scheduled_task_runs_name_time
ON scheduled_task_runs(task_name, started_at DESC);
CREATE TABLE IF NOT EXISTS notification_events (
  event_id TEXT PRIMARY KEY,
  channel TEXT NOT NULL,
  event_type TEXT NOT NULL,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operational_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  component TEXT NOT NULL,
  message TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_operational_events_component_time
ON operational_events(component, created_at DESC);
CREATE TABLE IF NOT EXISTS backup_runs (
  backup_id TEXT PRIMARY KEY,
  backup_type TEXT NOT NULL,
  path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL,
  rollback_note TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forward_pilot_sessions (
  session_id TEXT PRIMARY KEY,
  strategy_version TEXT NOT NULL,
  strategy_config_hash TEXT NOT NULL,
  universe_name TEXT NOT NULL,
  universe_snapshot_hash TEXT NOT NULL,
  validation_fingerprint TEXT NOT NULL,
  mode TEXT NOT NULL,
  status TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT,
  rules_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  closed_at TEXT
);
CREATE TABLE IF NOT EXISTS forward_pilot_days (
  session_id TEXT NOT NULL,
  market_date TEXT NOT NULL,
  phase TEXT NOT NULL,
  preflight_json TEXT NOT NULL,
  scan_json TEXT NOT NULL,
  close_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (session_id, market_date)
);
CREATE TABLE IF NOT EXISTS forward_pilot_candidates (
  candidate_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  market_date TEXT NOT NULL,
  signal_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  rank INTEGER NOT NULL,
  level TEXT NOT NULL,
  data_status TEXT NOT NULL,
  veto_status TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  trigger_status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_forward_pilot_candidates_session_date
ON forward_pilot_candidates(session_id, market_date, rank);
CREATE TABLE IF NOT EXISTS forward_pilot_outcomes (
  candidate_id TEXT PRIMARY KEY,
  outcome_status TEXT NOT NULL,
  triggered_at TEXT,
  completed_at TEXT,
  entry_price REAL,
  exit_price REAL,
  realized_r REAL,
  deviation_json TEXT NOT NULL,
  notes TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_simulation_accounts (
  account_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL UNIQUE,
  initial_cash REAL NOT NULL,
  cash REAL NOT NULL,
  risk_per_trade_pct REAL NOT NULL,
  max_positions INTEGER NOT NULL,
  max_daily_risk_pct REAL NOT NULL,
  no_averaging INTEGER NOT NULL,
  no_chasing INTEGER NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_simulation_positions (
  position_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  entry_time TEXT NOT NULL,
  entry_price REAL NOT NULL,
  shares INTEGER NOT NULL,
  stop_price REAL NOT NULL,
  target_price REAL NOT NULL,
  entry_plan_high REAL,
  status TEXT NOT NULL,
  exit_time TEXT,
  exit_price REAL,
  realized_r REAL,
  notes TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_paper_positions_account_status
ON paper_simulation_positions(account_id, status, entry_time);
"""


def default_db_path(root: Path | None = None) -> Path:
    base = (root or Path.cwd()).resolve()
    return base / "work" / "kquant_us.sqlite3"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_columns(
        conn,
        "stock_signal_journal",
        {
            "strategy_profile": "TEXT NOT NULL DEFAULT ''",
            "strategy_version": "TEXT NOT NULL DEFAULT 'legacy_unversioned'",
            "strategy_config_hash": "TEXT NOT NULL DEFAULT ''",
            "rule_conclusion": "TEXT NOT NULL DEFAULT ''",
            "ai_review_verdict": "TEXT NOT NULL DEFAULT ''",
        },
    )
    _ensure_columns(
        conn,
        "stock_signal_runs",
        {
            "strategy_version": "TEXT NOT NULL DEFAULT 'legacy_unversioned'",
            "strategy_config_hash": "TEXT NOT NULL DEFAULT ''",
        },
    )
    _ensure_columns(
        conn,
        "stock_signals",
        {
            "strategy_version": "TEXT NOT NULL DEFAULT 'legacy_unversioned'",
            "strategy_config_hash": "TEXT NOT NULL DEFAULT ''",
        },
    )
    _ensure_columns(
        conn,
        "stock_features",
        {
            "strategy_version": "TEXT NOT NULL DEFAULT 'legacy_unversioned'",
            "strategy_config_hash": "TEXT NOT NULL DEFAULT ''",
        },
    )
    _ensure_columns(
        conn,
        "stock_backtest_runs",
        {
            "strategy_version": "TEXT NOT NULL DEFAULT 'legacy_unversioned'",
            "strategy_config_hash": "TEXT NOT NULL DEFAULT ''",
        },
    )
    _ensure_columns(
        conn,
        "strategy_validation_runs",
        {
            "dataset_id": "TEXT NOT NULL DEFAULT ''",
            "evidence_source": "TEXT NOT NULL DEFAULT 'prospective_llm_actions'",
            "policy_version": "TEXT NOT NULL DEFAULT ''",
            "config_version": "TEXT NOT NULL DEFAULT ''",
            "strategy_version": "TEXT NOT NULL DEFAULT 'legacy_unversioned'",
            "strategy_config_hash": "TEXT NOT NULL DEFAULT ''",
        },
    )
    _ensure_columns(
        conn,
        "strategy_validation_trades",
        {
            "strategy_version": "TEXT NOT NULL DEFAULT 'legacy_unversioned'",
            "strategy_config_hash": "TEXT NOT NULL DEFAULT ''",
        },
    )
    return conn


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    conn.commit()
