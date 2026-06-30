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
CREATE TABLE IF NOT EXISTS stock_signal_runs (
  run_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  universe TEXT NOT NULL,
  profile TEXT NOT NULL,
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
  features_json TEXT NOT NULL,
  data_status_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (run_id, symbol)
);
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
  sample_count INTEGER NOT NULL,
  win_rate_5d REAL NOT NULL,
  avg_forward_return_5d REAL NOT NULL,
  avg_max_drawdown_5d REAL NOT NULL,
  buy_setup_count INTEGER NOT NULL,
  watch_count INTEGER NOT NULL,
  pass_count INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_signal_journal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  strategy_profile TEXT NOT NULL DEFAULT '',
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
CREATE TABLE IF NOT EXISTS provider_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  instrument TEXT NOT NULL,
  symbol TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
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
            "rule_conclusion": "TEXT NOT NULL DEFAULT ''",
            "ai_review_verdict": "TEXT NOT NULL DEFAULT ''",
        },
    )
    return conn


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    conn.commit()
