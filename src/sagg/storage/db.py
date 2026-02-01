"""Database connection management and schema migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import TracebackType

# Schema version for migrations
SCHEMA_VERSION = 3

# SQL statements for schema creation
SCHEMA_SQL = """
-- Sessions table (metadata for fast queries)
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_path TEXT NOT NULL,
    title TEXT,
    project_path TEXT,
    project_name TEXT,
    git_branch TEXT,
    git_commit TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    duration_ms INTEGER,
    turn_count INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    models_json TEXT,
    files_modified_json TEXT,
    imported_at INTEGER NOT NULL,
    origin_machine TEXT,
    import_source TEXT,
    UNIQUE(source, source_id)
);

-- Models used (for filtering/analytics)
CREATE TABLE IF NOT EXISTS session_models (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    model_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    message_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    PRIMARY KEY (session_id, model_id)
);

-- Tool calls (for analytics)
CREATE TABLE IF NOT EXISTS session_tools (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    call_count INTEGER DEFAULT 0,
    PRIMARY KEY (session_id, tool_name)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_path);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);

-- Sync state tracking for incremental sync
CREATE TABLE IF NOT EXISTS sync_state (
    source TEXT PRIMARY KEY,
    last_sync_at INTEGER NOT NULL,
    session_count INTEGER DEFAULT 0
);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);
"""

FTS_SCHEMA_SQL = """
-- Full-text search index (created separately as it's a virtual table)
CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
    title,
    project_name,
    content,
    content=sessions,
    content_rowid=rowid
);

-- Triggers to keep FTS index in sync
CREATE TRIGGER IF NOT EXISTS sessions_ai AFTER INSERT ON sessions BEGIN
    INSERT INTO sessions_fts(rowid, title, project_name, content)
    VALUES (new.rowid, new.title, new.project_name, '');
END;

CREATE TRIGGER IF NOT EXISTS sessions_ad AFTER DELETE ON sessions BEGIN
    INSERT INTO sessions_fts(sessions_fts, rowid, title, project_name, content)
    VALUES ('delete', old.rowid, old.title, old.project_name, '');
END;

CREATE TRIGGER IF NOT EXISTS sessions_au AFTER UPDATE ON sessions BEGIN
    INSERT INTO sessions_fts(sessions_fts, rowid, title, project_name, content)
    VALUES ('delete', old.rowid, old.title, old.project_name, '');
    INSERT INTO sessions_fts(rowid, title, project_name, content)
    VALUES (new.rowid, new.title, new.project_name, '');
END;
"""


class DatabaseError(Exception):
    """Database operation error."""


class Database:
    """SQLite database connection manager with schema migrations."""

    def __init__(self, db_path: Path) -> None:
        """Initialize database connection.

        Args:
            db_path: Path to the SQLite database file.
        """
        self._db_path = db_path
        self._connection: sqlite3.Connection | None = None

    @property
    def path(self) -> Path:
        """Get the database file path."""
        return self._db_path

    def connect(self) -> sqlite3.Connection:
        """Get or create database connection.

        Returns:
            Active SQLite connection.
        """
        if self._connection is None:
            # Ensure parent directory exists
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

            self._connection = sqlite3.connect(
                self._db_path,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            # Enable foreign keys
            self._connection.execute("PRAGMA foreign_keys = ON")
            # Use WAL mode for better concurrent access
            self._connection.execute("PRAGMA journal_mode = WAL")
            # Return rows as Row objects for dict-like access
            self._connection.row_factory = sqlite3.Row

        return self._connection

    def close(self) -> None:
        """Close the database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> Database:
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: object) -> None:
        """Context manager exit."""
        self.close()

    def transaction(self) -> _TransactionContext:
        """Get a transaction context manager.

        Usage:
            with db.transaction() as cursor:
                cursor.execute(...)
        """
        return _TransactionContext(self.connect())

    def execute(self, sql: str, params: tuple | dict | None = None) -> sqlite3.Cursor:
        """Execute a SQL statement.

        Args:
            sql: SQL statement to execute.
            params: Optional parameters for the statement.

        Returns:
            Cursor with results.
        """
        conn = self.connect()
        if params is None:
            return conn.execute(sql)
        return conn.execute(sql, params)

    def executemany(self, sql: str, params_list: list[tuple] | list[dict]) -> sqlite3.Cursor:
        """Execute a SQL statement with multiple parameter sets.

        Args:
            sql: SQL statement to execute.
            params_list: List of parameter tuples/dicts.

        Returns:
            Cursor with results.
        """
        conn = self.connect()
        return conn.executemany(sql, params_list)

    def commit(self) -> None:
        """Commit the current transaction."""
        if self._connection is not None:
            self._connection.commit()

    def rollback(self) -> None:
        """Rollback the current transaction."""
        if self._connection is not None:
            self._connection.rollback()

    def get_schema_version(self) -> int:
        """Get the current schema version.

        Returns:
            Current schema version, or 0 if not initialized.
        """
        try:
            cursor = self.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return row["version"] if row else 0
        except sqlite3.OperationalError:
            # Table doesn't exist yet
            return 0

    def initialize_schema(self) -> None:
        """Initialize or migrate the database schema."""
        current_version = self.get_schema_version()

        if current_version < SCHEMA_VERSION:
            self._apply_migrations(current_version)

    def _apply_migrations(self, from_version: int) -> None:
        """Apply schema migrations from the given version.

        Args:
            from_version: Starting schema version.
        """
        conn = self.connect()

        if from_version == 0:
            # Initial schema creation
            conn.executescript(SCHEMA_SQL)
            conn.executescript(FTS_SCHEMA_SQL)

            # Record schema version
            import time

            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (1, int(time.time())),
            )
            conn.commit()
            from_version = 1  # Update for subsequent migrations

        # Migration v1 -> v2: Add provenance tracking columns
        if from_version < 2:
            self._migrate_v1_to_v2()

        # Migration v2 -> v3: Add budgets table
        if from_version < 3:
            self._migrate_v2_to_v3()

    def _migrate_v1_to_v2(self) -> None:
        """Migrate schema from v1 to v2.

        Adds provenance tracking columns for bundle import functionality:
        - origin_machine: Machine ID where session was originally created
        - import_source: Path to bundle file if imported
        """
        import time

        conn = self.connect()

        # Add new columns (SQLite doesn't support IF NOT EXISTS for columns)
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN origin_machine TEXT")
        except Exception:
            pass  # Column may already exist

        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN import_source TEXT")
        except Exception:
            pass  # Column may already exist

        # Record schema version
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (2, int(time.time())),
        )
        conn.commit()

    def _migrate_v2_to_v3(self) -> None:
        """Migrate schema from v2 to v3.

        Adds budgets table for token budget tracking.
        """
        import time

        conn = self.connect()

        # Create budgets table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY,
                period TEXT NOT NULL,
                token_limit INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(period)
            )
        """)

        # Record schema version
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (3, int(time.time())),
        )
        conn.commit()

    def check_fts_table_exists(self) -> bool:
        """Check if the FTS table exists.

        Returns:
            True if sessions_fts table exists.
        """
        cursor = self.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions_fts'"
        )
        return cursor.fetchone() is not None

    def update_fts_content(self, session_id: str, content: str) -> None:
        """Update the FTS content for a session.

        Args:
            session_id: Session ID to update.
            content: Text content for full-text search.
        """
        # Get the rowid for this session
        cursor = self.execute("SELECT rowid FROM sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        if row is None:
            return

        rowid = row["rowid"]

        # Get current session data for title and project_name
        cursor = self.execute(
            "SELECT title, project_name FROM sessions WHERE id = ?", (session_id,)
        )
        session_row = cursor.fetchone()
        if session_row is None:
            return

        # Update FTS with content
        # First delete existing entry
        self.execute(
            "INSERT INTO sessions_fts(sessions_fts, rowid, title, project_name, content) "
            "VALUES ('delete', ?, ?, ?, '')",
            (rowid, session_row["title"], session_row["project_name"]),
        )
        # Then insert new entry with content
        self.execute(
            "INSERT INTO sessions_fts(rowid, title, project_name, content) VALUES (?, ?, ?, ?)",
            (rowid, session_row["title"], session_row["project_name"], content),
        )
        self.commit()


class _TransactionContext:
    """Context manager for database transactions."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._cursor: sqlite3.Cursor | None = None

    def __enter__(self) -> sqlite3.Cursor:
        self._cursor = self._connection.cursor()
        return self._cursor

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._cursor is not None:
            if exc_type is None:
                self._connection.commit()
            else:
                self._connection.rollback()
            self._cursor.close()


def get_default_db_path() -> Path:
    """Get the default database path.

    Returns:
        Path to ~/.sagg/db.sqlite
    """
    return Path.home() / ".sagg" / "db.sqlite"


def get_sessions_dir() -> Path:
    """Get the default sessions storage directory.

    Returns:
        Path to ~/.sagg/sessions/
    """
    return Path.home() / ".sagg" / "sessions"
