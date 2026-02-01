"""Session storage layer."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from sagg.models import (
    GitContext,
    Message,
    ModelUsage,
    Part,
    SessionStats,
    SourceTool,
    Turn,
    UnifiedSession,
)
from sagg.storage.db import Database, get_default_db_path, get_sessions_dir


class SessionStoreError(Exception):
    """Session store operation error."""


class SessionStore:
    """Storage layer for unified sessions.

    Manages both SQLite metadata storage and JSONL content files.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        sessions_dir: Path | None = None,
    ) -> None:
        """Initialize the session store.

        Args:
            db_path: Path to SQLite database. Defaults to ~/.sagg/db.sqlite
            sessions_dir: Path to sessions directory. Defaults to ~/.sagg/sessions/
        """
        self._db_path = db_path or get_default_db_path()
        self._sessions_dir = sessions_dir or get_sessions_dir()
        self._db = Database(self._db_path)

        # Initialize schema on first access
        self._db.initialize_schema()

    @property
    def db(self) -> Database:
        """Get the database instance."""
        return self._db

    @property
    def sessions_dir(self) -> Path:
        """Get the sessions directory path."""
        return self._sessions_dir

    def close(self) -> None:
        """Close the database connection."""
        self._db.close()

    def __enter__(self) -> SessionStore:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: object) -> None:
        """Context manager exit."""
        self.close()

    def save_session(self, session: UnifiedSession) -> None:
        """Save or update a session.

        Stores metadata in SQLite and content as JSONL file.

        Args:
            session: Session to save.
        """
        now = int(time.time())

        # Prepare model and file JSON
        models_json = json.dumps([m.model_id for m in session.models])
        files_json = json.dumps(session.stats.files_modified)

        # Insert or replace session metadata
        self._db.execute(
            """
            INSERT OR REPLACE INTO sessions (
                id, source, source_id, source_path,
                title, project_path, project_name,
                git_branch, git_commit,
                created_at, updated_at, duration_ms,
                turn_count, message_count,
                input_tokens, output_tokens, tool_call_count,
                models_json, files_modified_json, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                session.source.value,
                session.source_id,
                session.source_path,
                session.title,
                session.project_path,
                session.project_name,
                session.git.branch if session.git else None,
                session.git.commit if session.git else None,
                int(session.created_at.timestamp()),
                int(session.updated_at.timestamp()),
                session.duration_ms,
                session.stats.turn_count,
                session.stats.message_count,
                session.stats.input_tokens,
                session.stats.output_tokens,
                session.stats.tool_call_count,
                models_json,
                files_json,
                now,
            ),
        )

        # Save model usage details
        self._db.execute("DELETE FROM session_models WHERE session_id = ?", (session.id,))
        for model in session.models:
            self._db.execute(
                """
                INSERT INTO session_models (
                    session_id, model_id, provider,
                    message_count, input_tokens, output_tokens
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    model.model_id,
                    model.provider,
                    model.message_count,
                    model.input_tokens,
                    model.output_tokens,
                ),
            )

        # Save tool usage details
        self._db.execute("DELETE FROM session_tools WHERE session_id = ?", (session.id,))
        tool_counts = session.get_tool_counts()
        for tool_name, call_count in tool_counts.items():
            self._db.execute(
                """
                INSERT INTO session_tools (session_id, tool_name, call_count)
                VALUES (?, ?, ?)
                """,
                (session.id, tool_name, call_count),
            )

        self._db.commit()

        # Save content as JSONL
        self._save_content(session)

        # Update FTS index with content
        content = session.extract_text_content()
        self._db.update_fts_content(session.id, content)

    def _save_content(self, session: UnifiedSession) -> None:
        """Save session content to JSONL file.

        Args:
            session: Session whose content to save.
        """
        # Create directory structure: ~/.sagg/sessions/<source>/<session-id>.jsonl
        source_dir = self._sessions_dir / session.source.value
        source_dir.mkdir(parents=True, exist_ok=True)

        content_path = source_dir / f"{session.id}.jsonl"
        content_path.write_text(session.to_jsonl())

    def _load_content(self, session_id: str, source: str) -> list[Message]:
        """Load session content from JSONL file.

        Args:
            session_id: Session ID.
            source: Source tool name.

        Returns:
            List of messages from the session.
        """
        content_path = self._sessions_dir / source / f"{session_id}.jsonl"
        if not content_path.exists():
            return []

        content = content_path.read_text()
        if not content.strip():
            return []

        return UnifiedSession.messages_from_jsonl(content)

    def get_session(self, session_id: str) -> UnifiedSession | None:
        """Get a session by ID.

        Args:
            session_id: Session ID to retrieve.

        Returns:
            Session if found, None otherwise.
        """
        cursor = self._db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        if row is None:
            return None

        return self._row_to_session(row, include_content=True)

    def list_sessions(
        self,
        source: str | None = None,
        project: str | None = None,
        since: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[UnifiedSession]:
        """List sessions with optional filtering.

        Args:
            source: Filter by source tool (opencode, claude, etc.).
            project: Filter by project path (partial match).
            since: Only include sessions created after this datetime.
            limit: Maximum number of sessions to return.
            offset: Number of sessions to skip.

        Returns:
            List of sessions matching the filters.
        """
        conditions = []
        params: list[str | int] = []

        if source is not None:
            conditions.append("source = ?")
            params.append(source)

        if project is not None:
            conditions.append("(project_path LIKE ? OR project_name LIKE ?)")
            params.append(f"%{project}%")
            params.append(f"%{project}%")

        if since is not None:
            conditions.append("created_at >= ?")
            params.append(int(since.timestamp()))

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT * FROM sessions
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        params.append(limit)
        params.append(offset)

        cursor = self._db.execute(query, tuple(params))
        return [self._row_to_session(row, include_content=False) for row in cursor]

    def search_sessions(self, query: str, limit: int = 50) -> list[UnifiedSession]:
        """Search sessions using full-text search.

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            List of matching sessions.
        """
        # Use FTS5 match syntax
        cursor = self._db.execute(
            """
            SELECT s.* FROM sessions s
            JOIN sessions_fts fts ON s.rowid = fts.rowid
            WHERE sessions_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        )
        return [self._row_to_session(row, include_content=False) for row in cursor]

    def search_sessions_ranked(
        self, query: str, limit: int = 50
    ) -> list[tuple[UnifiedSession, float]]:
        """Search sessions with relevance scores.

        Uses FTS5 for matching and returns both the session and its relevance rank.
        The rank is a negative number where more negative means better match.

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            List of tuples containing (session, relevance_score).
        """
        cursor = self._db.execute(
            """
            SELECT s.*, fts.rank as relevance
            FROM sessions s
            JOIN sessions_fts fts ON s.rowid = fts.rowid
            WHERE sessions_fts MATCH ?
            ORDER BY fts.rank
            LIMIT ?
            """,
            (query, limit),
        )
        results = []
        for row in cursor:
            session = self._row_to_session(row, include_content=True)
            relevance = row["relevance"]
            results.append((session, relevance))
        return results

    def session_exists(self, source: str, source_id: str) -> bool:
        """Check if a session already exists.

        Args:
            source: Source tool name.
            source_id: Original session ID from the source.

        Returns:
            True if session exists.
        """
        cursor = self._db.execute(
            "SELECT 1 FROM sessions WHERE source = ? AND source_id = ?",
            (source, source_id),
        )
        return cursor.fetchone() is not None

    def get_session_by_source(self, source: str, source_id: str) -> UnifiedSession | None:
        """Get a session by source and source_id.

        Args:
            source: Source tool name.
            source_id: Original session ID from the source.

        Returns:
            Session if found, None otherwise.
        """
        cursor = self._db.execute(
            "SELECT * FROM sessions WHERE source = ? AND source_id = ?",
            (source, source_id),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return self._row_to_session(row, include_content=True)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: Session ID to delete.

        Returns:
            True if session was deleted.
        """
        # Get session info first
        cursor = self._db.execute("SELECT source FROM sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        if row is None:
            return False

        source = row["source"]

        # Delete from database (CASCADE will handle related tables)
        self._db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._db.commit()

        # Delete content file
        content_path = self._sessions_dir / source / f"{session_id}.jsonl"
        if content_path.exists():
            content_path.unlink()

        return True

    def get_sessions_by_day(self, since: datetime) -> dict[str, dict]:
        """Get session counts and token totals grouped by day.

        Args:
            since: Start datetime for the query.

        Returns:
            Dictionary mapping date strings to stats:
            {
                "2026-01-30": {"count": 5, "tokens": 45000},
                "2026-01-29": {"count": 3, "tokens": 28000},
                ...
            }
        """
        cursor = self._db.execute(
            """
            SELECT date(created_at, 'unixepoch') as day,
                   COUNT(*) as count,
                   SUM(input_tokens + output_tokens) as tokens
            FROM sessions
            WHERE created_at >= ?
            GROUP BY day
            """,
            (int(since.timestamp()),),
        )
        return {
            row["day"]: {"count": row["count"], "tokens": row["tokens"] or 0}
            for row in cursor
        }

    def get_stats(self) -> dict:
        """Get aggregate statistics.

        Returns:
            Dictionary with statistics:
            - total_sessions: Total number of sessions
            - sessions_by_source: Count by source tool
            - total_tokens: Total input + output tokens
            - total_turns: Total conversation turns
            - models_used: List of unique models
            - tools_used: List of unique tools with counts
        """
        stats: dict = {}

        # Total sessions
        cursor = self._db.execute("SELECT COUNT(*) as count FROM sessions")
        row = cursor.fetchone()
        stats["total_sessions"] = row["count"] if row else 0

        # Sessions by source
        cursor = self._db.execute("SELECT source, COUNT(*) as count FROM sessions GROUP BY source")
        stats["sessions_by_source"] = {row["source"]: row["count"] for row in cursor}

        # Total tokens
        cursor = self._db.execute(
            "SELECT SUM(input_tokens) as input, SUM(output_tokens) as output FROM sessions"
        )
        row = cursor.fetchone()
        stats["total_input_tokens"] = row["input"] or 0 if row else 0
        stats["total_output_tokens"] = row["output"] or 0 if row else 0
        stats["total_tokens"] = stats["total_input_tokens"] + stats["total_output_tokens"]

        # Total turns
        cursor = self._db.execute("SELECT SUM(turn_count) as total FROM sessions")
        row = cursor.fetchone()
        stats["total_turns"] = row["total"] or 0 if row else 0

        # Models used with token counts
        cursor = self._db.execute(
            """
            SELECT model_id, provider,
                   SUM(message_count) as messages,
                   SUM(input_tokens) as input,
                   SUM(output_tokens) as output
            FROM session_models
            GROUP BY model_id, provider
            ORDER BY input + output DESC
            """
        )
        stats["models_used"] = [
            {
                "model_id": row["model_id"],
                "provider": row["provider"],
                "message_count": row["messages"],
                "input_tokens": row["input"],
                "output_tokens": row["output"],
            }
            for row in cursor
        ]

        # Tools used
        cursor = self._db.execute(
            """
            SELECT tool_name, SUM(call_count) as total
            FROM session_tools
            GROUP BY tool_name
            ORDER BY total DESC
            """
        )
        stats["tools_used"] = {row["tool_name"]: row["total"] for row in cursor}

        return stats

    def _row_to_session(self, row: dict, include_content: bool = False) -> UnifiedSession:
        """Convert a database row to a UnifiedSession.

        Args:
            row: Database row (dict-like).
            include_content: Whether to load full content from JSONL.

        Returns:
            UnifiedSession instance.
        """
        from datetime import datetime, timezone

        # Parse JSON fields
        models_json = row["models_json"]
        models_list = json.loads(models_json) if models_json else []

        files_json = row["files_modified_json"]
        files_list = json.loads(files_json) if files_json else []

        # Get model details if available
        models = []
        if models_list:
            cursor = self._db.execute(
                "SELECT * FROM session_models WHERE session_id = ?", (row["id"],)
            )
            for model_row in cursor:
                models.append(
                    ModelUsage(
                        model_id=model_row["model_id"],
                        provider=model_row["provider"],
                        message_count=model_row["message_count"],
                        input_tokens=model_row["input_tokens"],
                        output_tokens=model_row["output_tokens"],
                    )
                )

        # Build git context if available
        git = None
        if row["git_branch"] or row["git_commit"]:
            git = GitContext(
                branch=row["git_branch"] or "",
                commit=row["git_commit"] or "",
            )

        # Build stats
        stats = SessionStats(
            turn_count=row["turn_count"] or 0,
            message_count=row["message_count"] or 0,
            input_tokens=row["input_tokens"] or 0,
            output_tokens=row["output_tokens"] or 0,
            tool_call_count=row["tool_call_count"] or 0,
            files_modified=files_list,
        )

        # Load turns from content if requested
        turns: list[Turn] = []
        if include_content:
            messages = self._load_content(row["id"], row["source"])
            if messages:
                # Group messages into turns (simplified: each message is its own turn)
                # A more sophisticated implementation would group by turn boundaries
                turns = self._messages_to_turns(messages)

        return UnifiedSession(
            id=row["id"],
            source=SourceTool(row["source"]),
            source_id=row["source_id"],
            source_path=row["source_path"],
            title=row["title"],
            project_path=row["project_path"],
            project_name=row["project_name"],
            git=git,
            created_at=datetime.fromtimestamp(row["created_at"], tz=timezone.utc),
            updated_at=datetime.fromtimestamp(row["updated_at"], tz=timezone.utc),
            duration_ms=row["duration_ms"],
            stats=stats,
            models=models,
            turns=turns,
        )

    def _messages_to_turns(self, messages: list[Message]) -> list[Turn]:
        """Group messages into turns.

        Simple implementation: group consecutive user/assistant messages.

        Args:
            messages: List of messages.

        Returns:
            List of turns.
        """
        if not messages:
            return []

        turns: list[Turn] = []
        current_turn_messages: list[Message] = []
        turn_index = 0

        for message in messages:
            # Start a new turn on each user message (after the first)
            if message.role == "user" and current_turn_messages:
                turn = Turn(
                    id=f"turn_{turn_index}",
                    index=turn_index,
                    started_at=current_turn_messages[0].timestamp,
                    ended_at=current_turn_messages[-1].timestamp,
                    messages=current_turn_messages,
                )
                turns.append(turn)
                current_turn_messages = []
                turn_index += 1

            current_turn_messages.append(message)

        # Don't forget the last turn
        if current_turn_messages:
            turn = Turn(
                id=f"turn_{turn_index}",
                index=turn_index,
                started_at=current_turn_messages[0].timestamp,
                ended_at=current_turn_messages[-1].timestamp,
                messages=current_turn_messages,
            )
            turns.append(turn)

        return turns

    def get_sync_state(self, source: str) -> dict | None:
        """Get last sync timestamp and count for a source.

        Args:
            source: Source tool name (e.g., 'opencode', 'claude').

        Returns:
            Dictionary with 'last_sync_at' and 'session_count', or None if never synced.
        """
        cursor = self._db.execute(
            "SELECT last_sync_at, session_count FROM sync_state WHERE source = ?",
            (source,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "last_sync_at": row["last_sync_at"],
            "session_count": row["session_count"],
        }

    def update_sync_state(self, source: str, sync_time: int, count: int) -> None:
        """Update sync state after successful sync.

        Args:
            source: Source tool name.
            sync_time: Unix timestamp of the sync.
            count: Total number of sessions synced for this source.
        """
        self._db.execute(
            """
            INSERT OR REPLACE INTO sync_state (source, last_sync_at, session_count)
            VALUES (?, ?, ?)
            """,
            (source, sync_time, count),
        )
        self._db.commit()

    # Budget management methods

    def set_budget(self, period: str, limit: int) -> None:
        """Set a token budget for a period.

        Args:
            period: Budget period ('daily' or 'weekly').
            limit: Token limit for the period.
        """
        now = int(time.time())
        self._db.execute(
            """
            INSERT OR REPLACE INTO budgets (period, token_limit, created_at)
            VALUES (?, ?, ?)
            """,
            (period, limit, now),
        )
        self._db.commit()

    def get_budget(self, period: str) -> int | None:
        """Get the token budget for a period.

        Args:
            period: Budget period ('daily' or 'weekly').

        Returns:
            Token limit for the period, or None if not set.
        """
        cursor = self._db.execute(
            "SELECT token_limit FROM budgets WHERE period = ?",
            (period,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return row["token_limit"]

    def clear_budget(self, period: str) -> None:
        """Clear a token budget.

        Args:
            period: Budget period ('daily' or 'weekly').
        """
        self._db.execute("DELETE FROM budgets WHERE period = ?", (period,))
        self._db.commit()

    def get_usage_for_period(self, period: str) -> int:
        """Get total token usage for a period.

        Args:
            period: Budget period ('daily' or 'weekly').

        Returns:
            Total tokens (input + output) used in the period.
        """
        from datetime import timezone

        now = datetime.now(timezone.utc)

        if period == "daily":
            # Start of today (midnight UTC)
            start_of_period = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "weekly":
            # Start of week (Monday midnight UTC)
            days_since_monday = now.weekday()
            start_of_period = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start_of_period = start_of_period - timedelta(days=days_since_monday)
        else:
            return 0

        start_timestamp = int(start_of_period.timestamp())

        cursor = self._db.execute(
            """
            SELECT COALESCE(SUM(input_tokens + output_tokens), 0) as total
            FROM sessions
            WHERE created_at >= ?
            """,
            (start_timestamp,),
        )
        row = cursor.fetchone()
        return row["total"] if row else 0
