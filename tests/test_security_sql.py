import pytest
from sagg.storage import SessionStore
from sagg.models import SourceTool, UnifiedSession
import datetime

def test_sql_injection_attempt_list_sessions(session_store):
    """Test if SQL injection via 'source' or 'project' parameter is possible in list_sessions."""
    # This shouldn't crash or return unexpected results if handled correctly by placeholders.
    # However, the concern is how the query string is BUILT.

    # Attempting to inject into 'source'
    malicious_source = "opencode' OR '1'='1"
    sessions = session_store.list_sessions(source=malicious_source)
    # If the injection worked and bypassed the placeholder, it might return all sessions.
    # But since it's using 'source = ?', it will just look for a source literally named "opencode' OR '1'='1"
    assert len(sessions) == 0

def test_sql_injection_attempt_get_facets(session_store):
    """Test if SQL injection is possible in get_facets."""
    malicious_project = "foo%') OR ('1'='1"
    facets = session_store.get_facets(project=malicious_project)
    assert len(facets) == 0

def test_sql_injection_attempt_get_unfaceted_sessions(session_store):
    """Test if SQL injection is possible in get_unfaceted_sessions."""
    malicious_project = "foo%') OR ('1'='1"
    sessions = session_store.get_unfaceted_sessions(project=malicious_project)
    # By default in empty store, it should be 0 anyway, but we want to ensure no crash
    assert len(sessions) == 0

def test_untrusted_condition_fragment(session_store):
    """Test that untrusted condition fragments raise ValueError."""
    with pytest.raises(ValueError, match="Untrusted SQL condition fragment"):
        # Manually calling the internal method to verify whitelist logic
        session_store._safe_join_conditions(["DELETE FROM sessions --"])
