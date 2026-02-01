"""Tests for friction points detection."""

import pytest
from datetime import datetime, timedelta, timezone

from sagg.analytics.friction import (
    FrictionType,
    FrictionPoint,
    analyze_retries,
    analyze_error_rate,
    analyze_back_and_forth,
    calculate_friction_score,
    detect_friction_points,
)
from sagg.models import (
    UnifiedSession,
    Turn,
    Message,
    TextPart,
    ToolCallPart,
    ToolResultPart,
    SessionStats,
    SourceTool,
    generate_session_id,
    TokenUsage,
)


def create_session_with_tool_calls(
    tool_calls: list[tuple[str, bool]],
    user_messages: list[str] | None = None,
) -> UnifiedSession:
    """Helper to create sessions with specified tool calls.

    Args:
        tool_calls: List of (tool_name, is_error) tuples.
        user_messages: Optional list of user message contents.

    Returns:
        UnifiedSession with the specified tool calls.
    """
    now = datetime.now(timezone.utc)
    messages = []

    # Add initial user message
    messages.append(
        Message(
            id="msg-user-0",
            role="user",
            timestamp=now,
            parts=[TextPart(content=user_messages[0] if user_messages else "Do something")],
        )
    )

    # Add tool calls
    for i, (tool_name, is_error) in enumerate(tool_calls):
        messages.append(
            Message(
                id=f"msg-assistant-{i}",
                role="assistant",
                timestamp=now + timedelta(seconds=i),
                parts=[
                    ToolCallPart(
                        tool_name=tool_name,
                        tool_id=f"tool-{i}",
                        input={"command": "test"},
                    )
                ],
            )
        )
        messages.append(
            Message(
                id=f"msg-tool-{i}",
                role="tool",
                timestamp=now + timedelta(seconds=i, milliseconds=500),
                parts=[
                    ToolResultPart(
                        tool_id=f"tool-{i}",
                        output="error" if is_error else "success",
                        is_error=is_error,
                    )
                ],
            )
        )

    # Add additional user messages if provided
    if user_messages and len(user_messages) > 1:
        for j, content in enumerate(user_messages[1:], start=1):
            messages.append(
                Message(
                    id=f"msg-user-{j}",
                    role="user",
                    timestamp=now + timedelta(seconds=len(tool_calls) + j),
                    parts=[TextPart(content=content)],
                )
            )
            # Add a short assistant response after each user message
            messages.append(
                Message(
                    id=f"msg-assistant-reply-{j}",
                    role="assistant",
                    timestamp=now + timedelta(seconds=len(tool_calls) + j, milliseconds=500),
                    parts=[TextPart(content="I'll fix that.")],
                )
            )

    turn = Turn(
        id="turn-0",
        index=0,
        started_at=now,
        ended_at=now + timedelta(seconds=len(tool_calls) + 10),
        messages=messages,
    )

    return UnifiedSession(
        id=generate_session_id(),
        source=SourceTool.OPENCODE,
        source_id=f"test-session-{generate_session_id()[:8]}",
        source_path="/tmp/test/session.json",
        title="Test Session with Tool Calls",
        project_name="test-project",
        project_path="/tmp/test-project",
        created_at=now,
        updated_at=now,
        stats=SessionStats(
            turn_count=1,
            message_count=len(messages),
            input_tokens=1000,
            output_tokens=500,
            tool_call_count=len(tool_calls),
        ),
        turns=[turn],
    )


class TestAnalyzeRetries:
    """Tests for analyze_retries function."""

    def test_no_retries(self):
        """Test with no consecutive retries."""
        # Different tools called in sequence
        session = create_session_with_tool_calls([
            ("bash", False),
            ("read", False),
            ("write", False),
        ])
        retry_count, tools = analyze_retries(session)
        assert retry_count == 0
        assert tools == []

    def test_sequential_retries_same_tool(self):
        """Test detecting sequential retries of the same tool."""
        # Same tool called multiple times
        session = create_session_with_tool_calls([
            ("bash", True),
            ("bash", True),
            ("bash", True),
            ("bash", False),
        ])
        retry_count, tools = analyze_retries(session)
        assert retry_count == 3  # 4 calls - 1 = 3 retries
        assert "bash" in tools

    def test_multiple_retry_sequences(self):
        """Test detecting multiple sequences of retries."""
        session = create_session_with_tool_calls([
            ("bash", True),
            ("bash", True),
            ("read", False),
            ("write", True),
            ("write", True),
            ("write", False),
        ])
        retry_count, tools = analyze_retries(session)
        # bash: 1 retry, write: 2 retries
        assert retry_count == 3
        assert "bash" in tools
        assert "write" in tools

    def test_empty_session(self):
        """Test with a session with no tool calls."""
        session = UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.OPENCODE,
            source_id="empty-session",
            source_path="/tmp/test/session.json",
            title="Empty Session",
            project_name="test-project",
            project_path="/tmp/test-project",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            stats=SessionStats(),
            turns=[],
        )
        retry_count, tools = analyze_retries(session)
        assert retry_count == 0
        assert tools == []


class TestAnalyzeErrorRate:
    """Tests for analyze_error_rate function."""

    def test_no_errors(self):
        """Test with no errors."""
        session = create_session_with_tool_calls([
            ("bash", False),
            ("read", False),
            ("write", False),
        ])
        error_rate = analyze_error_rate(session)
        assert error_rate == 0.0

    def test_all_errors(self):
        """Test with all errors."""
        session = create_session_with_tool_calls([
            ("bash", True),
            ("read", True),
            ("write", True),
        ])
        error_rate = analyze_error_rate(session)
        assert error_rate == 1.0

    def test_partial_errors(self):
        """Test with some errors."""
        session = create_session_with_tool_calls([
            ("bash", True),
            ("bash", False),
            ("read", True),
            ("read", False),
        ])
        error_rate = analyze_error_rate(session)
        assert error_rate == 0.5

    def test_no_tool_calls(self):
        """Test with no tool calls returns 0."""
        session = UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.OPENCODE,
            source_id="empty-session",
            source_path="/tmp/test/session.json",
            title="Empty Session",
            project_name="test-project",
            project_path="/tmp/test-project",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            stats=SessionStats(),
            turns=[],
        )
        error_rate = analyze_error_rate(session)
        assert error_rate == 0.0


class TestAnalyzeBackAndForth:
    """Tests for analyze_back_and_forth function."""

    def test_no_back_and_forth(self):
        """Test with no short user messages."""
        session = create_session_with_tool_calls(
            [("bash", False)],
            user_messages=[
                "Please implement a complete authentication system with OAuth2 support.",
            ],
        )
        count = analyze_back_and_forth(session)
        assert count == 0

    def test_multiple_short_corrections(self):
        """Test detecting multiple short user messages."""
        session = create_session_with_tool_calls(
            [("bash", False)],
            user_messages=[
                "Please fix the bug.",
                "No, wrong file.",  # Short correction
                "Try again",  # Short correction
                "Use port 8080",  # Short correction
                "Almost",  # Short correction
                "Done",  # Short correction
            ],
        )
        count = analyze_back_and_forth(session)
        # Should detect the short messages (< 50 chars)
        assert count >= 4  # At least 4 short messages

    def test_counts_only_short_messages(self):
        """Test that only short messages are counted."""
        session = create_session_with_tool_calls(
            [("bash", False)],
            user_messages=[
                "A very long first message that explains what needs to be done in great detail.",
                "No",  # Short
                "Another very detailed message with complete context about what should happen.",
                "Fix",  # Short
            ],
        )
        count = analyze_back_and_forth(session)
        assert count == 2  # Only 2 short messages


class TestCalculateFrictionScore:
    """Tests for calculate_friction_score function."""

    def test_no_friction(self):
        """Test with no friction indicators."""
        score = calculate_friction_score(
            retry_count=0,
            error_rate=0.0,
            back_forth_count=0,
        )
        assert score == 0.0

    def test_high_friction(self):
        """Test with high friction indicators."""
        score = calculate_friction_score(
            retry_count=10,
            error_rate=0.8,
            back_forth_count=10,
        )
        assert score >= 0.8
        assert score <= 1.0

    def test_medium_friction(self):
        """Test with medium friction indicators."""
        score = calculate_friction_score(
            retry_count=4,
            error_rate=0.3,
            back_forth_count=3,
        )
        assert 0.3 <= score <= 0.7

    def test_score_bounded(self):
        """Test that score is bounded between 0 and 1."""
        # Even with extreme values
        score = calculate_friction_score(
            retry_count=100,
            error_rate=1.0,
            back_forth_count=100,
        )
        assert 0.0 <= score <= 1.0


class TestDetectFrictionPoints:
    """Tests for detect_friction_points function."""

    def test_empty_store(self, session_store):
        """Test with no sessions."""
        friction_points = detect_friction_points(session_store)
        assert friction_points == []

    def test_detects_high_retry_friction(self, session_store):
        """Test detecting sessions with high retry count."""
        # Create a session with many retries
        session = create_session_with_tool_calls([
            ("bash", True),
            ("bash", True),
            ("bash", True),
            ("bash", True),
            ("bash", False),
        ])
        session_store.save_session(session)

        friction_points = detect_friction_points(
            session_store,
            retry_threshold=3,
        )

        assert len(friction_points) == 1
        assert FrictionType.HIGH_RETRIES in friction_points[0].friction_types

    def test_detects_high_error_rate(self, session_store):
        """Test detecting sessions with high error rate."""
        # Create a session with high error rate
        session = create_session_with_tool_calls([
            ("bash", True),
            ("read", True),
            ("write", True),
            ("grep", False),
        ])
        session_store.save_session(session)

        friction_points = detect_friction_points(
            session_store,
            error_threshold=0.5,
        )

        assert len(friction_points) == 1
        assert FrictionType.ERROR_RATE in friction_points[0].friction_types

    def test_since_filter(self, session_store):
        """Test that since filter is applied."""
        now = datetime.now(timezone.utc)

        # Create an old session
        old_session = create_session_with_tool_calls([
            ("bash", True),
            ("bash", True),
            ("bash", True),
            ("bash", False),
        ])
        # Modify timestamps to make it old
        old_session = UnifiedSession(
            **{
                **old_session.model_dump(),
                "created_at": now - timedelta(days=30),
                "updated_at": now - timedelta(days=30),
            }
        )
        session_store.save_session(old_session)

        # Create a recent session without friction
        recent_session = create_session_with_tool_calls([
            ("bash", False),
        ])
        session_store.save_session(recent_session)

        # With since=7d, should not find the old session
        friction_points = detect_friction_points(
            session_store,
            since=now - timedelta(days=7),
            retry_threshold=3,
        )

        # The old session should be excluded, the recent one has no friction
        assert len(friction_points) == 0

    def test_sorted_by_score(self, session_store):
        """Test that results are sorted by friction score descending."""
        # Create a session with high friction
        high_friction = create_session_with_tool_calls([
            ("bash", True),
            ("bash", True),
            ("bash", True),
            ("bash", True),
            ("bash", True),
            ("bash", True),
            ("read", True),
            ("read", True),
        ])

        session_store.save_session(high_friction)

        friction_points = detect_friction_points(session_store, retry_threshold=2)

        # At least one friction point should be detected
        assert len(friction_points) >= 1

        # If multiple, should be sorted by score descending
        for i in range(len(friction_points) - 1):
            assert friction_points[i].friction_score >= friction_points[i + 1].friction_score


class TestFrictionPoint:
    """Tests for FrictionPoint dataclass."""

    def test_creation(self):
        """Test creating a FrictionPoint."""
        fp = FrictionPoint(
            session_id="test-id",
            title="Test Session",
            friction_types=[FrictionType.HIGH_RETRIES, FrictionType.ERROR_RATE],
            friction_score=0.75,
            details={"retry_count": 5, "error_rate": 0.4},
            project="test-project",
        )

        assert fp.session_id == "test-id"
        assert fp.title == "Test Session"
        assert len(fp.friction_types) == 2
        assert fp.friction_score == 0.75
        assert fp.details["retry_count"] == 5


class TestFrictionType:
    """Tests for FrictionType enum."""

    def test_values(self):
        """Test that all expected friction types exist."""
        assert FrictionType.HIGH_RETRIES.value == "high_retries"
        assert FrictionType.ERROR_RATE.value == "high_errors"
        assert FrictionType.BACK_AND_FORTH.value == "back_and_forth"
        assert FrictionType.LOW_EFFICIENCY.value == "low_efficiency"
