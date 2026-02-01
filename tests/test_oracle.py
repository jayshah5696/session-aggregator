"""Tests for the oracle semantic search feature."""

import pytest
from datetime import datetime, timezone, timedelta

from sagg.models import (
    UnifiedSession,
    Turn,
    Message,
    TextPart,
    SessionStats,
    SourceTool,
    generate_session_id,
)
from sagg.analytics.oracle import (
    OracleResult,
    search_history,
    extract_snippet,
    format_result,
)


@pytest.fixture
def oracle_sessions(session_store):
    """Create multiple sessions with searchable content for oracle tests."""
    sessions = []

    # Session 1: Rate limiting implementation
    session1 = UnifiedSession(
        id=generate_session_id(),
        source=SourceTool.OPENCODE,
        source_id="session-rate-limit",
        source_path="/tmp/test/session1.json",
        title="Implement API throttling",
        project_name="backend-api",
        project_path="/home/user/backend-api",
        created_at=datetime.now(timezone.utc) - timedelta(days=3),
        updated_at=datetime.now(timezone.utc) - timedelta(days=3),
        stats=SessionStats(turn_count=2, message_count=4, input_tokens=500, output_tokens=400),
        turns=[
            Turn(
                id="turn-1",
                index=0,
                started_at=datetime.now(timezone.utc) - timedelta(days=3),
                messages=[
                    Message(
                        id="msg-1",
                        role="user",
                        timestamp=datetime.now(timezone.utc) - timedelta(days=3),
                        parts=[TextPart(content="How do I add rate limiting to my API?")],
                    ),
                    Message(
                        id="msg-2",
                        role="assistant",
                        timestamp=datetime.now(timezone.utc) - timedelta(days=3),
                        parts=[TextPart(content="I'll help you add rate limiting middleware using Redis to track request counts per user. Set default limit to 100 req/min. First, let's install the dependencies.")],
                    ),
                ],
            ),
        ],
    )
    session_store.save_session(session1)
    sessions.append(session1)

    # Session 2: Rate limit bypass fix
    session2 = UnifiedSession(
        id=generate_session_id(),
        source=SourceTool.CLAUDE,
        source_id="session-rate-limit-fix",
        source_path="/tmp/test/session2.json",
        title="Fix rate limit bypass bug",
        project_name="backend-api",
        project_path="/home/user/backend-api",
        created_at=datetime.now(timezone.utc) - timedelta(weeks=2),
        updated_at=datetime.now(timezone.utc) - timedelta(weeks=2),
        stats=SessionStats(turn_count=1, message_count=2, input_tokens=300, output_tokens=250),
        turns=[
            Turn(
                id="turn-1",
                index=0,
                started_at=datetime.now(timezone.utc) - timedelta(weeks=2),
                messages=[
                    Message(
                        id="msg-1",
                        role="user",
                        timestamp=datetime.now(timezone.utc) - timedelta(weeks=2),
                        parts=[TextPart(content="The rate limiter isn't checking authenticated users properly")],
                    ),
                    Message(
                        id="msg-2",
                        role="assistant",
                        timestamp=datetime.now(timezone.utc) - timedelta(weeks=2),
                        parts=[TextPart(content="I see the issue - the rate limiter wasn't checking authenticated users. Added check for JWT token before applying limits. This ensures all users go through rate limiting.")],
                    ),
                ],
            ),
        ],
    )
    session_store.save_session(session2)
    sessions.append(session2)

    # Session 3: TypeError fix (unrelated topic)
    session3 = UnifiedSession(
        id=generate_session_id(),
        source=SourceTool.OPENCODE,
        source_id="session-typeerror",
        source_path="/tmp/test/session3.json",
        title="Fix TypeError in user service",
        project_name="user-service",
        project_path="/home/user/user-service",
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
        updated_at=datetime.now(timezone.utc) - timedelta(days=1),
        stats=SessionStats(turn_count=1, message_count=2, input_tokens=200, output_tokens=150),
        turns=[
            Turn(
                id="turn-1",
                index=0,
                started_at=datetime.now(timezone.utc) - timedelta(days=1),
                messages=[
                    Message(
                        id="msg-1",
                        role="user",
                        timestamp=datetime.now(timezone.utc) - timedelta(days=1),
                        parts=[TextPart(content="I'm getting TypeError: Cannot read property 'name' of undefined")],
                    ),
                    Message(
                        id="msg-2",
                        role="assistant",
                        timestamp=datetime.now(timezone.utc) - timedelta(days=1),
                        parts=[TextPart(content="The TypeError occurs because user object is undefined. You need to add a null check before accessing user.name. Here's the fix...")],
                    ),
                ],
            ),
        ],
    )
    session_store.save_session(session3)
    sessions.append(session3)

    return sessions


class TestOracleSearch:
    """Tests for the oracle search functionality."""

    def test_search_returns_relevant_results(self, session_store, oracle_sessions):
        """Test that searching finds related sessions."""
        results = search_history(session_store, "rate limiting", limit=10)

        assert len(results) >= 1
        # Should find sessions mentioning rate limiting
        session_ids = [r.session_id for r in results]
        assert any("rate" in session_store.get_session(sid).title.lower() for sid in session_ids if session_store.get_session(sid).title)

    def test_search_ranking_by_relevance(self, session_store, oracle_sessions):
        """Test that results are ranked by relevance score."""
        results = search_history(session_store, "rate limit", limit=10)

        # Should have relevance scores
        assert all(r.relevance_score is not None for r in results)

        # Scores should be in descending order (most relevant first)
        scores = [r.relevance_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_includes_matched_text(self, session_store, oracle_sessions):
        """Test that results include a snippet showing the match."""
        results = search_history(session_store, "TypeError", limit=5)

        assert len(results) >= 1
        # The matched_text should contain context around the match
        assert any("TypeError" in r.matched_text or "typeerror" in r.matched_text.lower() for r in results)

    def test_search_respects_limit(self, session_store, oracle_sessions):
        """Test that limit parameter restricts result count."""
        results = search_history(session_store, "rate", limit=1)
        assert len(results) <= 1

        results = search_history(session_store, "rate", limit=5)
        assert len(results) <= 5

    def test_empty_results_for_no_match(self, session_store, oracle_sessions):
        """Test that searching for non-existent content returns empty list."""
        results = search_history(session_store, "xyznonexistent123", limit=10)
        assert len(results) == 0

    def test_search_includes_session_metadata(self, session_store, oracle_sessions):
        """Test that results include project and timestamp info."""
        results = search_history(session_store, "rate limiting", limit=5)

        assert len(results) >= 1
        result = results[0]

        # Should have all metadata fields
        assert result.session_id is not None
        assert result.title is not None
        assert result.project is not None
        assert result.timestamp is not None


class TestExtractSnippet:
    """Tests for the snippet extraction function."""

    def test_extract_snippet_basic(self):
        """Test basic snippet extraction around a match."""
        content = "This is a long piece of text that contains the word rate limiting somewhere in the middle of it."
        snippet = extract_snippet(content, "rate limiting", context_chars=20)

        assert "rate limiting" in snippet
        assert len(snippet) <= 20 * 2 + len("rate limiting") + 10  # Allow some buffer

    def test_extract_snippet_at_start(self):
        """Test snippet extraction when match is at the start."""
        content = "rate limiting is important for API security and performance."
        snippet = extract_snippet(content, "rate limiting", context_chars=20)

        assert snippet.startswith("rate limiting") or "rate limiting" in snippet

    def test_extract_snippet_at_end(self):
        """Test snippet extraction when match is at the end."""
        content = "For API security, you should implement rate limiting"
        snippet = extract_snippet(content, "rate limiting", context_chars=20)

        assert "rate limiting" in snippet

    def test_extract_snippet_case_insensitive(self):
        """Test that snippet extraction is case insensitive."""
        content = "You should implement RATE LIMITING for your API"
        snippet = extract_snippet(content, "rate limiting", context_chars=20)

        # Should find the match regardless of case
        assert "RATE LIMITING" in snippet or "rate limiting" in snippet.lower()

    def test_extract_snippet_no_match(self):
        """Test snippet extraction when there's no match."""
        content = "This text doesn't contain the search term"
        snippet = extract_snippet(content, "xyznonexistent", context_chars=20)

        # Should return empty or a truncated version of content
        assert snippet == "" or len(snippet) <= 50

    def test_extract_snippet_with_ellipsis(self):
        """Test that snippets include ellipsis when truncated."""
        content = "A" * 100 + "rate limiting" + "B" * 100
        snippet = extract_snippet(content, "rate limiting", context_chars=20)

        # Should have ellipsis when text is truncated
        assert "..." in snippet or len(snippet) < len(content)


class TestFormatResult:
    """Tests for result formatting."""

    def test_format_result_includes_title(self):
        """Test that formatted result includes the title."""
        result = OracleResult(
            session_id="test-id",
            title="Fix rate limit bypass",
            relevance_score=0.85,
            matched_text="...rate limiting middleware...",
            project="backend-api",
            timestamp=datetime.now(timezone.utc),
        )

        formatted = format_result(result)

        assert "Fix rate limit bypass" in formatted

    def test_format_result_includes_relevance(self):
        """Test that formatted result shows relevance as percentage."""
        result = OracleResult(
            session_id="test-id",
            title="Test Session",
            relevance_score=0.95,
            matched_text="test content",
            project="test-project",
            timestamp=datetime.now(timezone.utc),
        )

        formatted = format_result(result)

        # Should show relevance as percentage (95%)
        assert "95%" in formatted or "95" in formatted

    def test_format_result_includes_project(self):
        """Test that formatted result includes project name."""
        result = OracleResult(
            session_id="test-id",
            title="Test Session",
            relevance_score=0.75,
            matched_text="test content",
            project="my-awesome-project",
            timestamp=datetime.now(timezone.utc),
        )

        formatted = format_result(result)

        assert "my-awesome-project" in formatted

    def test_format_result_includes_time_ago(self):
        """Test that formatted result shows relative time."""
        result = OracleResult(
            session_id="test-id",
            title="Test Session",
            relevance_score=0.75,
            matched_text="test content",
            project="test-project",
            timestamp=datetime.now(timezone.utc) - timedelta(days=3),
        )

        formatted = format_result(result)

        # Should show "3 days ago" or similar
        assert "ago" in formatted.lower() or "3" in formatted


class TestOracleResultDataclass:
    """Tests for the OracleResult dataclass."""

    def test_oracle_result_creation(self):
        """Test that OracleResult can be created with all fields."""
        result = OracleResult(
            session_id="session-123",
            title="My Session",
            relevance_score=0.9,
            matched_text="some matched text",
            project="my-project",
            timestamp=datetime.now(timezone.utc),
        )

        assert result.session_id == "session-123"
        assert result.title == "My Session"
        assert result.relevance_score == 0.9
        assert result.matched_text == "some matched text"
        assert result.project == "my-project"
        assert result.timestamp is not None
