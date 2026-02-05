"""Tests for heuristic-based session facet extraction."""

import pytest
from datetime import datetime, timedelta, timezone

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
from sagg.analytics.insights.heuristic import (
    analyze_session,
    _extract_goal,
    _classify_task_type,
    _assess_outcome,
    _classify_session_type,
    _assess_complexity,
    _detect_primary_language,
    _detect_files_pattern,
    _generate_summary,
    _extract_goal_categories,
    EXTENSION_TO_LANGUAGE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _make_empty_session(title: str | None = "Empty Session") -> UnifiedSession:
    """Create a session with no turns."""
    now = datetime.now(timezone.utc)
    return UnifiedSession(
        id=generate_session_id(),
        source=SourceTool.OPENCODE,
        source_id="empty-session",
        source_path="/tmp/test/session.json",
        title=title,
        project_name="test-project",
        project_path="/tmp/test-project",
        created_at=now,
        updated_at=now,
        stats=SessionStats(),
        turns=[],
    )


def _make_session_with_turns(
    turn_count: int,
    *,
    user_message: str = "Do something",
    title: str | None = "Multi-turn Session",
    files_modified: list[str] | None = None,
    tool_call_count: int = 0,
) -> UnifiedSession:
    """Create a session with a specific number of turns.

    Each turn has a user message and an assistant reply.
    """
    now = datetime.now(timezone.utc)
    turns = []
    for i in range(turn_count):
        msgs = [
            Message(
                id=f"msg-user-{i}",
                role="user",
                timestamp=now + timedelta(seconds=i * 2),
                parts=[TextPart(content=user_message if i == 0 else f"Follow up {i}")],
            ),
            Message(
                id=f"msg-assistant-{i}",
                role="assistant",
                timestamp=now + timedelta(seconds=i * 2 + 1),
                parts=[TextPart(content=f"Response {i}")],
                usage=TokenUsage(input_tokens=100, output_tokens=50),
            ),
        ]
        turns.append(
            Turn(
                id=f"turn-{i}",
                index=i,
                started_at=now + timedelta(seconds=i * 2),
                ended_at=now + timedelta(seconds=i * 2 + 1),
                messages=msgs,
            )
        )

    return UnifiedSession(
        id=generate_session_id(),
        source=SourceTool.OPENCODE,
        source_id=f"test-session-{generate_session_id()[:8]}",
        source_path="/tmp/test/session.json",
        title=title,
        project_name="test-project",
        project_path="/tmp/test-project",
        created_at=now,
        updated_at=now,
        stats=SessionStats(
            turn_count=turn_count,
            message_count=turn_count * 2,
            input_tokens=turn_count * 100,
            output_tokens=turn_count * 50,
            tool_call_count=tool_call_count,
            files_modified=files_modified or [],
        ),
        turns=turns,
    )


def _make_session_with_files(files: list[str]) -> UnifiedSession:
    """Create a session whose stats.files_modified is the given list."""
    session = _make_session_with_turns(3, files_modified=files)
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAnalyzeSession:
    """Tests for analyze_session function."""

    def test_basic_session(self):
        """Test that analyze_session returns a dict with all required keys."""
        session = create_session_with_tool_calls(
            [("Read", False), ("Edit", False)],
            user_messages=["Add a docstring to the function"],
        )
        result = analyze_session(session)

        assert isinstance(result, dict)
        assert result["session_id"] == session.id
        assert result["source"] == "opencode"
        assert result["analyzer_version"] == "heuristic_v1"
        assert result["analyzer_model"] is None
        assert isinstance(result["analyzed_at"], int)
        assert isinstance(result["underlying_goal"], str)
        assert isinstance(result["task_type"], str)
        assert isinstance(result["outcome"], str)
        assert isinstance(result["session_type"], str)
        assert isinstance(result["complexity_score"], int)
        assert isinstance(result["friction_score"], float)
        assert isinstance(result["brief_summary"], str)

    def test_empty_session(self):
        """Test that analyze_session handles a session with no turns."""
        session = _make_empty_session()
        result = analyze_session(session)

        assert result["session_id"] == session.id
        assert result["outcome"] == "unclear"
        assert result["session_type"] == "quick_question"  # 0 turns <= 2
        assert result["complexity_score"] == 1

    def test_session_with_friction(self):
        """Test that sessions with errors produce friction scores > 0."""
        session = create_session_with_tool_calls([
            ("bash", True),
            ("bash", True),
            ("bash", True),
            ("bash", True),
            ("bash", True),
            ("bash", True),
            ("read", True),
            ("read", True),
        ])
        result = analyze_session(session)

        assert result["friction_score"] > 0

    def test_output_keys_match_schema(self):
        """Test that all keys expected by session_facets table are present."""
        session = create_session_with_tool_calls(
            [("Read", False)],
            user_messages=["Show me the file"],
        )
        result = analyze_session(session)

        expected_keys = {
            "session_id",
            "source",
            "analyzed_at",
            "analyzer_version",
            "analyzer_model",
            "underlying_goal",
            "goal_categories",
            "task_type",
            "outcome",
            "completion_confidence",
            "session_type",
            "complexity_score",
            "friction_counts",
            "friction_detail",
            "friction_score",
            "tools_that_helped",
            "tools_that_didnt",
            "tool_helpfulness",
            "primary_language",
            "files_pattern",
            "brief_summary",
            "key_decisions",
        }
        assert set(result.keys()) == expected_keys


class TestExtractGoal:
    """Tests for _extract_goal function."""

    def test_extracts_first_user_message(self):
        """Test extracting goal from the first user message."""
        session = create_session_with_tool_calls(
            [("Read", False)],
            user_messages=["Fix the login bug in auth.py"],
        )
        goal = _extract_goal(session)
        assert goal == "Fix the login bug in auth.py"

    def test_truncates_long_goals(self):
        """Test that goals longer than 200 characters are truncated."""
        long_message = "A" * 250
        session = create_session_with_tool_calls(
            [("Read", False)],
            user_messages=[long_message],
        )
        goal = _extract_goal(session)
        assert len(goal) == 203  # 200 chars + "..."
        assert goal.endswith("...")

    def test_falls_back_to_title(self):
        """Test falling back to session title when no user messages have text."""
        session = _make_empty_session(title="My Session Title")
        goal = _extract_goal(session)
        assert goal == "My Session Title"

    def test_no_content_returns_unknown(self):
        """Test that a session with no title and no text returns 'Unknown goal'."""
        session = _make_empty_session(title=None)
        goal = _extract_goal(session)
        assert goal == "Unknown goal"


class TestClassifyTaskType:
    """Tests for _classify_task_type function."""

    def test_bugfix_keywords(self):
        """Test that 'fix', 'bug', 'error' keywords yield 'bugfix'."""
        for keyword in ["fix the tests", "there is a bug here", "error in module"]:
            session = create_session_with_tool_calls(
                [("Read", False)],
                user_messages=[keyword],
            )
            assert _classify_task_type(session) == "bugfix", f"Failed for: {keyword}"

    def test_debug_keywords(self):
        """Test that 'debug', 'investigate' keywords yield 'debug'."""
        for keyword in ["debug the crash", "investigate why this fails"]:
            session = create_session_with_tool_calls(
                [("Read", False)],
                user_messages=[keyword],
            )
            assert _classify_task_type(session) == "debug", f"Failed for: {keyword}"

    def test_docs_keywords(self):
        """Test that 'document', 'readme' keywords yield 'docs'."""
        for keyword in ["document the API", "update the readme"]:
            session = create_session_with_tool_calls(
                [("Read", False)],
                user_messages=[keyword],
            )
            assert _classify_task_type(session) == "docs", f"Failed for: {keyword}"

    def test_refactor_keywords(self):
        """Test that 'refactor', 'clean', 'reorganize' keywords yield 'refactor'."""
        for keyword in ["refactor this module", "clean up the code", "reorganize the files"]:
            session = create_session_with_tool_calls(
                [("Read", False)],
                user_messages=[keyword],
            )
            assert _classify_task_type(session) == "refactor", f"Failed for: {keyword}"

    def test_config_keywords(self):
        """Test that 'config', 'setup', 'deploy' keywords yield 'config'."""
        for keyword in ["config the pipeline", "setup the env", "deploy to staging"]:
            session = create_session_with_tool_calls(
                [("Read", False)],
                user_messages=[keyword],
            )
            assert _classify_task_type(session) == "config", f"Failed for: {keyword}"

    def test_exploration_from_read_heavy_tools(self):
        """Test that read-heavy tool usage yields 'exploration'."""
        session = create_session_with_tool_calls(
            [
                ("Read", False),
                ("Read", False),
                ("Read", False),
                ("Grep", False),
                ("Grep", False),
                ("Glob", False),
            ],
            user_messages=["Show me around the codebase"],
        )
        assert _classify_task_type(session) == "exploration"

    def test_feature_from_write_heavy_tools(self):
        """Test that write-heavy tool usage yields 'feature'."""
        session = create_session_with_tool_calls(
            [
                ("Edit", False),
                ("Write", False),
                ("Edit", False),
            ],
            user_messages=["Implement the new handler"],
        )
        assert _classify_task_type(session) == "feature"


class TestAssessOutcome:
    """Tests for _assess_outcome function."""

    def test_empty_session_unclear(self):
        """Test that an empty session returns 'unclear'."""
        session = _make_empty_session()
        assert _assess_outcome(session) == "unclear"

    def test_single_turn_abandoned(self):
        """Test that a single-turn session returns 'abandoned'."""
        session = _make_session_with_turns(1)
        assert _assess_outcome(session) == "abandoned"

    def test_successful_session_fully_achieved(self):
        """Test that a multi-turn session ending with assistant gets 'fully_achieved'."""
        session = _make_session_with_turns(3, user_message="Add a feature")
        # The last message in each turn is an assistant message, and there are
        # no errors, so outcome should be fully_achieved.
        assert _assess_outcome(session) == "fully_achieved"

    def test_high_error_session_partially_achieved(self):
        """Test that a session with high error rate gets 'partially_achieved'."""
        now = datetime.now(timezone.utc)

        # Build two turns: turn 0 has errors, turn 1 ends with assistant
        turn0_messages = [
            Message(
                id="msg-user-0",
                role="user",
                timestamp=now,
                parts=[TextPart(content="Fix the thing")],
            ),
        ]
        # Add many erroring tool calls to raise error_rate above 0.2
        for i in range(10):
            turn0_messages.append(
                Message(
                    id=f"msg-assistant-tc-{i}",
                    role="assistant",
                    timestamp=now + timedelta(seconds=i),
                    parts=[
                        ToolCallPart(
                            tool_name="bash",
                            tool_id=f"tool-{i}",
                            input={"command": "test"},
                        )
                    ],
                )
            )
            turn0_messages.append(
                Message(
                    id=f"msg-tool-{i}",
                    role="tool",
                    timestamp=now + timedelta(seconds=i, milliseconds=500),
                    parts=[
                        ToolResultPart(
                            tool_id=f"tool-{i}",
                            output="error",
                            is_error=True,
                        )
                    ],
                )
            )

        turn0 = Turn(
            id="turn-0",
            index=0,
            started_at=now,
            ended_at=now + timedelta(seconds=20),
            messages=turn0_messages,
        )

        turn1_messages = [
            Message(
                id="msg-user-1",
                role="user",
                timestamp=now + timedelta(seconds=21),
                parts=[TextPart(content="Try again")],
            ),
            Message(
                id="msg-assistant-final",
                role="assistant",
                timestamp=now + timedelta(seconds=22),
                parts=[TextPart(content="Done.")],
                usage=TokenUsage(input_tokens=100, output_tokens=50),
            ),
        ]
        turn1 = Turn(
            id="turn-1",
            index=1,
            started_at=now + timedelta(seconds=21),
            ended_at=now + timedelta(seconds=22),
            messages=turn1_messages,
        )

        session = UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.OPENCODE,
            source_id="error-session",
            source_path="/tmp/test/session.json",
            title="Error Session",
            project_name="test-project",
            project_path="/tmp/test-project",
            created_at=now,
            updated_at=now,
            stats=SessionStats(
                turn_count=2,
                message_count=len(turn0_messages) + len(turn1_messages),
                input_tokens=1000,
                output_tokens=500,
                tool_call_count=10,
            ),
            turns=[turn0, turn1],
        )

        outcome = _assess_outcome(session)
        assert outcome == "partially_achieved"


class TestClassifySessionType:
    """Tests for _classify_session_type function."""

    def test_quick_question(self):
        """Test that 1-2 turns produce 'quick_question'."""
        session = _make_session_with_turns(1)
        assert _classify_session_type(session) == "quick_question"

        session = _make_session_with_turns(2)
        assert _classify_session_type(session) == "quick_question"

    def test_single_task(self):
        """Test that 3-5 turns produce 'single_task'."""
        for n in (3, 4, 5):
            session = _make_session_with_turns(n)
            assert _classify_session_type(session) == "single_task", f"Failed for {n} turns"

    def test_multi_task(self):
        """Test that 6-15 turns produce 'multi_task'."""
        for n in (6, 10, 15):
            session = _make_session_with_turns(n)
            assert _classify_session_type(session) == "multi_task", f"Failed for {n} turns"

    def test_iterative_refinement(self):
        """Test that 16+ turns produce 'iterative_refinement'."""
        for n in (16, 20, 30):
            session = _make_session_with_turns(n)
            assert _classify_session_type(session) == "iterative_refinement", f"Failed for {n} turns"


class TestAssessComplexity:
    """Tests for _assess_complexity function."""

    def test_minimal_complexity(self):
        """Test that a simple session scores complexity 1."""
        session = _make_session_with_turns(
            2, tool_call_count=0, files_modified=[],
        )
        assert _assess_complexity(session) == 1

    def test_high_complexity(self):
        """Test that a complex session scores 4 or 5."""
        session = _make_session_with_turns(
            20,
            tool_call_count=30,
            files_modified=[f"src/mod{i}.py" for i in range(8)],
        )
        score = _assess_complexity(session)
        assert score >= 4
        assert score <= 5


class TestDetectPrimaryLanguage:
    """Tests for _detect_primary_language function."""

    def test_python_files(self):
        """Test detection of Python as primary language."""
        session = _make_session_with_files(["src/main.py", "src/utils.py", "tests/test_main.py"])
        assert _detect_primary_language(session) == "python"

    def test_mixed_files_picks_dominant(self):
        """Test that the dominant language wins when files are mixed."""
        session = _make_session_with_files([
            "src/main.py",
            "src/utils.py",
            "src/helpers.py",
            "app.js",
        ])
        assert _detect_primary_language(session) == "python"

    def test_no_files_returns_none(self):
        """Test that an empty file list returns None."""
        session = _make_session_with_files([])
        assert _detect_primary_language(session) is None


class TestDetectFilesPattern:
    """Tests for _detect_files_pattern function."""

    def test_docs_pattern(self):
        """Test detection of docs pattern."""
        session = _make_session_with_files(["README.md", "CHANGELOG.md"])
        assert _detect_files_pattern(session) == "docs"

    def test_config_pattern(self):
        """Test detection of config pattern."""
        session = _make_session_with_files(["config.yaml", "settings.toml"])
        assert _detect_files_pattern(session) == "config"

    def test_testing_pattern(self):
        """Test detection of testing pattern."""
        session = _make_session_with_files(["tests/test_main.py", "tests/test_utils.py"])
        assert _detect_files_pattern(session) == "python_testing"

    def test_backend_pattern(self):
        """Test detection of backend pattern for Python files."""
        session = _make_session_with_files(["src/server.py", "src/handlers.py"])
        assert _detect_files_pattern(session) == "python_backend"


class TestGenerateSummary:
    """Tests for _generate_summary function."""

    def test_includes_title(self):
        """Test that the summary includes the session title when different from goal."""
        session = _make_session_with_turns(
            3,
            user_message="Implement pagination",
            title="Pagination Feature",
        )
        summary = _generate_summary(session)
        assert "Pagination Feature" in summary

    def test_includes_stats(self):
        """Test that the summary includes turn and tool counts."""
        session = _make_session_with_turns(
            5,
            user_message="Do work",
            title="Work Session",
            tool_call_count=10,
            files_modified=["a.py", "b.py"],
        )
        summary = _generate_summary(session)
        assert "5 turns" in summary
        assert "10 tool calls" in summary
        assert "2 files" in summary
