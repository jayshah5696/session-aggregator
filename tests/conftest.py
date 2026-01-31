import pytest
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timezone
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
from sagg.storage import SessionStore, Database


@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test_db.sqlite"
    yield db_path
    shutil.rmtree(temp_dir)


@pytest.fixture
def session_store(temp_db_path):
    """Create a SessionStore with a temporary database."""
    store = SessionStore(db_path=temp_db_path)
    yield store
    store.close()


@pytest.fixture
def sample_session():
    """Create a sample UnifiedSession for testing."""
    return UnifiedSession(
        id=generate_session_id(),
        source=SourceTool.OPENCODE,
        source_id="test-session-1",
        source_path="/tmp/test/session.json",
        title="Test Session",
        project_name="test-project",
        project_path="/tmp/test-project",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        stats=SessionStats(turn_count=1, message_count=2, input_tokens=100, output_tokens=50),
        turns=[
            Turn(
                id="turn-1",
                index=0,
                started_at=datetime.now(timezone.utc),
                messages=[
                    Message(
                        id="msg-1",
                        role="user",
                        timestamp=datetime.now(timezone.utc),
                        parts=[TextPart(content="Hello")],
                    ),
                    Message(
                        id="msg-2",
                        role="assistant",
                        timestamp=datetime.now(timezone.utc),
                        parts=[TextPart(content="Hi there")],
                        usage=TokenUsage(input_tokens=100, output_tokens=50),
                    ),
                ],
            )
        ],
    )
