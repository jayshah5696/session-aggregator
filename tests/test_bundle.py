"""Tests for portable session bundles."""

import gzip
import json
import pytest
import tempfile
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
from sagg.storage import SessionStore


@pytest.fixture
def temp_bundle_dir():
    """Create a temporary directory for bundle files."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


@pytest.fixture
def temp_store():
    """Create a temporary SessionStore."""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test_db.sqlite"
    sessions_dir = Path(temp_dir) / "sessions"
    store = SessionStore(db_path=db_path, sessions_dir=sessions_dir)
    yield store
    store.close()
    shutil.rmtree(temp_dir)


@pytest.fixture
def sample_sessions():
    """Create multiple sample sessions for testing."""
    now = datetime.now(timezone.utc)
    sessions = []

    for i in range(5):
        session = UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.OPENCODE if i % 2 == 0 else SourceTool.CLAUDE,
            source_id=f"test-session-{i}",
            source_path=f"/tmp/test/session-{i}.json",
            title=f"Test Session {i}",
            project_name="test-project" if i < 3 else "other-project",
            project_path="/tmp/test-project" if i < 3 else "/tmp/other-project",
            created_at=now - timedelta(days=i),
            updated_at=now - timedelta(days=i),
            stats=SessionStats(
                turn_count=1,
                message_count=2,
                input_tokens=100 * (i + 1),
                output_tokens=50 * (i + 1),
            ),
            turns=[
                Turn(
                    id=f"turn-{i}-1",
                    index=0,
                    started_at=now - timedelta(days=i),
                    messages=[
                        Message(
                            id=f"msg-{i}-1",
                            role="user",
                            timestamp=now - timedelta(days=i),
                            parts=[TextPart(content=f"Hello from session {i}")],
                        ),
                        Message(
                            id=f"msg-{i}-2",
                            role="assistant",
                            timestamp=now - timedelta(days=i),
                            parts=[TextPart(content=f"Response for session {i}")],
                            usage=TokenUsage(
                                input_tokens=100 * (i + 1),
                                output_tokens=50 * (i + 1),
                            ),
                        ),
                    ],
                )
            ],
        )
        sessions.append(session)

    return sessions


class TestBundleExport:
    """Tests for exporting sessions to bundles."""

    def test_export_creates_bundle_file(self, temp_store, sample_sessions, temp_bundle_dir):
        """Test that export creates a valid bundle file."""
        from sagg.bundle import export_bundle

        # Save sessions to store
        for session in sample_sessions:
            temp_store.save_session(session)

        bundle_path = temp_bundle_dir / "test.sagg"
        count = export_bundle(temp_store, bundle_path)

        assert count == 5
        assert bundle_path.exists()
        assert bundle_path.stat().st_size > 0

    def test_export_bundle_is_gzipped(self, temp_store, sample_sessions, temp_bundle_dir):
        """Test that the bundle is gzip compressed."""
        from sagg.bundle import export_bundle

        for session in sample_sessions:
            temp_store.save_session(session)

        bundle_path = temp_bundle_dir / "test.sagg"
        export_bundle(temp_store, bundle_path)

        # Should be able to decompress with gzip
        with gzip.open(bundle_path, "rt") as f:
            content = f.read()
            lines = content.strip().split("\n")
            assert len(lines) >= 7  # header + 5 sessions + footer

    def test_export_bundle_format(self, temp_store, sample_sessions, temp_bundle_dir):
        """Test the bundle format (header, sessions, footer)."""
        from sagg.bundle import export_bundle

        for session in sample_sessions:
            temp_store.save_session(session)

        bundle_path = temp_bundle_dir / "test.sagg"
        export_bundle(temp_store, bundle_path)

        with gzip.open(bundle_path, "rt") as f:
            lines = [json.loads(line) for line in f.read().strip().split("\n")]

        # First line is header
        header = lines[0]
        assert header["type"] == "header"
        assert header["version"] == "1.0.0"
        assert "machine_id" in header
        assert "exported_at" in header
        assert header["session_count"] == 5

        # Middle lines are sessions
        sessions = [l for l in lines if l.get("type") == "session"]
        assert len(sessions) == 5

        # Last line is footer
        footer = lines[-1]
        assert footer["type"] == "footer"
        assert footer["session_count"] == 5
        assert "checksum" in footer
        assert footer["checksum"].startswith("sha256:")

    def test_export_with_since_filter(self, temp_store, sample_sessions, temp_bundle_dir):
        """Test exporting sessions with since filter."""
        from sagg.bundle import export_bundle

        for session in sample_sessions:
            temp_store.save_session(session)

        bundle_path = temp_bundle_dir / "recent.sagg"
        # Use 2.5 days to avoid boundary issues with exact timestamps
        since = datetime.now(timezone.utc) - timedelta(days=2, hours=12)
        count = export_bundle(temp_store, bundle_path, since=since)

        # Should only export sessions from last ~2.5 days (indices 0, 1, 2)
        assert count == 3

    def test_export_with_project_filter(self, temp_store, sample_sessions, temp_bundle_dir):
        """Test exporting sessions filtered by project."""
        from sagg.bundle import export_bundle

        for session in sample_sessions:
            temp_store.save_session(session)

        bundle_path = temp_bundle_dir / "project.sagg"
        count = export_bundle(temp_store, bundle_path, project="test-project")

        # Should only export sessions with project_name "test-project"
        assert count == 3

    def test_export_with_source_filter(self, temp_store, sample_sessions, temp_bundle_dir):
        """Test exporting sessions filtered by source."""
        from sagg.bundle import export_bundle

        for session in sample_sessions:
            temp_store.save_session(session)

        bundle_path = temp_bundle_dir / "opencode.sagg"
        count = export_bundle(temp_store, bundle_path, source="opencode")

        # Sessions 0, 2, 4 are opencode
        assert count == 3

    def test_export_empty_store(self, temp_store, temp_bundle_dir):
        """Test exporting from an empty store."""
        from sagg.bundle import export_bundle

        bundle_path = temp_bundle_dir / "empty.sagg"
        count = export_bundle(temp_store, bundle_path)

        assert count == 0
        assert bundle_path.exists()


class TestBundleImport:
    """Tests for importing sessions from bundles."""

    def test_import_sessions(self, temp_store, sample_sessions, temp_bundle_dir):
        """Test importing sessions from a bundle."""
        from sagg.bundle import export_bundle, import_bundle

        # Export from source store
        source_dir = tempfile.mkdtemp()
        source_store = SessionStore(
            db_path=Path(source_dir) / "source.sqlite",
            sessions_dir=Path(source_dir) / "sessions",
        )

        for session in sample_sessions:
            source_store.save_session(session)

        bundle_path = temp_bundle_dir / "transfer.sagg"
        export_bundle(source_store, bundle_path)
        source_store.close()
        shutil.rmtree(source_dir)

        # Import to target store
        result = import_bundle(temp_store, bundle_path)

        assert result["imported"] == 5
        assert result["skipped"] == 0
        assert result["errors"] == []

        # Verify sessions are in store
        sessions = temp_store.list_sessions(limit=10)
        assert len(sessions) == 5

    def test_import_deduplication_skip(self, temp_store, sample_sessions, temp_bundle_dir):
        """Test that duplicate sessions are skipped by default."""
        from sagg.bundle import export_bundle, import_bundle

        # Save some sessions first
        for session in sample_sessions[:2]:
            temp_store.save_session(session)

        # Export all sessions
        source_dir = tempfile.mkdtemp()
        source_store = SessionStore(
            db_path=Path(source_dir) / "source.sqlite",
            sessions_dir=Path(source_dir) / "sessions",
        )
        for session in sample_sessions:
            source_store.save_session(session)

        bundle_path = temp_bundle_dir / "with_dups.sagg"
        export_bundle(source_store, bundle_path)
        source_store.close()
        shutil.rmtree(source_dir)

        # Import with skip strategy (default)
        result = import_bundle(temp_store, bundle_path, strategy="skip")

        assert result["imported"] == 3  # Only new ones
        assert result["skipped"] == 2  # Duplicates

    def test_import_deduplication_replace(self, temp_store, sample_sessions, temp_bundle_dir):
        """Test that duplicate sessions can be replaced."""
        from sagg.bundle import export_bundle, import_bundle

        # Save a session with modified title
        modified_session = sample_sessions[0].model_copy()
        modified_session.title = "Old Title"
        temp_store.save_session(modified_session)

        # Export session with new title
        source_dir = tempfile.mkdtemp()
        source_store = SessionStore(
            db_path=Path(source_dir) / "source.sqlite",
            sessions_dir=Path(source_dir) / "sessions",
        )
        source_store.save_session(sample_sessions[0])  # Has "Test Session 0" title

        bundle_path = temp_bundle_dir / "replace.sagg"
        export_bundle(source_store, bundle_path)
        source_store.close()
        shutil.rmtree(source_dir)

        # Import with replace strategy
        result = import_bundle(temp_store, bundle_path, strategy="replace")

        assert result["imported"] == 1
        assert result["skipped"] == 0

        # Verify session was replaced
        session = temp_store.get_session(sample_sessions[0].id)
        assert session is not None
        assert session.title == "Test Session 0"

    def test_import_dry_run(self, temp_store, sample_sessions, temp_bundle_dir):
        """Test dry run mode doesn't modify the store."""
        from sagg.bundle import export_bundle, import_bundle

        source_dir = tempfile.mkdtemp()
        source_store = SessionStore(
            db_path=Path(source_dir) / "source.sqlite",
            sessions_dir=Path(source_dir) / "sessions",
        )
        for session in sample_sessions:
            source_store.save_session(session)

        bundle_path = temp_bundle_dir / "dry_run.sagg"
        export_bundle(source_store, bundle_path)
        source_store.close()
        shutil.rmtree(source_dir)

        # Dry run import
        result = import_bundle(temp_store, bundle_path, dry_run=True)

        assert result["imported"] == 5  # Would import
        assert result["skipped"] == 0

        # But store is still empty
        sessions = temp_store.list_sessions(limit=10)
        assert len(sessions) == 0

    def test_import_tracks_provenance(self, temp_store, sample_sessions, temp_bundle_dir):
        """Test that imported sessions track provenance info."""
        from sagg.bundle import export_bundle, import_bundle, get_machine_id

        source_dir = tempfile.mkdtemp()
        source_store = SessionStore(
            db_path=Path(source_dir) / "source.sqlite",
            sessions_dir=Path(source_dir) / "sessions",
        )
        source_store.save_session(sample_sessions[0])

        bundle_path = temp_bundle_dir / "provenance.sagg"
        export_bundle(source_store, bundle_path)
        source_machine_id = get_machine_id()  # Get source machine ID before cleanup
        source_store.close()
        shutil.rmtree(source_dir)

        # Import to target store
        import_bundle(temp_store, bundle_path)

        # Check provenance info in database
        cursor = temp_store.db.execute(
            "SELECT origin_machine, import_source, imported_at FROM sessions WHERE id = ?",
            (sample_sessions[0].id,),
        )
        row = cursor.fetchone()

        assert row is not None
        assert row["origin_machine"] == source_machine_id
        assert row["import_source"] == str(bundle_path)
        assert row["imported_at"] is not None


class TestBundleIntegrity:
    """Tests for bundle integrity verification."""

    def test_verify_valid_bundle(self, temp_store, sample_sessions, temp_bundle_dir):
        """Test verifying a valid bundle."""
        from sagg.bundle import export_bundle, verify_bundle

        for session in sample_sessions:
            temp_store.save_session(session)

        bundle_path = temp_bundle_dir / "valid.sagg"
        export_bundle(temp_store, bundle_path)

        assert verify_bundle(bundle_path) is True

    def test_verify_corrupted_bundle(self, temp_store, sample_sessions, temp_bundle_dir):
        """Test verifying a corrupted bundle."""
        from sagg.bundle import export_bundle, verify_bundle

        for session in sample_sessions:
            temp_store.save_session(session)

        bundle_path = temp_bundle_dir / "corrupted.sagg"
        export_bundle(temp_store, bundle_path)

        # Corrupt the bundle by modifying a byte
        with gzip.open(bundle_path, "rb") as f:
            content = f.read()

        corrupted = content[:-100] + b"CORRUPTED" + content[-91:]

        with gzip.open(bundle_path, "wb") as f:
            f.write(corrupted)

        assert verify_bundle(bundle_path) is False

    def test_verify_missing_footer(self, temp_store, sample_sessions, temp_bundle_dir):
        """Test verifying a bundle with missing footer."""
        from sagg.bundle import verify_bundle

        for session in sample_sessions[:1]:
            temp_store.save_session(session)

        bundle_path = temp_bundle_dir / "no_footer.sagg"

        # Manually create a bundle without footer
        with gzip.open(bundle_path, "wt") as f:
            f.write(json.dumps({"type": "header", "version": "1.0.0"}) + "\n")
            f.write(json.dumps({"type": "session", "id": "test"}) + "\n")

        assert verify_bundle(bundle_path) is False


class TestMachineId:
    """Tests for machine ID functionality."""

    def test_get_machine_id_creates_id(self, tmp_path, monkeypatch):
        """Test that machine ID is created if it doesn't exist."""
        from sagg.bundle import get_machine_id

        # Patch home directory
        monkeypatch.setenv("HOME", str(tmp_path))

        machine_id = get_machine_id()

        assert machine_id is not None
        assert len(machine_id) == 36  # UUID format

        # Should be persisted
        machine_id_path = tmp_path / ".sagg" / "machine_id"
        assert machine_id_path.exists()
        assert machine_id_path.read_text().strip() == machine_id

    def test_get_machine_id_returns_existing(self, tmp_path, monkeypatch):
        """Test that existing machine ID is returned."""
        from sagg.bundle import get_machine_id

        # Patch home directory
        monkeypatch.setenv("HOME", str(tmp_path))

        # Create existing machine ID
        machine_id_path = tmp_path / ".sagg" / "machine_id"
        machine_id_path.parent.mkdir(parents=True)
        machine_id_path.write_text("existing-machine-id-123")

        machine_id = get_machine_id()

        assert machine_id == "existing-machine-id-123"
