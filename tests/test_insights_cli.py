"""Tests for insights-related CLI flows."""

from datetime import datetime, timezone

from click.testing import CliRunner

from sagg.cli import cli
from sagg.models import Message, SessionStats, SourceTool, TextPart, Turn, UnifiedSession, generate_session_id


def _session_with_text(text: str) -> UnifiedSession:
    now = datetime.now(timezone.utc)
    return UnifiedSession(
        id=generate_session_id(),
        source=SourceTool.CLAUDE,
        source_id=f"src-{generate_session_id()}",
        source_path="/tmp/test-session.jsonl",
        title="Session",
        project_name="proj",
        project_path="/tmp/proj",
        created_at=now,
        updated_at=now,
        stats=SessionStats(turn_count=1, message_count=1, input_tokens=0, output_tokens=0),
        turns=[
            Turn(
                id="turn-1",
                index=0,
                started_at=now,
                messages=[
                    Message(
                        id="msg-1",
                        role="user",
                        timestamp=now,
                        parts=[TextPart(content=text)],
                    )
                ],
            )
        ],
    )


class _FakeStore:
    def __init__(self, sessions: list[UnifiedSession], existing_facets: list[dict] | None = None):
        self._sessions = sessions
        self.upserted: list[dict] = []
        self._existing_facets = existing_facets or []

    def get_unfaceted_sessions(self, **_: object) -> list[UnifiedSession]:
        return self._sessions

    def list_sessions(self, **_: object) -> list[UnifiedSession]:
        return self._sessions

    def get_session(self, session_id: str) -> UnifiedSession | None:
        for s in self._sessions:
            if s.id == session_id:
                return s
        return None

    def upsert_facet(self, facet_data: dict) -> None:
        self.upserted.append(facet_data)

    def get_facets(
        self,
        source: str | None = None,
        since: datetime | None = None,
        project: str | None = None,
        limit: int = 5000,
    ) -> list[dict]:
        del source, since, project, limit
        return self._existing_facets

    def close(self) -> None:
        return


def test_analyze_sessions_llm_skips_non_substantive_sessions(monkeypatch):
    non_substantive = _session_with_text("tiny")
    substantive = _session_with_text("Please debug auth issue and add fix")
    fake_store = _FakeStore([non_substantive, substantive])

    monkeypatch.setattr("sagg.cli.SessionStore", lambda: fake_store)

    from sagg.analytics.insights import cli_llm

    monkeypatch.setattr(cli_llm, "detect_available_backend", lambda: "claude")
    monkeypatch.setattr(
        cli_llm,
        "is_session_substantive",
        lambda session: session.id == substantive.id,
    )
    monkeypatch.setattr(
        cli_llm,
        "analyze_sessions_llm_batch",
        lambda sessions, backend_name=None: [
            {
                "session_id": sessions[0].id,
                "source": sessions[0].source.value,
                "analyzed_at": int(datetime.now(timezone.utc).timestamp()),
                "analyzer_version": "llm_v1",
                "analyzer_model": backend_name,
                "underlying_goal": "fix auth",
                "goal_categories": {},
                "task_type": "bugfix",
                "outcome": "fully_achieved",
                "completion_confidence": 0.8,
                "session_type": "single_task",
                "complexity_score": 3,
                "friction_counts": {},
                "friction_detail": None,
                "friction_score": 0.0,
                "tools_that_helped": [],
                "tools_that_didnt": [],
                "tool_helpfulness": "very",
                "primary_language": "python",
                "files_pattern": None,
                "brief_summary": "Fixed authentication flow.",
                "key_decisions": [],
            }
        ],
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["analyze-sessions", "--analyzer", "llm", "--since", "30d", "--batch-size", "10"],
    )

    assert result.exit_code == 0
    assert "Analyzed 1 session(s)" in result.output
    assert "1 skipped non-substantive" in result.output
    assert len(fake_store.upserted) == 1
    assert fake_store.upserted[0]["session_id"] == substantive.id


def test_analyze_sessions_llm_force_resume_skips_already_analyzed(monkeypatch):
    first = _session_with_text("Please debug auth issue and add fix")
    second = _session_with_text("Please improve docs and tests")

    existing = [
        {
            "session_id": first.id,
            "analyzer_version": "llm_v1",
        }
    ]
    fake_store = _FakeStore([first, second], existing_facets=existing)

    monkeypatch.setattr("sagg.cli.SessionStore", lambda: fake_store)

    from sagg.analytics.insights import cli_llm

    monkeypatch.setattr(cli_llm, "detect_available_backend", lambda: "claude")
    monkeypatch.setattr(cli_llm, "is_session_substantive", lambda session: True)
    monkeypatch.setattr(
        cli_llm,
        "analyze_sessions_llm_batch",
        lambda sessions, backend_name=None: [
            {
                "session_id": sessions[0].id,
                "source": sessions[0].source.value,
                "analyzed_at": int(datetime.now(timezone.utc).timestamp()),
                "analyzer_version": "llm_v1",
                "analyzer_model": backend_name,
                "underlying_goal": "goal",
                "goal_categories": {},
                "task_type": "docs",
                "outcome": "fully_achieved",
                "completion_confidence": 0.8,
                "session_type": "single_task",
                "complexity_score": 3,
                "friction_counts": {},
                "friction_detail": None,
                "friction_score": 0.0,
                "tools_that_helped": [],
                "tools_that_didnt": [],
                "tool_helpfulness": "very",
                "primary_language": "python",
                "files_pattern": None,
                "brief_summary": "Done.",
                "key_decisions": [],
            }
        ],
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "analyze-sessions",
            "--analyzer",
            "llm",
            "--since",
            "30d",
            "--batch-size",
            "10",
            "--force",
            "--resume",
        ],
    )

    assert result.exit_code == 0
    assert "1 skipped already-analyzed" in result.output
    assert len(fake_store.upserted) == 1
    assert fake_store.upserted[0]["session_id"] == second.id
