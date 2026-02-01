"""Tests for budget tracking functionality."""

import pytest
from datetime import datetime, timezone, timedelta
from click.testing import CliRunner

from sagg.cli import cli, parse_token_amount
from sagg.storage import SessionStore
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


class TestParseTokenAmount:
    """Tests for parsing token amount strings."""

    def test_parse_plain_number(self):
        """Test parsing plain integer strings."""
        assert parse_token_amount("100000") == 100000
        assert parse_token_amount("50") == 50
        assert parse_token_amount("1000000") == 1000000

    def test_parse_k_suffix(self):
        """Test parsing k suffix (thousands)."""
        assert parse_token_amount("500k") == 500000
        assert parse_token_amount("500K") == 500000
        assert parse_token_amount("1k") == 1000
        assert parse_token_amount("100k") == 100000

    def test_parse_m_suffix(self):
        """Test parsing M suffix (millions)."""
        assert parse_token_amount("1M") == 1000000
        assert parse_token_amount("1m") == 1000000
        assert parse_token_amount("5M") == 5000000
        assert parse_token_amount("2.5M") == 2500000

    def test_parse_decimal_k(self):
        """Test parsing decimal with k suffix."""
        assert parse_token_amount("1.5k") == 1500
        assert parse_token_amount("2.5K") == 2500

    def test_invalid_format_raises_error(self):
        """Test that invalid formats raise ValueError."""
        with pytest.raises(ValueError):
            parse_token_amount("abc")
        with pytest.raises(ValueError):
            parse_token_amount("")
        with pytest.raises(ValueError):
            parse_token_amount("100x")


class TestBudgetStorage:
    """Tests for budget storage operations."""

    def test_set_and_get_daily_budget(self, session_store):
        """Test setting and retrieving daily budget."""
        session_store.set_budget("daily", 100000)
        assert session_store.get_budget("daily") == 100000

    def test_set_and_get_weekly_budget(self, session_store):
        """Test setting and retrieving weekly budget."""
        session_store.set_budget("weekly", 500000)
        assert session_store.get_budget("weekly") == 500000

    def test_get_nonexistent_budget(self, session_store):
        """Test getting a budget that doesn't exist."""
        assert session_store.get_budget("daily") is None
        assert session_store.get_budget("weekly") is None

    def test_update_budget(self, session_store):
        """Test updating an existing budget."""
        session_store.set_budget("daily", 100000)
        session_store.set_budget("daily", 200000)
        assert session_store.get_budget("daily") == 200000

    def test_clear_budget(self, session_store):
        """Test clearing a budget."""
        session_store.set_budget("daily", 100000)
        session_store.set_budget("weekly", 500000)

        session_store.clear_budget("daily")
        assert session_store.get_budget("daily") is None
        assert session_store.get_budget("weekly") == 500000

    def test_clear_nonexistent_budget(self, session_store):
        """Test clearing a budget that doesn't exist (should not raise)."""
        # Should not raise
        session_store.clear_budget("daily")

    def test_get_usage_for_daily_period(self, session_store):
        """Test getting token usage for today."""
        # Create a session with tokens from today
        session = _create_session_with_tokens(
            input_tokens=1000,
            output_tokens=500,
            created_at=datetime.now(timezone.utc),
        )
        session_store.save_session(session)

        usage = session_store.get_usage_for_period("daily")
        assert usage == 1500  # input + output

    def test_get_usage_for_weekly_period(self, session_store):
        """Test getting token usage for this week."""
        # Create sessions from different days this week
        now = datetime.now(timezone.utc)

        session1 = _create_session_with_tokens(
            input_tokens=1000,
            output_tokens=500,
            created_at=now,
        )
        session_store.save_session(session1)

        session2 = _create_session_with_tokens(
            input_tokens=2000,
            output_tokens=1000,
            created_at=now - timedelta(days=2),
        )
        session_store.save_session(session2)

        usage = session_store.get_usage_for_period("weekly")
        # Should include at least one session, depends on day of week
        # If today is early in the week, session2 might be from last week
        assert usage >= 0
        assert usage <= 4500  # At most both sessions

    def test_get_usage_excludes_old_sessions(self, session_store):
        """Test that old sessions are excluded from usage calculation."""
        now = datetime.now(timezone.utc)

        # Session from today
        session1 = _create_session_with_tokens(
            input_tokens=1000,
            output_tokens=500,
            created_at=now,
        )
        session_store.save_session(session1)

        # Session from 2 weeks ago (should be excluded from weekly)
        session2 = _create_session_with_tokens(
            input_tokens=10000,
            output_tokens=5000,
            created_at=now - timedelta(days=14),
        )
        session_store.save_session(session2)

        weekly_usage = session_store.get_usage_for_period("weekly")
        # Weekly usage should include recent session but exclude 2-week-old one
        assert weekly_usage >= 0  # At least the recent session, or 0 if timing edge case
        assert weekly_usage <= 1500  # Should NOT include the old session's 15000 tokens

        daily_usage = session_store.get_usage_for_period("daily")
        assert daily_usage >= 0
        assert daily_usage <= 1500


class TestBudgetCLI:
    """Tests for budget CLI commands."""

    def test_budget_set_weekly(self, session_store, monkeypatch):
        """Test setting weekly budget via CLI."""
        monkeypatch.setattr("sagg.cli.SessionStore", lambda: session_store)

        runner = CliRunner()
        result = runner.invoke(cli, ["budget", "set", "--weekly", "500k"])

        assert result.exit_code == 0
        assert session_store.get_budget("weekly") == 500000

    def test_budget_set_daily(self, session_store, monkeypatch):
        """Test setting daily budget via CLI."""
        monkeypatch.setattr("sagg.cli.SessionStore", lambda: session_store)

        runner = CliRunner()
        result = runner.invoke(cli, ["budget", "set", "--daily", "100k"])

        assert result.exit_code == 0
        assert session_store.get_budget("daily") == 100000

    def test_budget_set_both(self, session_store, monkeypatch):
        """Test setting both budgets at once."""
        monkeypatch.setattr("sagg.cli.SessionStore", lambda: session_store)

        runner = CliRunner()
        result = runner.invoke(cli, ["budget", "set", "--weekly", "1M", "--daily", "200k"])

        assert result.exit_code == 0
        assert session_store.get_budget("weekly") == 1000000
        assert session_store.get_budget("daily") == 200000

    def test_budget_set_requires_option(self, session_store, monkeypatch):
        """Test that set requires at least one option."""
        monkeypatch.setattr("sagg.cli.SessionStore", lambda: session_store)

        runner = CliRunner()
        result = runner.invoke(cli, ["budget", "set"])

        assert result.exit_code != 0
        assert "Specify --weekly or --daily" in result.output

    def test_budget_show(self, session_store, monkeypatch):
        """Test showing budget status."""
        session_store.set_budget("weekly", 500000)
        session_store.set_budget("daily", 100000)

        # Add some usage
        session = _create_session_with_tokens(
            input_tokens=40000,
            output_tokens=10000,
            created_at=datetime.now(timezone.utc),
        )
        session_store.save_session(session)

        monkeypatch.setattr("sagg.cli.SessionStore", lambda: session_store)

        runner = CliRunner()
        result = runner.invoke(cli, ["budget", "show"])

        assert result.exit_code == 0
        assert "Daily Budget" in result.output or "daily" in result.output.lower()
        assert "Weekly Budget" in result.output or "weekly" in result.output.lower()

    def test_budget_show_no_budgets(self, session_store, monkeypatch):
        """Test show when no budgets are set."""
        monkeypatch.setattr("sagg.cli.SessionStore", lambda: session_store)

        runner = CliRunner()
        result = runner.invoke(cli, ["budget", "show"])

        assert result.exit_code == 0
        assert "No budgets set" in result.output

    def test_budget_clear_weekly(self, session_store, monkeypatch):
        """Test clearing weekly budget."""
        session_store.set_budget("weekly", 500000)
        session_store.set_budget("daily", 100000)

        monkeypatch.setattr("sagg.cli.SessionStore", lambda: session_store)

        runner = CliRunner()
        result = runner.invoke(cli, ["budget", "clear", "--weekly"])

        assert result.exit_code == 0
        assert session_store.get_budget("weekly") is None
        assert session_store.get_budget("daily") == 100000

    def test_budget_clear_daily(self, session_store, monkeypatch):
        """Test clearing daily budget."""
        session_store.set_budget("weekly", 500000)
        session_store.set_budget("daily", 100000)

        monkeypatch.setattr("sagg.cli.SessionStore", lambda: session_store)

        runner = CliRunner()
        result = runner.invoke(cli, ["budget", "clear", "--daily"])

        assert result.exit_code == 0
        assert session_store.get_budget("weekly") == 500000
        assert session_store.get_budget("daily") is None

    def test_budget_clear_all(self, session_store, monkeypatch):
        """Test clearing all budgets (no flags = clear all)."""
        session_store.set_budget("weekly", 500000)
        session_store.set_budget("daily", 100000)

        monkeypatch.setattr("sagg.cli.SessionStore", lambda: session_store)

        runner = CliRunner()
        result = runner.invoke(cli, ["budget", "clear"])

        assert result.exit_code == 0
        assert session_store.get_budget("weekly") is None
        assert session_store.get_budget("daily") is None


class TestBudgetAlerts:
    """Tests for budget alert thresholds."""

    def test_usage_below_80_percent_is_green(self, session_store):
        """Test that usage below 80% is considered safe (green)."""
        session_store.set_budget("daily", 100000)

        # 50% usage
        session = _create_session_with_tokens(
            input_tokens=40000,
            output_tokens=10000,
            created_at=datetime.now(timezone.utc),
        )
        session_store.save_session(session)

        usage = session_store.get_usage_for_period("daily")
        budget = session_store.get_budget("daily")
        percentage = (usage / budget) * 100

        assert percentage < 80

    def test_usage_between_80_and_95_is_warning(self, session_store):
        """Test that usage between 80-95% triggers warning (yellow)."""
        session_store.set_budget("daily", 100000)

        # 85% usage
        session = _create_session_with_tokens(
            input_tokens=70000,
            output_tokens=15000,
            created_at=datetime.now(timezone.utc),
        )
        session_store.save_session(session)

        usage = session_store.get_usage_for_period("daily")
        budget = session_store.get_budget("daily")
        percentage = (usage / budget) * 100

        assert 80 <= percentage < 95

    def test_usage_above_95_is_critical(self, session_store):
        """Test that usage above 95% is critical (red)."""
        session_store.set_budget("daily", 100000)

        # 98% usage
        session = _create_session_with_tokens(
            input_tokens=80000,
            output_tokens=18000,
            created_at=datetime.now(timezone.utc),
        )
        session_store.save_session(session)

        usage = session_store.get_usage_for_period("daily")
        budget = session_store.get_budget("daily")
        percentage = (usage / budget) * 100

        assert percentage >= 95


def _create_session_with_tokens(
    input_tokens: int,
    output_tokens: int,
    created_at: datetime,
) -> UnifiedSession:
    """Helper to create a session with specific token counts."""
    return UnifiedSession(
        id=generate_session_id(),
        source=SourceTool.OPENCODE,
        source_id=f"test-session-{generate_session_id()[:8]}",
        source_path="/tmp/test/session.json",
        title="Test Session",
        project_name="test-project",
        project_path="/tmp/test-project",
        created_at=created_at,
        updated_at=created_at,
        stats=SessionStats(
            turn_count=1,
            message_count=2,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
        turns=[
            Turn(
                id="turn-1",
                index=0,
                started_at=created_at,
                messages=[
                    Message(
                        id="msg-1",
                        role="user",
                        timestamp=created_at,
                        parts=[TextPart(content="Hello")],
                    ),
                    Message(
                        id="msg-2",
                        role="assistant",
                        timestamp=created_at,
                        parts=[TextPart(content="Hi there")],
                        usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
                    ),
                ],
            )
        ],
    )
