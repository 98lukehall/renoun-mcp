"""
ReNoUn SQLite Database.

Shared database module for rate limiting and analytics persistence.
Uses WAL mode for concurrent reads, thread-safe connections.
Database lives at $RENOUN_DATA_DIR/renoun.db (default: ~/.renoun/renoun.db).
"""

import os
import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

_DATA_DIR = os.environ.get("RENOUN_DATA_DIR", str(Path.home() / ".renoun"))
DB_PATH = Path(_DATA_DIR) / "renoun.db"

# Schema version — bump when adding migrations
_SCHEMA_VERSION = 1


def _ensure_dir():
    """Ensure the data directory exists."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _create_tables(conn: sqlite3.Connection):
    """Create all tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            key_id   TEXT NOT NULL,
            date     TEXT NOT NULL,
            call_count INTEGER NOT NULL DEFAULT 0,
            reset_at   REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (key_id, date)
        );

        CREATE TABLE IF NOT EXISTS provisions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ip        TEXT,
            email     TEXT,
            timestamp TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pageviews (
            date  TEXT NOT NULL,
            page  TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (date, page)
        );

        CREATE TABLE IF NOT EXISTS api_calls (
            date     TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            key_id   TEXT NOT NULL DEFAULT '',
            count    INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (date, endpoint, key_id)
        );

        CREATE TABLE IF NOT EXISTS daily_stats (
            date         TEXT PRIMARY KEY,
            provisions   INTEGER NOT NULL DEFAULT 0,
            unique_keys  TEXT NOT NULL DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS schema_meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)


def _run_migrations(conn: sqlite3.Connection):
    """Run any pending migrations based on schema version."""
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    current = int(row[0]) if row else 0

    if current < _SCHEMA_VERSION:
        # Future migrations go here as:
        # if current < 2: ...
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
            (str(_SCHEMA_VERSION),),
        )
        conn.commit()


def _cleanup_old_entries(conn: sqlite3.Connection, days: int = 7):
    """Remove entries older than `days` days from rate_limits table."""
    try:
        conn.execute(
            "DELETE FROM rate_limits WHERE date < date('now', ?)",
            (f"-{days} days",),
        )
        conn.commit()
    except Exception as e:
        logger.warning("Failed to clean up old rate_limit entries: %s", e)


def _init_db() -> sqlite3.Connection:
    """Open (or create) the database with WAL mode and return a connection."""
    _ensure_dir()
    conn = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    _create_tables(conn)
    _run_migrations(conn)
    _cleanup_old_entries(conn)
    return conn


# Module-level singleton connection
_conn: Optional[sqlite3.Connection] = None


def get_connection() -> sqlite3.Connection:
    """Return the singleton database connection, creating it if needed.

    Thread-safe via SQLite WAL mode + busy_timeout.
    """
    global _conn
    if _conn is None:
        _conn = _init_db()
    return _conn


@contextmanager
def get_cursor():
    """Context manager that yields a cursor and commits on success, rolls back on error."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
