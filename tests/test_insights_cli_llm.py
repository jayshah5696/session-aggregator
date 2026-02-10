from datetime import datetime, timezone

from sagg.analytics.insights import cli_llm
from sagg.models import Message, SessionStats, SourceTool, TextPart, Turn, UnifiedSession, generate_session_id


def _make_session(user_text: str = "", assistant_text: str = "") -> UnifiedSession:
    parts_user = [TextPart(content=user_text)] if user_text else []
    parts_assistant = [TextPart(content=assistant_text)] if assistant_text else []

    messages = []
    if parts_user:
        messages.append(
            Message(
                id="u1",
                role="user",
                timestamp=datetime.now(timezone.utc),
                parts=parts_user,
            )
        )
    if parts_assistant:
        messages.append(
            Message(
                id="a1",
                role="assistant",
                timestamp=datetime.now(timezone.utc),
                parts=parts_assistant,
            )
        )

    return UnifiedSession(
        id=generate_session_id(),
        source=SourceTool.CLAUDE,
        source_id="s1",
        source_path="/tmp/s1.jsonl",
        title="T",
        project_name="p",
        project_path="/tmp/p",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        stats=SessionStats(
            turn_count=1 if messages else 0,
            message_count=len(messages),
            input_tokens=0,
            output_tokens=0,
        ),
        turns=[
            Turn(
                id="t1",
                index=0,
                started_at=datetime.now(timezone.utc),
                messages=messages,
            )
        ]
        if messages
        else [],
    )


def test_is_session_substantive_false_for_empty_session():
    session = _make_session()
    assert cli_llm.is_session_substantive(session) is False


def test_is_session_substantive_true_for_textual_session():
    session = _make_session(user_text="Please fix auth bug in middleware")
    assert cli_llm.is_session_substantive(session) is True


def test_analyze_sessions_llm_batch_parses_indexed_response(monkeypatch):
    sessions = [
        _make_session(user_text="fix bug A"),
        _make_session(user_text="write docs for module B"),
    ]

    def fake_prompt(_: str, backend_name: str | None = None) -> str:
        return (
            "["
            '{"index":0,"task_type":"bugfix","outcome":"fully_achieved","brief_summary":"A"},'
            '{"index":1,"task_type":"docs","outcome":"partially_achieved","brief_summary":"B"}'
            "]"
        )

    monkeypatch.setattr(cli_llm, "run_llm_prompt", fake_prompt)

    facets = cli_llm.analyze_sessions_llm_batch(sessions, backend_name="claude")

    assert len(facets) == 2
    assert facets[0]["task_type"] == "bugfix"
    assert facets[1]["task_type"] == "docs"
    assert facets[0]["analyzer_model"] == "claude"
