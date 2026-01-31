from datetime import datetime, timedelta, timezone
from sagg.storage import SessionStore

def test_list_sessions_since(session_store, sample_session):
    """Test listing sessions with 'since' filter."""
    # Create an old session
    old_session = sample_session.model_copy()
    old_session.id = "old-session"
    # Hack: update the timestamp directly in DB since model_copy keeps original
    # But for testing list_sessions, we can just save it, then manually update DB
    session_store.save_session(old_session)
    
    # Update updated_at to 10 days ago
    ten_days_ago = int((datetime.now(timezone.utc) - timedelta(days=10)).timestamp())
    session_store.db.execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?", 
        (ten_days_ago, old_session.id)
    )
    
    # Create a new session
    new_session = sample_session.model_copy()
    new_session.id = "new-session"
    session_store.save_session(new_session)
    
    # Filter since 1 day ago
    since = datetime.now(timezone.utc) - timedelta(days=1)
    sessions = session_store.list_sessions(since=since)
    
    assert len(sessions) == 1
    assert sessions[0].id == new_session.id
