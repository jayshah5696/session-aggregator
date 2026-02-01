"""Tests for the heatmap feature."""

import pytest
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from sagg.analytics.heatmap import (
    get_activity_by_day,
    generate_heatmap_data,
    render_heatmap,
    calculate_intensity,
)
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


class TestGetActivityByDay:
    """Tests for get_activity_by_day function."""

    def test_empty_store(self, session_store):
        """Test with no sessions."""
        activity = get_activity_by_day(session_store, weeks=12, metric="sessions")
        assert activity == {}

    def test_sessions_metric(self, session_store):
        """Test counting sessions per day."""
        # Create sessions on different days
        now = datetime.now(timezone.utc)

        for i in range(3):
            session = UnifiedSession(
                id=generate_session_id(),
                source=SourceTool.OPENCODE,
                source_id=f"test-session-{i}",
                source_path="/tmp/test/session.json",
                title=f"Test Session {i}",
                project_name="test-project",
                project_path="/tmp/test-project",
                created_at=now - timedelta(days=i),
                updated_at=now - timedelta(days=i),
                stats=SessionStats(
                    turn_count=1,
                    message_count=2,
                    input_tokens=100 * (i + 1),
                    output_tokens=50 * (i + 1),
                ),
                turns=[],
            )
            session_store.save_session(session)

        activity = get_activity_by_day(session_store, weeks=12, metric="sessions")

        # Should have 3 days with activity
        assert len(activity) == 3

        # Each day should have 1 session
        for count in activity.values():
            assert count == 1

    def test_tokens_metric(self, session_store):
        """Test counting tokens per day."""
        now = datetime.now(timezone.utc)

        # Create 2 sessions on the same day with different token counts
        for i in range(2):
            session = UnifiedSession(
                id=generate_session_id(),
                source=SourceTool.OPENCODE,
                source_id=f"test-session-tokens-{i}",
                source_path="/tmp/test/session.json",
                title=f"Test Session {i}",
                project_name="test-project",
                project_path="/tmp/test-project",
                created_at=now,
                updated_at=now,
                stats=SessionStats(
                    turn_count=1,
                    message_count=2,
                    input_tokens=1000,
                    output_tokens=500,
                ),
                turns=[],
            )
            session_store.save_session(session)

        activity = get_activity_by_day(session_store, weeks=12, metric="tokens")

        # Should have 1 day
        assert len(activity) == 1

        # Total tokens should be 2 * (1000 + 500) = 3000
        today_str = now.strftime("%Y-%m-%d")
        assert activity[today_str] == 3000

    def test_respects_weeks_limit(self, session_store):
        """Test that only sessions within the weeks limit are counted."""
        now = datetime.now(timezone.utc)

        # Session from 2 weeks ago (should be included for 12 weeks)
        session1 = UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.OPENCODE,
            source_id="test-session-recent",
            source_path="/tmp/test/session.json",
            title="Recent Session",
            project_name="test-project",
            project_path="/tmp/test-project",
            created_at=now - timedelta(weeks=2),
            updated_at=now - timedelta(weeks=2),
            stats=SessionStats(turn_count=1, message_count=2, input_tokens=100, output_tokens=50),
            turns=[],
        )
        session_store.save_session(session1)

        # Session from 20 weeks ago (should be excluded for 12 weeks)
        session2 = UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.OPENCODE,
            source_id="test-session-old",
            source_path="/tmp/test/session.json",
            title="Old Session",
            project_name="test-project",
            project_path="/tmp/test-project",
            created_at=now - timedelta(weeks=20),
            updated_at=now - timedelta(weeks=20),
            stats=SessionStats(turn_count=1, message_count=2, input_tokens=100, output_tokens=50),
            turns=[],
        )
        session_store.save_session(session2)

        # With 12 weeks, only recent session should be included
        activity = get_activity_by_day(session_store, weeks=12, metric="sessions")
        assert len(activity) == 1

        # With 24 weeks, both sessions should be included
        activity = get_activity_by_day(session_store, weeks=24, metric="sessions")
        assert len(activity) == 2


class TestCalculateIntensity:
    """Tests for calculate_intensity function."""

    def test_zero_value(self):
        """Test zero value returns intensity 0."""
        assert calculate_intensity(0, max_value=100) == 0

    def test_max_value(self):
        """Test max value returns intensity 4."""
        assert calculate_intensity(100, max_value=100) == 4

    def test_quartiles(self):
        """Test quartile-based intensity levels."""
        # 0-25% -> 1, 25-50% -> 2, 50-75% -> 3, 75-100% -> 4
        assert calculate_intensity(10, max_value=100) == 1
        assert calculate_intensity(30, max_value=100) == 2
        assert calculate_intensity(60, max_value=100) == 3
        assert calculate_intensity(80, max_value=100) == 4

    def test_handles_max_zero(self):
        """Test when max_value is zero."""
        assert calculate_intensity(0, max_value=0) == 0
        assert calculate_intensity(5, max_value=0) == 4  # Any positive value with max=0


class TestGenerateHeatmapData:
    """Tests for generate_heatmap_data function."""

    def test_empty_activity(self):
        """Test with no activity data."""
        data = generate_heatmap_data({}, weeks=4)

        # Should return 7 rows (Sun-Sat) x weeks columns
        assert len(data) == 7
        for row in data:
            assert len(row) == 4
            assert all(cell == 0 for cell in row)

    def test_single_day_activity(self):
        """Test with activity on a single day."""
        # Use a known Sunday
        sunday = datetime(2026, 1, 25, tzinfo=timezone.utc)  # This is a Sunday
        activity = {sunday.strftime("%Y-%m-%d"): 5}

        data = generate_heatmap_data(activity, weeks=4)

        # Should have 7 rows
        assert len(data) == 7

        # Find the cell that should have data
        # Row 0 is Sunday
        total_cells_with_data = sum(1 for row in data for cell in row if cell > 0)
        assert total_cells_with_data == 1

    def test_correct_dimensions(self):
        """Test output dimensions match weeks parameter."""
        data = generate_heatmap_data({}, weeks=12)
        assert len(data) == 7
        for row in data:
            assert len(row) == 12

        data = generate_heatmap_data({}, weeks=24)
        assert len(data) == 7
        for row in data:
            assert len(row) == 24


class TestRenderHeatmap:
    """Tests for render_heatmap function."""

    def test_empty_heatmap(self):
        """Test rendering an empty heatmap."""
        data = [[0] * 4 for _ in range(7)]
        output = render_heatmap(data, legend=False)

        # Should contain day labels
        assert "Sun" in output
        assert "Mon" in output
        assert "Sat" in output

    def test_with_activity(self):
        """Test rendering a heatmap with activity."""
        # Create data with various intensities
        data = [
            [1, 2, 3, 4],  # Sun
            [0, 1, 2, 3],  # Mon
            [0, 0, 1, 2],  # Tue
            [0, 0, 0, 1],  # Wed
            [0, 0, 0, 0],  # Thu
            [4, 3, 2, 1],  # Fri
            [2, 2, 2, 2],  # Sat
        ]
        output = render_heatmap(data, legend=False)

        # Should contain block characters for different intensities
        assert "░" in output or "▒" in output or "▓" in output or "█" in output

    def test_with_legend(self):
        """Test that legend is included when requested."""
        data = [[0] * 4 for _ in range(7)]

        output_with_legend = render_heatmap(data, legend=True)
        output_without_legend = render_heatmap(data, legend=False)

        # Legend should contain "Less" and "More"
        assert "Less" in output_with_legend
        assert "More" in output_with_legend
        assert "Less" not in output_without_legend

    def test_intensity_characters(self):
        """Test that correct characters are used for intensities."""
        # Single cell with each intensity
        for intensity in range(5):
            data = [[intensity] + [0] * 3 for _ in range(7)]
            output = render_heatmap(data, legend=False)

            if intensity == 0:
                # Should have spaces for empty cells
                pass
            elif intensity == 1:
                assert "░" in output
            elif intensity == 2:
                assert "▒" in output
            elif intensity == 3:
                assert "▓" in output
            elif intensity == 4:
                assert "█" in output
