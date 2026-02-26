"""Tests for the v2 feature extractor pipeline.

TDD: Tests written first, then extractors implemented to pass them.
"""

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
    ModelUsage,
    TokenUsage,
    generate_session_id,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_session(
    *,
    turns: list[Turn] | None = None,
    title: str | None = "Test Session",
    source: SourceTool = SourceTool.OPENCODE,
    files_modified: list[str] | None = None,
    tool_call_count: int = 0,
    duration_ms: int | None = None,
    models: list[ModelUsage] | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> UnifiedSession:
    """Build a minimal UnifiedSession for testing."""
    now = _now()
    t = turns or []
    msg_count = sum(len(turn.messages) for turn in t)
    return UnifiedSession(
        id=generate_session_id(),
        source=source,
        source_id=f"test-{generate_session_id()[:8]}",
        source_path="/tmp/test/session.json",
        title=title,
        project_name="test-project",
        project_path="/tmp/test-project",
        created_at=now,
        updated_at=now,
        duration_ms=duration_ms,
        models=models or [],
        stats=SessionStats(
            turn_count=len(t),
            message_count=msg_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_call_count=tool_call_count,
            files_modified=files_modified or [],
        ),
        turns=t,
    )


def _make_turn(
    index: int,
    messages: list[Message],
    *,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> Turn:
    now = _now()
    return Turn(
        id=f"turn-{index}",
        index=index,
        started_at=started_at or now,
        ended_at=ended_at or (now + timedelta(seconds=10)),
        messages=messages,
    )


def _user_msg(text: str, *, ts: datetime | None = None, msg_id: str = "") -> Message:
    return Message(
        id=msg_id or f"msg-user-{generate_session_id()[:6]}",
        role="user",
        timestamp=ts or _now(),
        parts=[TextPart(content=text)],
    )


def _assistant_msg(
    text: str = "",
    *,
    ts: datetime | None = None,
    tool_calls: list[tuple[str, str]] | None = None,
    usage: TokenUsage | None = None,
    model: str | None = None,
    msg_id: str = "",
) -> Message:
    parts: list = []
    if text:
        parts.append(TextPart(content=text))
    if tool_calls:
        for tool_name, tool_id in tool_calls:
            parts.append(ToolCallPart(tool_name=tool_name, tool_id=tool_id, input={}))
    return Message(
        id=msg_id or f"msg-asst-{generate_session_id()[:6]}",
        role="assistant",
        timestamp=ts or _now(),
        parts=parts,
        usage=usage,
        model=model,
    )


def _tool_result_msg(
    tool_id: str,
    output: str = "ok",
    is_error: bool = False,
    *,
    ts: datetime | None = None,
) -> Message:
    return Message(
        id=f"msg-tool-{generate_session_id()[:6]}",
        role="tool",
        timestamp=ts or _now(),
        parts=[ToolResultPart(tool_id=tool_id, output=output, is_error=is_error)],
    )


def _session_with_tool_calls(
    calls: list[tuple[str, bool]],
    user_text: str = "Do something",
) -> UnifiedSession:
    """Build a session with tool call + result pairs.

    Args:
        calls: list of (tool_name, is_error) tuples
        user_text: initial user message
    """
    now = _now()
    messages: list[Message] = [_user_msg(user_text, ts=now)]

    for i, (tool_name, is_error) in enumerate(calls):
        tid = f"tool-{i}"
        messages.append(
            _assistant_msg(
                tool_calls=[(tool_name, tid)],
                ts=now + timedelta(seconds=i * 2),
            )
        )
        messages.append(
            _tool_result_msg(
                tid,
                output="error: something failed" if is_error else "success",
                is_error=is_error,
                ts=now + timedelta(seconds=i * 2 + 1),
            )
        )

    # Final assistant response
    messages.append(
        _assistant_msg("Done.", ts=now + timedelta(seconds=len(calls) * 2 + 1))
    )

    turn = _make_turn(
        0,
        messages,
        started_at=now,
        ended_at=now + timedelta(seconds=len(calls) * 2 + 2),
    )
    return _make_session(
        turns=[turn],
        tool_call_count=len(calls),
        files_modified=[],
    )


# ===========================================================================
# 1. ToolCallStatsExtractor
# ===========================================================================


class TestToolCallStatsExtractor:
    def _extract(self, session):
        from sagg.analytics.insights.extractors import ToolCallStatsExtractor
        return ToolCallStatsExtractor().extract(session)

    def test_empty_session(self):
        session = _make_session(turns=[])
        result = self._extract(session)
        assert result["tool_calls_total"] == 0
        assert result["tool_calls_by_name"] == {}
        assert result["tool_call_sequence"] == []
        assert result["unique_tools_used"] == 0
        assert result["most_used_tool"] is None
        assert result["tool_diversity_ratio"] == 0.0
        assert result["read_write_ratio"] is None

    def test_counts_tools(self):
        session = _session_with_tool_calls([
            ("Read", False),
            ("Read", False),
            ("Edit", False),
            ("Bash", False),
        ])
        result = self._extract(session)
        assert result["tool_calls_total"] == 4
        assert result["tool_calls_by_name"] == {"Read": 2, "Edit": 1, "Bash": 1}
        assert result["unique_tools_used"] == 3
        assert result["most_used_tool"] == "Read"

    def test_sequence_preserved(self):
        session = _session_with_tool_calls([
            ("Read", False),
            ("Edit", False),
            ("Read", False),
        ])
        result = self._extract(session)
        assert result["tool_call_sequence"] == ["Read", "Edit", "Read"]

    def test_diversity_ratio(self):
        # 3 unique tools out of 6 total calls
        session = _session_with_tool_calls([
            ("Read", False), ("Read", False),
            ("Edit", False), ("Edit", False),
            ("Bash", False), ("Bash", False),
        ])
        result = self._extract(session)
        assert result["tool_diversity_ratio"] == pytest.approx(3 / 6)

    def test_read_write_ratio(self):
        # Read-heavy: 4 reads vs 1 write
        session = _session_with_tool_calls([
            ("Read", False), ("Read", False), ("Grep", False), ("Glob", False),
            ("Edit", False),
        ])
        result = self._extract(session)
        # read_tools = Read(2) + Grep(1) + Glob(1) = 4
        # write_tools = Edit(1) = 1
        assert result["read_write_ratio"] == pytest.approx(4.0)

    def test_read_write_ratio_no_writes(self):
        session = _session_with_tool_calls([("Read", False), ("Grep", False)])
        result = self._extract(session)
        assert result["read_write_ratio"] is None  # Division by zero → None


# ===========================================================================
# 2. ErrorAnalysisExtractor
# ===========================================================================


class TestErrorAnalysisExtractor:
    def _extract(self, session):
        from sagg.analytics.insights.extractors import ErrorAnalysisExtractor
        return ErrorAnalysisExtractor().extract(session)

    def test_no_errors(self):
        session = _session_with_tool_calls([
            ("Read", False), ("Edit", False),
        ])
        result = self._extract(session)
        assert result["tool_results_total"] == 2
        assert result["tool_errors_total"] == 0
        assert result["error_rate"] == 0.0
        assert result["errors_by_tool"] == {}
        assert result["error_details"] == []
        assert result["first_error_turn_index"] is None
        assert result["error_recovery_rate"] is None

    def test_all_errors(self):
        session = _session_with_tool_calls([
            ("Bash", True), ("Bash", True), ("Edit", True),
        ])
        result = self._extract(session)
        assert result["tool_errors_total"] == 3
        assert result["error_rate"] == pytest.approx(1.0)
        assert result["errors_by_tool"] == {"Bash": 2, "Edit": 1}

    def test_error_details_capped_at_10(self):
        calls = [("Bash", True)] * 15
        session = _session_with_tool_calls(calls)
        result = self._extract(session)
        assert len(result["error_details"]) <= 10

    def test_error_detail_structure(self):
        session = _session_with_tool_calls([("Bash", True)])
        result = self._extract(session)
        assert len(result["error_details"]) == 1
        detail = result["error_details"][0]
        assert detail["tool_name"] == "Bash"
        assert "tool_id" in detail
        assert "error_preview" in detail
        assert "turn_index" in detail

    def test_first_error_turn_index(self):
        now = _now()
        # Turn 0: success, Turn 1: error
        t0 = _make_turn(0, [
            _user_msg("hi", ts=now),
            _assistant_msg(tool_calls=[("Read", "t0")], ts=now + timedelta(seconds=1)),
            _tool_result_msg("t0", "ok", False, ts=now + timedelta(seconds=2)),
        ], started_at=now, ended_at=now + timedelta(seconds=3))
        t1 = _make_turn(1, [
            _user_msg("more", ts=now + timedelta(seconds=4)),
            _assistant_msg(tool_calls=[("Bash", "t1")], ts=now + timedelta(seconds=5)),
            _tool_result_msg("t1", "fail", True, ts=now + timedelta(seconds=6)),
        ], started_at=now + timedelta(seconds=4), ended_at=now + timedelta(seconds=7))

        session = _make_session(turns=[t0, t1])
        result = self._extract(session)
        assert result["first_error_turn_index"] == 1

    def test_error_free_streak(self):
        session = _session_with_tool_calls([
            ("Read", False), ("Read", False), ("Read", False),
            ("Bash", True),
            ("Edit", False),
        ])
        result = self._extract(session)
        assert result["error_free_streak_max"] == 3

    def test_error_clustering_early(self):
        # Errors in first quarter of tool calls
        session = _session_with_tool_calls([
            ("Bash", True), ("Bash", True),
            ("Read", False), ("Read", False), ("Read", False),
            ("Edit", False), ("Edit", False), ("Edit", False),
        ])
        result = self._extract(session)
        assert result["error_clustering"] == "early"

    def test_error_clustering_late(self):
        session = _session_with_tool_calls([
            ("Read", False), ("Read", False), ("Read", False),
            ("Edit", False), ("Edit", False), ("Edit", False),
            ("Bash", True), ("Bash", True),
        ])
        result = self._extract(session)
        assert result["error_clustering"] == "late"

    def test_error_recovery_rate(self):
        # Bash errors then Bash succeeds → recovery
        session = _session_with_tool_calls([
            ("Bash", True),
            ("Bash", False),
            ("Edit", True),  # No Edit success after → no recovery
        ])
        result = self._extract(session)
        # 1 recovered (Bash) out of 2 errors
        assert result["error_recovery_rate"] == pytest.approx(0.5)


# ===========================================================================
# 3. InterventionExtractor
# ===========================================================================


class TestInterventionExtractor:
    def _extract(self, session):
        from sagg.analytics.insights.extractors import InterventionExtractor
        return InterventionExtractor().extract(session)

    def test_no_interventions(self):
        session = _session_with_tool_calls([("Read", False), ("Edit", False)])
        result = self._extract(session)
        assert result["intervention_count"] == 0
        assert result["intervention_details"] == []
        assert result["intervention_rate"] == 0.0

    def test_post_error_intervention(self):
        """User corrects after a tool error."""
        now = _now()
        messages = [
            _user_msg("run the build", ts=now),
            _assistant_msg(tool_calls=[("Bash", "t0")], ts=now + timedelta(seconds=1)),
            _tool_result_msg("t0", "error: npm not found", True, ts=now + timedelta(seconds=2)),
            _user_msg("no use yarn instead", ts=now + timedelta(seconds=3)),
            _assistant_msg(tool_calls=[("Bash", "t1")], ts=now + timedelta(seconds=4)),
            _tool_result_msg("t1", "ok", False, ts=now + timedelta(seconds=5)),
        ]
        turn = _make_turn(0, messages, started_at=now, ended_at=now + timedelta(seconds=6))
        session = _make_session(turns=[turn])
        result = self._extract(session)
        assert result["intervention_count"] >= 1
        assert result["post_error_interventions"] >= 1

    def test_proactive_redirection(self):
        """User redirects before any error — short correction message."""
        now = _now()
        messages = [
            _user_msg("implement the login page", ts=now),
            _assistant_msg("I'll create a React component...", ts=now + timedelta(seconds=1)),
            _user_msg("no don't use React, use Vue", ts=now + timedelta(seconds=2)),
            _assistant_msg("OK, I'll use Vue...", ts=now + timedelta(seconds=3)),
        ]
        turn = _make_turn(0, messages, started_at=now, ended_at=now + timedelta(seconds=4))
        session = _make_session(turns=[turn])
        result = self._extract(session)
        assert result["intervention_count"] >= 1
        assert result["proactive_redirections"] >= 1

    def test_intervention_rate(self):
        """Rate = interventions / user_messages."""
        now = _now()
        messages = [
            _user_msg("do X", ts=now),
            _assistant_msg("ok", ts=now + timedelta(seconds=1)),
            _user_msg("no wrong", ts=now + timedelta(seconds=2)),  # intervention
            _assistant_msg("fixed", ts=now + timedelta(seconds=3)),
            _user_msg("now do Y", ts=now + timedelta(seconds=4)),  # not intervention (new topic)
            _assistant_msg("done", ts=now + timedelta(seconds=5)),
        ]
        turn = _make_turn(0, messages, started_at=now, ended_at=now + timedelta(seconds=6))
        session = _make_session(turns=[turn])
        result = self._extract(session)
        # 3 user messages, at least 1 intervention
        assert result["intervention_rate"] > 0.0
        assert result["intervention_rate"] <= 1.0

    def test_intervention_details_capped(self):
        """At most 10 intervention details."""
        now = _now()
        messages = [_user_msg("start", ts=now)]
        for i in range(20):
            messages.append(
                _assistant_msg("trying...", ts=now + timedelta(seconds=i * 3 + 1))
            )
            messages.append(
                _user_msg("no wrong", ts=now + timedelta(seconds=i * 3 + 2))
            )
        turn = _make_turn(0, messages, started_at=now, ended_at=now + timedelta(seconds=100))
        session = _make_session(turns=[turn])
        result = self._extract(session)
        assert len(result["intervention_details"]) <= 10


# ===========================================================================
# 4. TimingExtractor
# ===========================================================================


class TestTimingExtractor:
    def _extract(self, session):
        from sagg.analytics.insights.extractors import TimingExtractor
        return TimingExtractor().extract(session)

    def test_empty_session(self):
        session = _make_session(turns=[])
        result = self._extract(session)
        assert result["session_duration_ms"] is None
        assert result["avg_turn_duration_ms"] is None

    def test_session_duration_from_model(self):
        session = _make_session(turns=[], duration_ms=5000)
        result = self._extract(session)
        assert result["session_duration_ms"] == 5000

    def test_avg_turn_duration(self):
        now = _now()
        t0 = _make_turn(0, [
            _user_msg("a", ts=now),
        ], started_at=now, ended_at=now + timedelta(seconds=10))
        t1 = _make_turn(1, [
            _user_msg("b", ts=now + timedelta(seconds=15)),
        ], started_at=now + timedelta(seconds=15), ended_at=now + timedelta(seconds=25))
        session = _make_session(turns=[t0, t1])
        result = self._extract(session)
        # Both turns are 10s = 10000ms
        assert result["avg_turn_duration_ms"] == pytest.approx(10000.0)

    def test_max_turn_duration(self):
        now = _now()
        t0 = _make_turn(0, [_user_msg("a", ts=now)],
                         started_at=now, ended_at=now + timedelta(seconds=5))
        t1 = _make_turn(1, [_user_msg("b", ts=now + timedelta(seconds=10))],
                         started_at=now + timedelta(seconds=10),
                         ended_at=now + timedelta(seconds=30))
        session = _make_session(turns=[t0, t1])
        result = self._extract(session)
        assert result["max_turn_duration_ms"] == 20000

    def test_time_to_first_tool_call(self):
        now = _now()
        messages = [
            _user_msg("hi", ts=now),
            _assistant_msg("thinking...", ts=now + timedelta(seconds=2)),
            _assistant_msg(tool_calls=[("Read", "t0")], ts=now + timedelta(seconds=5)),
            _tool_result_msg("t0", "ok", False, ts=now + timedelta(seconds=6)),
        ]
        turn = _make_turn(0, messages, started_at=now, ended_at=now + timedelta(seconds=7))
        session = _make_session(turns=[turn])
        result = self._extract(session)
        # First message at t=0, first tool call at t=5 → 5000ms
        assert result["time_to_first_tool_call_ms"] == pytest.approx(5000.0, abs=100)

    def test_time_to_first_error(self):
        now = _now()
        messages = [
            _user_msg("hi", ts=now),
            _assistant_msg(tool_calls=[("Read", "t0")], ts=now + timedelta(seconds=1)),
            _tool_result_msg("t0", "ok", False, ts=now + timedelta(seconds=2)),
            _assistant_msg(tool_calls=[("Bash", "t1")], ts=now + timedelta(seconds=3)),
            _tool_result_msg("t1", "fail", True, ts=now + timedelta(seconds=4)),
        ]
        turn = _make_turn(0, messages, started_at=now, ended_at=now + timedelta(seconds=5))
        session = _make_session(turns=[turn])
        result = self._extract(session)
        # First msg at t=0, first error result at t=4 → 4000ms
        assert result["time_to_first_error_ms"] == pytest.approx(4000.0, abs=100)


# ===========================================================================
# 5. FilePatternExtractor
# ===========================================================================


class TestFilePatternExtractor:
    def _extract(self, session):
        from sagg.analytics.insights.extractors import FilePatternExtractor
        return FilePatternExtractor().extract(session)

    def test_empty_files(self):
        session = _make_session(turns=[], files_modified=[])
        result = self._extract(session)
        assert result["file_count_modified"] == 0
        assert result["primary_language"] is None
        assert result["files_pattern"] is None
        assert result["scope"] is None

    def test_language_detection(self):
        session = _make_session(
            turns=[], files_modified=["src/main.py", "src/utils.py", "config.yaml"]
        )
        result = self._extract(session)
        assert result["primary_language"] == "python"
        assert result["languages_touched"]["python"] == 2
        assert result["languages_touched"]["yaml"] == 1

    def test_files_read_from_tool_calls(self):
        """Extracts files read from Read tool call inputs."""
        now = _now()
        messages = [
            _user_msg("check", ts=now),
            Message(
                id="m1", role="assistant", timestamp=now + timedelta(seconds=1),
                parts=[ToolCallPart(
                    tool_name="Read", tool_id="r1",
                    input={"filePath": "/src/main.py"},
                )],
            ),
            _tool_result_msg("r1", "file content", False, ts=now + timedelta(seconds=2)),
        ]
        turn = _make_turn(0, messages, started_at=now, ended_at=now + timedelta(seconds=3))
        session = _make_session(turns=[turn], files_modified=[])
        result = self._extract(session)
        assert "/src/main.py" in result["files_read"]
        assert "/src/main.py" in result["files_read_only"]

    def test_test_files_flag(self):
        session = _make_session(
            turns=[], files_modified=["tests/test_foo.py", "src/foo.py"]
        )
        result = self._extract(session)
        assert result["test_files_touched"] is True

    def test_config_files_flag(self):
        session = _make_session(turns=[], files_modified=["config.yaml", "settings.toml"])
        result = self._extract(session)
        assert result["config_files_touched"] is True

    def test_scope_single_file(self):
        session = _make_session(turns=[], files_modified=["src/main.py"])
        result = self._extract(session)
        assert result["scope"] == "single_file"

    def test_scope_single_dir(self):
        session = _make_session(
            turns=[], files_modified=["src/main.py", "src/utils.py"]
        )
        result = self._extract(session)
        assert result["scope"] == "single_dir"

    def test_scope_multi_dir(self):
        session = _make_session(
            turns=[], files_modified=["src/main.py", "tests/test_main.py", "docs/README.md"]
        )
        result = self._extract(session)
        assert result["scope"] == "multi_dir"

    def test_files_pattern_docs(self):
        session = _make_session(turns=[], files_modified=["README.md", "CHANGELOG.md"])
        result = self._extract(session)
        assert result["files_pattern"] == "docs"

    def test_files_pattern_backend(self):
        session = _make_session(
            turns=[], files_modified=["src/server.py", "src/handlers.py"]
        )
        result = self._extract(session)
        assert result["files_pattern"] == "python_backend"


# ===========================================================================
# 6. TokenUsageExtractor
# ===========================================================================


class TestTokenUsageExtractor:
    def _extract(self, session):
        from sagg.analytics.insights.extractors import TokenUsageExtractor
        return TokenUsageExtractor().extract(session)

    def test_empty_session(self):
        session = _make_session(turns=[])
        result = self._extract(session)
        assert result["total_input_tokens"] == 0
        assert result["total_output_tokens"] == 0
        assert result["total_tokens"] == 0
        assert result["cached_tokens"] == 0
        assert result["cache_hit_ratio"] == 0.0
        assert result["primary_model"] is None

    def test_sums_tokens(self):
        now = _now()
        messages = [
            _user_msg("hi", ts=now),
            _assistant_msg(
                "hello",
                ts=now + timedelta(seconds=1),
                usage=TokenUsage(input_tokens=100, output_tokens=50, cached_tokens=20),
            ),
            _user_msg("more", ts=now + timedelta(seconds=2)),
            _assistant_msg(
                "ok",
                ts=now + timedelta(seconds=3),
                usage=TokenUsage(input_tokens=200, output_tokens=80, cached_tokens=30),
            ),
        ]
        turn = _make_turn(0, messages, started_at=now, ended_at=now + timedelta(seconds=4))
        session = _make_session(turns=[turn])
        result = self._extract(session)
        assert result["total_input_tokens"] == 300
        assert result["total_output_tokens"] == 130
        assert result["total_tokens"] == 430
        assert result["cached_tokens"] == 50
        assert result["cache_hit_ratio"] == pytest.approx(50 / 300, abs=1e-3)

    def test_tokens_per_turn(self):
        now = _now()
        t0 = _make_turn(0, [
            _user_msg("a", ts=now),
            _assistant_msg("b", ts=now + timedelta(seconds=1),
                           usage=TokenUsage(input_tokens=100, output_tokens=50)),
        ], started_at=now, ended_at=now + timedelta(seconds=2))
        t1 = _make_turn(1, [
            _user_msg("c", ts=now + timedelta(seconds=3)),
            _assistant_msg("d", ts=now + timedelta(seconds=4),
                           usage=TokenUsage(input_tokens=200, output_tokens=100)),
        ], started_at=now + timedelta(seconds=3), ended_at=now + timedelta(seconds=5))
        session = _make_session(turns=[t0, t1])
        result = self._extract(session)
        # Total tokens = 450, 2 turns → 225 per turn
        assert result["tokens_per_turn"] == pytest.approx(225.0)

    def test_models_from_messages(self):
        now = _now()
        messages = [
            _user_msg("hi", ts=now),
            _assistant_msg("a", ts=now + timedelta(seconds=1), model="claude-sonnet-4"),
            _user_msg("more", ts=now + timedelta(seconds=2)),
            _assistant_msg("b", ts=now + timedelta(seconds=3), model="claude-sonnet-4"),
            _user_msg("again", ts=now + timedelta(seconds=4)),
            _assistant_msg("c", ts=now + timedelta(seconds=5), model="gpt-4o"),
        ]
        turn = _make_turn(0, messages, started_at=now, ended_at=now + timedelta(seconds=6))
        session = _make_session(turns=[turn])
        result = self._extract(session)
        assert "claude-sonnet-4" in result["models_used"]
        assert "gpt-4o" in result["models_used"]
        assert result["primary_model"] == "claude-sonnet-4"


# ===========================================================================
# 7. ConversationFlowExtractor
# ===========================================================================


class TestConversationFlowExtractor:
    def _extract(self, session):
        from sagg.analytics.insights.extractors import ConversationFlowExtractor
        return ConversationFlowExtractor().extract(session)

    def test_empty_session(self):
        session = _make_session(turns=[])
        result = self._extract(session)
        assert result["user_messages_count"] == 0
        assert result["assistant_messages_count"] == 0
        assert result["turn_count"] == 0
        assert result["conversation_pattern"] == "single_shot"

    def test_counts_messages(self):
        now = _now()
        messages = [
            _user_msg("hello", ts=now),
            _assistant_msg("hi", ts=now + timedelta(seconds=1)),
            _user_msg("help me", ts=now + timedelta(seconds=2)),
            _assistant_msg("sure", ts=now + timedelta(seconds=3)),
        ]
        turn = _make_turn(0, messages, started_at=now, ended_at=now + timedelta(seconds=4))
        session = _make_session(turns=[turn])
        result = self._extract(session)
        assert result["user_messages_count"] == 2
        assert result["assistant_messages_count"] == 2

    def test_avg_message_lengths(self):
        now = _now()
        messages = [
            _user_msg("short", ts=now),  # 5 chars
            _assistant_msg("a bit longer response", ts=now + timedelta(seconds=1)),  # 21 chars
            _user_msg("another short", ts=now + timedelta(seconds=2)),  # 13 chars
            _assistant_msg("yes", ts=now + timedelta(seconds=3)),  # 3 chars
        ]
        turn = _make_turn(0, messages, started_at=now, ended_at=now + timedelta(seconds=4))
        session = _make_session(turns=[turn])
        result = self._extract(session)
        assert result["avg_user_message_length"] == pytest.approx((5 + 13) / 2)
        assert result["avg_assistant_message_length"] == pytest.approx((21 + 3) / 2)

    def test_back_and_forth(self):
        now = _now()
        messages = [
            _user_msg("implement X", ts=now),
            _assistant_msg("ok doing it", ts=now + timedelta(seconds=1)),
            _user_msg("no", ts=now + timedelta(seconds=2)),          # short correction
            _assistant_msg("ok fixing", ts=now + timedelta(seconds=3)),
            _user_msg("wrong again", ts=now + timedelta(seconds=4)),  # short correction
            _assistant_msg("fixed", ts=now + timedelta(seconds=5)),
        ]
        turn = _make_turn(0, messages, started_at=now, ended_at=now + timedelta(seconds=6))
        session = _make_session(turns=[turn])
        result = self._extract(session)
        assert result["back_and_forth_count"] >= 2

    def test_single_shot_pattern(self):
        now = _now()
        t0 = _make_turn(0, [
            _user_msg("what is X?", ts=now),
            _assistant_msg("X is Y", ts=now + timedelta(seconds=1)),
        ], started_at=now, ended_at=now + timedelta(seconds=2))
        session = _make_session(turns=[t0])
        result = self._extract(session)
        assert result["conversation_pattern"] == "single_shot"

    def test_iterative_pattern(self):
        """Many short exchanges → iterative."""
        now = _now()
        turns = []
        for i in range(10):
            turns.append(_make_turn(i, [
                _user_msg("fix" if i > 0 else "do X", ts=now + timedelta(seconds=i * 2)),
                _assistant_msg("ok", ts=now + timedelta(seconds=i * 2 + 1)),
            ], started_at=now + timedelta(seconds=i * 2),
               ended_at=now + timedelta(seconds=i * 2 + 1)))
        session = _make_session(turns=turns)
        result = self._extract(session)
        assert result["conversation_pattern"] == "iterative"

    def test_detailed_briefing_pattern(self):
        """Long first message, few follow-ups → detailed_briefing."""
        now = _now()
        long_msg = "Here is a very detailed description of what I want. " * 20  # ~1000 chars
        t0 = _make_turn(0, [
            _user_msg(long_msg, ts=now),
            _assistant_msg("Got it, working on it...", ts=now + timedelta(seconds=1)),
        ], started_at=now, ended_at=now + timedelta(seconds=2))
        t1 = _make_turn(1, [
            _user_msg("looks good", ts=now + timedelta(seconds=5)),
            _assistant_msg("Done!", ts=now + timedelta(seconds=6)),
        ], started_at=now + timedelta(seconds=5), ended_at=now + timedelta(seconds=6))
        session = _make_session(turns=[t0, t1])
        result = self._extract(session)
        assert result["conversation_pattern"] == "detailed_briefing"

    def test_first_user_message_length(self):
        now = _now()
        messages = [
            _user_msg("implement the full auth system", ts=now),
            _assistant_msg("on it", ts=now + timedelta(seconds=1)),
        ]
        turn = _make_turn(0, messages, started_at=now, ended_at=now + timedelta(seconds=2))
        session = _make_session(turns=[turn])
        result = self._extract(session)
        assert result["first_user_message_length"] == len("implement the full auth system")


# ===========================================================================
# 8. OutcomeSignalsExtractor
# ===========================================================================


class TestOutcomeSignalsExtractor:
    def _extract(self, session):
        from sagg.analytics.insights.extractors import OutcomeSignalsExtractor
        return OutcomeSignalsExtractor().extract(session)

    def test_empty_session_abandoned(self):
        session = _make_session(turns=[])
        result = self._extract(session)
        assert result["outcome"] == "abandoned"
        assert result["completion_confidence"] == pytest.approx(0.7)

    def test_single_turn_abandoned(self):
        now = _now()
        t0 = _make_turn(0, [
            _user_msg("hello", ts=now),
            _assistant_msg("hi", ts=now + timedelta(seconds=1)),
        ], started_at=now, ended_at=now + timedelta(seconds=2))
        session = _make_session(turns=[t0])
        result = self._extract(session)
        assert result["outcome"] == "abandoned"

    def test_satisfaction_detected(self):
        now = _now()
        t0 = _make_turn(0, [
            _user_msg("fix the bug", ts=now),
            _assistant_msg("Fixed it", ts=now + timedelta(seconds=1)),
        ], started_at=now, ended_at=now + timedelta(seconds=2))
        t1 = _make_turn(1, [
            _user_msg("thanks, perfect!", ts=now + timedelta(seconds=3)),
            _assistant_msg("You're welcome!", ts=now + timedelta(seconds=4)),
        ], started_at=now + timedelta(seconds=3), ended_at=now + timedelta(seconds=4))
        session = _make_session(turns=[t0, t1])
        result = self._extract(session)
        assert result["outcome"] == "fully_achieved"
        assert result["user_expressed_satisfaction"] is True

    def test_frustration_detected(self):
        now = _now()
        t0 = _make_turn(0, [
            _user_msg("do X", ts=now),
            _assistant_msg("done", ts=now + timedelta(seconds=1)),
        ], started_at=now, ended_at=now + timedelta(seconds=2))
        t1 = _make_turn(1, [
            _user_msg("this is wrong, stop", ts=now + timedelta(seconds=3)),
            _assistant_msg("sorry", ts=now + timedelta(seconds=4)),
        ], started_at=now + timedelta(seconds=3), ended_at=now + timedelta(seconds=4))
        session = _make_session(turns=[t0, t1])
        result = self._extract(session)
        assert result["outcome"] == "partially_achieved"
        assert result["user_expressed_frustration"] is True

    def test_clean_ending(self):
        now = _now()
        t0 = _make_turn(0, [
            _user_msg("do something", ts=now),
            _assistant_msg("working...", ts=now + timedelta(seconds=1)),
        ], started_at=now, ended_at=now + timedelta(seconds=2))
        t1 = _make_turn(1, [
            _user_msg("continue", ts=now + timedelta(seconds=3)),
            _assistant_msg("All done!", ts=now + timedelta(seconds=4)),
        ], started_at=now + timedelta(seconds=3), ended_at=now + timedelta(seconds=4))
        session = _make_session(turns=[t0, t1])
        result = self._extract(session)
        assert result["session_ended_cleanly"] is True
        assert result["last_message_role"] == "assistant"

    def test_outcome_signals_present(self):
        now = _now()
        t0 = _make_turn(0, [
            _user_msg("do X", ts=now),
            _assistant_msg("done", ts=now + timedelta(seconds=1)),
        ], started_at=now, ended_at=now + timedelta(seconds=2))
        t1 = _make_turn(1, [
            _user_msg("more", ts=now + timedelta(seconds=3)),
            _assistant_msg("finished", ts=now + timedelta(seconds=4)),
        ], started_at=now + timedelta(seconds=3), ended_at=now + timedelta(seconds=4))
        session = _make_session(turns=[t0, t1])
        result = self._extract(session)
        assert isinstance(result["outcome_signals"], list)
        assert len(result["outcome_signals"]) > 0


# ===========================================================================
# 9. GoalClassificationExtractor
# ===========================================================================


class TestGoalClassificationExtractor:
    def _extract(self, session):
        from sagg.analytics.insights.extractors import GoalClassificationExtractor
        return GoalClassificationExtractor().extract(session)

    def test_extracts_goal(self):
        now = _now()
        messages = [
            _user_msg("Fix the login bug in auth.py", ts=now),
            _assistant_msg("I'll look into it", ts=now + timedelta(seconds=1)),
        ]
        turn = _make_turn(0, messages, started_at=now, ended_at=now + timedelta(seconds=2))
        session = _make_session(turns=[turn])
        result = self._extract(session)
        assert result["underlying_goal"] == "Fix the login bug in auth.py"
        assert "bugfix" in result["goal_categories"]
        assert result["task_type"] == "bugfix"

    def test_debug_classification(self):
        now = _now()
        turn = _make_turn(0, [
            _user_msg("debug the crash", ts=now),
            _assistant_msg("ok", ts=now + timedelta(seconds=1)),
        ], started_at=now, ended_at=now + timedelta(seconds=2))
        session = _make_session(turns=[turn])
        result = self._extract(session)
        assert result["task_type"] == "debug"

    def test_session_type_quick_question(self):
        now = _now()
        t0 = _make_turn(0, [
            _user_msg("what is X?", ts=now),
            _assistant_msg("X is Y", ts=now + timedelta(seconds=1)),
        ], started_at=now, ended_at=now + timedelta(seconds=2))
        session = _make_session(turns=[t0])
        result = self._extract(session)
        assert result["session_type"] == "quick_question"

    def test_session_type_multi_task(self):
        now = _now()
        turns = []
        for i in range(8):
            turns.append(_make_turn(i, [
                _user_msg(f"task {i}", ts=now + timedelta(seconds=i * 2)),
                _assistant_msg(f"done {i}", ts=now + timedelta(seconds=i * 2 + 1)),
            ], started_at=now + timedelta(seconds=i * 2),
               ended_at=now + timedelta(seconds=i * 2 + 1)))
        session = _make_session(turns=turns)
        result = self._extract(session)
        assert result["session_type"] == "multi_task"

    def test_goal_evolution(self):
        """Goal categories change mid-session → goal_evolution = True."""
        now = _now()
        t0 = _make_turn(0, [
            _user_msg("fix the login bug", ts=now),
            _assistant_msg("fixing", ts=now + timedelta(seconds=1)),
        ], started_at=now, ended_at=now + timedelta(seconds=2))
        t1 = _make_turn(1, [
            _user_msg("actually, let's refactor the whole module", ts=now + timedelta(seconds=3)),
            _assistant_msg("ok refactoring", ts=now + timedelta(seconds=4)),
        ], started_at=now + timedelta(seconds=3), ended_at=now + timedelta(seconds=4))
        session = _make_session(turns=[t0, t1])
        result = self._extract(session)
        assert result["goal_evolution"] is True

    def test_multi_goal(self):
        """Multiple goal categories → multi_goal = True."""
        now = _now()
        turn = _make_turn(0, [
            _user_msg("fix the bug and add tests and update the docs", ts=now),
            _assistant_msg("on it", ts=now + timedelta(seconds=1)),
        ], started_at=now, ended_at=now + timedelta(seconds=2))
        session = _make_session(turns=[turn])
        result = self._extract(session)
        assert result["multi_goal"] is True

    def test_truncates_long_goal(self):
        now = _now()
        long_msg = "A" * 300
        turn = _make_turn(0, [
            _user_msg(long_msg, ts=now),
            _assistant_msg("ok", ts=now + timedelta(seconds=1)),
        ], started_at=now, ended_at=now + timedelta(seconds=2))
        session = _make_session(turns=[turn])
        result = self._extract(session)
        assert len(result["underlying_goal"]) <= 203


# ===========================================================================
# 10. ComplexityExtractor
# ===========================================================================


class TestComplexityExtractor:
    def _extract(self, session):
        from sagg.analytics.insights.extractors import ComplexityExtractor
        return ComplexityExtractor().extract(session)

    def test_minimal_complexity(self):
        now = _now()
        t0 = _make_turn(0, [
            _user_msg("hi", ts=now),
            _assistant_msg("hey", ts=now + timedelta(seconds=1)),
        ], started_at=now, ended_at=now + timedelta(seconds=2))
        session = _make_session(turns=[t0], tool_call_count=0, files_modified=[])
        result = self._extract(session)
        assert result["complexity_score"] == 1
        assert isinstance(result["complexity_factors"], dict)

    def test_high_complexity(self):
        now = _now()
        turns = []
        for i in range(20):
            turns.append(_make_turn(i, [
                _user_msg(f"task {i}", ts=now + timedelta(seconds=i * 2)),
                _assistant_msg(f"done {i}", ts=now + timedelta(seconds=i * 2 + 1)),
            ], started_at=now + timedelta(seconds=i * 2),
               ended_at=now + timedelta(seconds=i * 2 + 1)))
        session = _make_session(
            turns=turns,
            tool_call_count=30,
            files_modified=[f"src/mod{i}.py" for i in range(8)],
        )
        result = self._extract(session)
        assert result["complexity_score"] >= 4

    def test_brief_summary(self):
        now = _now()
        t0 = _make_turn(0, [
            _user_msg("implement pagination", ts=now),
            _assistant_msg("done", ts=now + timedelta(seconds=1)),
        ], started_at=now, ended_at=now + timedelta(seconds=2))
        session = _make_session(turns=[t0], title="Pagination Feature")
        result = self._extract(session)
        assert isinstance(result["brief_summary"], str)
        assert len(result["brief_summary"]) > 0

    def test_complexity_cap_at_5(self):
        """Even extreme sessions cap at 5."""
        now = _now()
        # Build a session with errors via tool calls
        calls = [("Bash", True)] * 10 + [("Edit", False)] * 15
        session = _session_with_tool_calls(calls)
        # Override stats for extra complexity
        session.stats.files_modified = [f"src/f{i}.py" for i in range(20)]
        result = self._extract(session)
        assert result["complexity_score"] <= 5


# ===========================================================================
# 11. Pipeline: extract_facet + EXTRACTORS registry
# ===========================================================================


class TestExtractFacetPipeline:
    def test_extract_facet_returns_all_keys(self):
        from sagg.analytics.insights.extractors import extract_facet
        session = _session_with_tool_calls([
            ("Read", False), ("Edit", False), ("Bash", True),
        ], user_text="Fix the login bug")
        facet = extract_facet(session)

        # Identity
        assert facet["session_id"] == session.id
        assert facet["source"] == "opencode"
        assert facet["analyzer_version"] == "heuristic_v2"
        assert "extractor_versions" in facet

        # From ToolCallStatsExtractor
        assert "tool_calls_total" in facet
        assert "tool_calls_by_name" in facet

        # From ErrorAnalysisExtractor
        assert "tool_errors_total" in facet
        assert "error_rate" in facet

        # From InterventionExtractor
        assert "intervention_count" in facet

        # From TimingExtractor
        assert "session_duration_ms" in facet

        # From FilePatternExtractor
        assert "primary_language" in facet
        assert "files_pattern" in facet

        # From TokenUsageExtractor
        assert "total_tokens" in facet

        # From ConversationFlowExtractor
        assert "user_messages_count" in facet
        assert "conversation_pattern" in facet

        # From OutcomeSignalsExtractor
        assert "outcome" in facet
        assert "completion_confidence" in facet

        # From GoalClassificationExtractor
        assert "underlying_goal" in facet
        assert "task_type" in facet
        assert "session_type" in facet

        # From ComplexityExtractor
        assert "complexity_score" in facet
        assert "brief_summary" in facet

    def test_extract_facet_minimum_30_attributes(self):
        """Spec requires >= 30 attributes per facet."""
        from sagg.analytics.insights.extractors import extract_facet
        session = _session_with_tool_calls([("Read", False)], user_text="hello")
        facet = extract_facet(session)
        assert len(facet) >= 30

    def test_all_extractors_registered(self):
        """Check that all 10 extractors are in the registry."""
        from sagg.analytics.insights.extractors import EXTRACTORS
        assert len(EXTRACTORS) >= 10
        names = [e.name for e in EXTRACTORS]
        assert "tool_call_stats" in names
        assert "error_analysis" in names
        assert "intervention" in names
        assert "timing" in names
        assert "file_patterns" in names
        assert "token_usage" in names
        assert "conversation_flow" in names
        assert "outcome_signals" in names
        assert "goal_classification" in names
        assert "complexity" in names

    def test_extractor_versions_tracked(self):
        from sagg.analytics.insights.extractors import extract_facet
        session = _session_with_tool_calls([("Read", False)])
        facet = extract_facet(session)
        versions = facet["extractor_versions"]
        assert isinstance(versions, dict)
        assert len(versions) >= 10

    def test_extract_facet_empty_session(self):
        """Pipeline handles empty sessions gracefully."""
        from sagg.analytics.insights.extractors import extract_facet
        session = _make_session(turns=[])
        facet = extract_facet(session)
        assert facet["tool_calls_total"] == 0
        assert facet["outcome"] == "abandoned"
        assert facet["complexity_score"] == 1

    def test_backward_compatible_keys(self):
        """V2 facet still has keys needed by existing store.upsert_facet."""
        from sagg.analytics.insights.extractors import extract_facet
        session = _session_with_tool_calls([("Read", False)], user_text="fix the bug")
        facet = extract_facet(session)

        # Keys required by existing session_facets table columns
        required_v1_keys = {
            "session_id", "source", "analyzed_at", "analyzer_version",
            "underlying_goal", "goal_categories", "task_type",
            "outcome", "completion_confidence",
            "session_type", "complexity_score",
            "friction_counts", "friction_detail", "friction_score",
            "tools_that_helped", "tools_that_didnt", "tool_helpfulness",
            "primary_language", "files_pattern",
            "brief_summary", "key_decisions",
        }
        for key in required_v1_keys:
            assert key in facet, f"Missing backward-compatible key: {key}"
