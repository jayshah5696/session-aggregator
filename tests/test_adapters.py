"""Tests for the base adapter."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sagg.adapters.base import SessionAdapter, SessionRef


class ConcreteAdapter(SessionAdapter):
    """Concrete adapter for testing SessionAdapter."""
    @property
    def name(self) -> str:
        return "test"

    @property
    def display_name(self) -> str:
        return "Test Adapter"

    def get_default_path(self) -> Path:
        return Path("/tmp")

    def is_available(self) -> bool:
        return True

    def list_sessions(self, since: datetime | None = None) -> list[SessionRef]:
        return []

    def parse_session(self, ref: SessionRef):
        """Not needed for has_changed tests."""
        return None

class TestSessionAdapter:
    """Tests for the SessionAdapter base class."""

    def test_has_changed(self):
        """Test the has_changed logic with various scenarios."""
        adapter = ConcreteAdapter()
        base_time = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)

        ref = SessionRef(
            id="test-session",
            path=Path("/tmp/test-session.json"),
            created_at=base_time - timedelta(hours=1),
            updated_at=base_time
        )

        # Case 1: Session updated after last import (should return True)
        last_import_before = base_time - timedelta(minutes=1)
        assert adapter.has_changed(ref, last_import_before) is True

        # Case 2: Session updated exactly at last import (should return False)
        # the current implementation uses '>' which means equal is NOT changed
        last_import_exact = base_time
        assert adapter.has_changed(ref, last_import_exact) is False

        # Case 3: Session updated before last import (should return False)
        last_import_after = base_time + timedelta(minutes=1)
        assert adapter.has_changed(ref, last_import_after) is False

    def test_has_changed_with_naive_datetimes(self):
        """
        Test has_changed with naive datetimes.
        While timezone-aware is preferred, we should ensure the behavior is consistent.
        """
        adapter = ConcreteAdapter()
        base_time = datetime(2023, 1, 1, 12, 0, 0) # Naive

        ref = SessionRef(
            id="test-session",
            path=Path("/tmp/test-session.json"),
            created_at=base_time - timedelta(hours=1),
            updated_at=base_time
        )

        # Modified after
        assert adapter.has_changed(ref, base_time - timedelta(minutes=1)) is True
        # Modified exact
        assert adapter.has_changed(ref, base_time) is False
        # Modified before
        assert adapter.has_changed(ref, base_time + timedelta(minutes=1)) is False
