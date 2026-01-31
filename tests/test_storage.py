import pytest
from sagg.storage import SessionStore


def test_save_and_get_session(session_store, sample_session):
    """Test saving and retrieving a session."""
    session_store.save_session(sample_session)

    # Retrieve
    retrieved = session_store.get_session(sample_session.id)
    assert retrieved is not None
    assert retrieved.id == sample_session.id
    assert retrieved.title == sample_session.title

    # Check if sessions file was created (in a real scenario, we'd mock the file write,
    # but SessionStore writes to a sessions/ dir)
    # Since we are using a temp dir in conftest, this is safe.


def test_list_sessions(session_store, sample_session):
    """Test listing sessions with filters."""
    session_store.save_session(sample_session)

    sessions = session_store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].id == sample_session.id

    # Test filter by source
    sessions = session_store.list_sessions(source="opencode")
    assert len(sessions) == 1

    sessions = session_store.list_sessions(source="claude")
    assert len(sessions) == 0


def test_search_sessions(session_store, sample_session):
    """Test FTS search."""
    session_store.save_session(sample_session)

    # Search for content in user message
    results = session_store.search_sessions("Hello")
    assert len(results) == 1
    assert results[0].id == sample_session.id

    # Search for content in assistant message
    results = session_store.search_sessions("Hi there")
    assert len(results) == 1

    # Search for non-existent content
    results = session_store.search_sessions("Banana")
    assert len(results) == 0


def test_session_exists(session_store, sample_session):
    """Test checking existence."""
    session_store.save_session(sample_session)
    assert session_store.session_exists(sample_session.source, sample_session.source_id)
    assert not session_store.session_exists("claude", "fake-id")
