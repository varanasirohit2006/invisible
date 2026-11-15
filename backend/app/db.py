import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DEFAULT_SETTINGS = {
    "approved_folders": [],
    "monitoring_enabled": False,
    "consent_at": None,
    "scope_revision": 0,
    "minimum_support": 3,
    "retention_days": 30,
    "ai_enabled": False,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, timestamp TEXT NOT NULL,
  event_type TEXT NOT NULL, file_path TEXT, old_path TEXT, new_path TEXT,
  is_demo INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS events_time ON events(timestamp);
CREATE INDEX IF NOT EXISTS events_source_time ON events(is_demo, timestamp);
CREATE TABLE IF NOT EXISTS workflows (
  id INTEGER PRIMARY KEY, signature TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
  sequence TEXT NOT NULL, frequency INTEGER NOT NULL, median_seconds REAL NOT NULL,
  last_seen TEXT NOT NULL, sample_paths TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS suggestions (
  workflow_id INTEGER PRIMARY KEY REFERENCES workflows(id), value TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS previews (
  id TEXT PRIMARY KEY, workflow_id INTEGER NOT NULL REFERENCES workflows(id),
  plan TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY, preview_id TEXT NOT NULL UNIQUE REFERENCES previews(id),
  workflow_id INTEGER NOT NULL REFERENCES workflows(id), created_at TEXT NOT NULL,
  consumed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, workflow_id INTEGER NOT NULL REFERENCES workflows(id),
  approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(id), plan TEXT NOT NULL,
  status TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  claimed_by TEXT, heartbeat_at TEXT, result TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS runs_status ON runs(status, created_at);
CREATE TABLE IF NOT EXISTS agent_status (
  id INTEGER PRIMARY KEY CHECK(id=1), instance_id TEXT NOT NULL, last_seen TEXT NOT NULL,
  watching INTEGER NOT NULL, error TEXT, dropped_events INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO settings(id,value) VALUES(1,?)",
                (json.dumps(DEFAULT_SETTINGS),),
            )

    @contextmanager
    def connection(self, *, write: bool = False):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def settings(self) -> dict:
        with self.connection() as conn:
            return {
                **DEFAULT_SETTINGS,
                **json.loads(conn.execute("SELECT value FROM settings WHERE id=1").fetchone()[0]),
            }
