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
    return conn
