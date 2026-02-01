"""Tests for the sync module."""

import pytest
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from sagg.models import (
    UnifiedSession,
    Turn,
    Message,
    TextPart,
    SessionStats,
    SourceTool,
    generate_session_id,
    TokenUsage,
)
from sagg.adapters.base import SessionAdapter, SessionRef
from sagg.sync import SessionSyncer


class MockAdapter(SessionAdapter):
    """Mock adapter for testing."""

    def __init__(
        self,
        name: str = "mock",
        sessions: list[SessionRef] | None = None,
    ):
        self._name = name
        self._sessions = sessions or []
        self._parsed_sessions: dict[str, UnifiedSession] = {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def display_name(self) -> str:
        return f"Mock {self._name.capitalize()}"

    def get_default_path(self) -> Path:
        return Path("/tmp/mock")

    def is_available(self) -> bool:
        return True

    def list_sessions(self, since: datetime | None = None) -> list[SessionRef]:
        if since is None:
            return self._sessions
        return [s for s in self._sessions if s.updated_at > since]

    def parse_session(self, ref: SessionRef) -> UnifiedSession:
        if ref.id in self._parsed_sessions:
            return self._parsed_sessions[ref.id]

        # Create a default session - source must match adapter name for session_exists check
        # Map mock adapter names to SourceTool enum values
        source_map = {
            "mock": SourceTool.OPENCODE,
            "opencode": SourceTool.OPENCODE,
            "claude": SourceTool.CLAUDE,
        }
        source = source_map.get(self._name, SourceTool.OPENCODE)

        return UnifiedSession(
            id=generate_session_id(),
            source=source,
            source_id=ref.id,
            source_path=str(ref.path),
            title=f"Session {ref.id}",
            project_name="test-project",
            project_path="/tmp/test-project",
            created_at=ref.created_at,
            updated_at=ref.updated_at,
            stats=SessionStats(turn_count=1, message_count=2),
            turns=[
                Turn(
                    id="turn-1",
                    index=0,
                    started_at=ref.created_at,
                    messages=[
                        Message(
                            id="msg-1",
                            role="user",
                            timestamp=ref.created_at,
                            parts=[TextPart(content="Hello")],
                        ),
                        Message(
                            id="msg-2",
                            role="assistant",
                            timestamp=ref.created_at,
                            parts=[TextPart(content="Hi there")],
                        ),
                    ],
                )
            ],
        )

    def add_session(self, ref: SessionRef, session: UnifiedSession | None = None):
        """Add a session for testing."""
        self._sessions.append(ref)
        if session:
            self._parsed_sessions[ref.id] = session


def create_session_ref(
    session_id: str,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> SessionRef:
    """Helper to create a SessionRef for testing."""
    now = datetime.now(timezone.utc)
    return SessionRef(
        id=session_id,
        path=Path(f"/tmp/sessions/{session_id}.json"),
        created_at=created_at or now,
        updated_at=updated_at or now,
    )


class TestSyncStateTracking:
    """Tests for sync state tracking in the store."""

    def test_get_sync_state_returns_none_for_new_source(self, session_store):
        """Test that get_sync_state returns None for a source with no sync history."""
        result = session_store.get_sync_state("opencode")
        assert result is None

    def test_update_sync_state_creates_new_entry(self, session_store):
        """Test that update_sync_state creates a new entry for a source."""
        now = int(time.time())
        session_store.update_sync_state("opencode", now, 5)

        result = session_store.get_sync_state("opencode")
        assert result is not None
        assert result["last_sync_at"] == now
        assert result["session_count"] == 5

    def test_update_sync_state_updates_existing(self, session_store):
        """Test that update_sync_state updates an existing entry."""
        first_time = int(time.time()) - 3600
        session_store.update_sync_state("opencode", first_time, 3)

        second_time = int(time.time())
        session_store.update_sync_state("opencode", second_time, 5)

        result = session_store.get_sync_state("opencode")
        assert result is not None
        assert result["last_sync_at"] == second_time
        assert result["session_count"] == 5

    def test_sync_state_per_source(self, session_store):
        """Test that sync state is tracked per source."""
        now = int(time.time())
        session_store.update_sync_state("opencode", now, 10)
        session_store.update_sync_state("claude", now - 100, 5)

        opencode_state = session_store.get_sync_state("opencode")
        claude_state = session_store.get_sync_state("claude")

        assert opencode_state["session_count"] == 10
        assert claude_state["session_count"] == 5
        assert opencode_state["last_sync_at"] > claude_state["last_sync_at"]


class TestSessionSyncer:
    """Tests for the SessionSyncer class."""

    def test_sync_once_empty_adapters(self, session_store):
        """Test sync with no adapters."""
        syncer = SessionSyncer(session_store, [])
        result = syncer.sync_once()
        assert result == {}

    def test_sync_once_no_sessions(self, session_store):
        """Test sync when adapters have no sessions."""
        adapter = MockAdapter("mock", sessions=[])
        syncer = SessionSyncer(session_store, [adapter])

        result = syncer.sync_once()
        assert result["mock"]["new"] == 0
        assert result["mock"]["skipped"] == 0

    def test_sync_once_new_sessions(self, session_store):
        """Test sync with new sessions to import."""
        ref1 = create_session_ref("session-1")
        ref2 = create_session_ref("session-2")
        adapter = MockAdapter("mock", sessions=[ref1, ref2])
        syncer = SessionSyncer(session_store, [adapter])

        result = syncer.sync_once()
        assert result["mock"]["new"] == 2
        assert result["mock"]["skipped"] == 0

        # Verify sessions were saved
        sessions = session_store.list_sessions()
        assert len(sessions) == 2

    def test_sync_once_skips_existing_sessions(self, session_store):
        """Test that sync skips sessions that already exist."""
        ref1 = create_session_ref("session-1")
        # Use "opencode" as adapter name to match SourceTool.OPENCODE
        adapter = MockAdapter("opencode", sessions=[ref1])
        syncer = SessionSyncer(session_store, [adapter])

        # First sync
        result1 = syncer.sync_once()
        assert result1["opencode"]["new"] == 1

        # Add another session
        ref2 = create_session_ref("session-2")
        adapter.add_session(ref2)

        # Second sync - should only get the new one
        result2 = syncer.sync_once()
        assert result2["opencode"]["new"] == 1
        assert result2["opencode"]["skipped"] == 1

    def test_sync_once_incremental_using_sync_state(self, session_store):
        """Test that sync uses last sync time for incremental sync."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        new_time = datetime.now(timezone.utc)

        ref_old = create_session_ref("old-session", updated_at=old_time)
        ref_new = create_session_ref("new-session", updated_at=new_time)

        adapter = MockAdapter("mock", sessions=[ref_old, ref_new])
        syncer = SessionSyncer(session_store, [adapter])

        # Set a sync state 1 hour ago - should only get new session
        one_hour_ago = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
        session_store.update_sync_state("mock", one_hour_ago, 1)

        result = syncer.sync_once()
        # Only the new session should be processed (old one is before last sync)
        assert result["mock"]["new"] == 1

    def test_sync_once_source_filter(self, session_store):
        """Test sync with source filter."""
        adapter1 = MockAdapter("opencode", sessions=[create_session_ref("s1")])
        adapter2 = MockAdapter("claude", sessions=[create_session_ref("s2")])
        syncer = SessionSyncer(session_store, [adapter1, adapter2])

        # Sync only opencode
        result = syncer.sync_once(source="opencode")
        assert "opencode" in result
        assert "claude" not in result
        assert result["opencode"]["new"] == 1

    def test_sync_once_updates_sync_state(self, session_store):
        """Test that sync updates the sync state after completion."""
        ref = create_session_ref("session-1")
        adapter = MockAdapter("mock", sessions=[ref])
        syncer = SessionSyncer(session_store, [adapter])

        before_sync = int(time.time())
        syncer.sync_once()
        after_sync = int(time.time())

        state = session_store.get_sync_state("mock")
        assert state is not None
        assert before_sync <= state["last_sync_at"] <= after_sync


class TestDryRun:
    """Tests for dry-run mode."""

    def test_dry_run_does_not_save_sessions(self, session_store):
        """Test that dry-run mode does not save sessions."""
        ref = create_session_ref("session-1")
        adapter = MockAdapter("mock", sessions=[ref])
        syncer = SessionSyncer(session_store, [adapter])

        result = syncer.sync_once(dry_run=True)
        assert result["mock"]["new"] == 1

        # Verify no sessions were saved
        sessions = session_store.list_sessions()
        assert len(sessions) == 0

    def test_dry_run_does_not_update_sync_state(self, session_store):
        """Test that dry-run mode does not update sync state."""
        ref = create_session_ref("session-1")
        adapter = MockAdapter("mock", sessions=[ref])
        syncer = SessionSyncer(session_store, [adapter])

        syncer.sync_once(dry_run=True)

        state = session_store.get_sync_state("mock")
        assert state is None

    def test_dry_run_shows_would_sync_count(self, session_store):
        """Test that dry-run shows correct would-sync count."""
        refs = [create_session_ref(f"session-{i}") for i in range(5)]
        adapter = MockAdapter("mock", sessions=refs)
        syncer = SessionSyncer(session_store, [adapter])

        result = syncer.sync_once(dry_run=True)
        assert result["mock"]["new"] == 5
        assert result["mock"]["skipped"] == 0


class TestWatchMode:
    """Tests for watch mode functionality."""

    def test_get_watch_paths_returns_adapter_paths(self, session_store):
        """Test that get_watch_paths returns paths for available adapters."""
        adapter = MockAdapter("mock")
        syncer = SessionSyncer(session_store, [adapter])

        paths = syncer.get_watch_paths()
        assert len(paths) == 1
        assert paths[0] == Path("/tmp/mock")

    def test_get_watch_paths_with_source_filter(self, session_store):
        """Test that get_watch_paths respects source filter."""
        adapter1 = MockAdapter("opencode")
        adapter2 = MockAdapter("claude")
        syncer = SessionSyncer(session_store, [adapter1, adapter2])

        paths = syncer.get_watch_paths(source="opencode")
        assert len(paths) == 1

    def test_get_watch_paths_skips_unavailable_adapters(self, session_store):
        """Test that unavailable adapters are skipped."""
        adapter = MockAdapter("mock")
        adapter.is_available = lambda: False  # type: ignore
        syncer = SessionSyncer(session_store, [adapter])

        paths = syncer.get_watch_paths()
        assert len(paths) == 0
