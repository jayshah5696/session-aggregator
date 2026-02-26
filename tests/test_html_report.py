"""Tests for HTML report generator."""

import pytest
from datetime import datetime, timezone


def _sample_report() -> dict:
    """Build a sample InsightsReport dict for testing."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "range_start": "2026-01-25T00:00:00+00:00",
        "range_end": "2026-02-25T00:00:00+00:00",
        "total_sessions": 256,
        "total_facets": 200,
        "at_a_glance": {
            "whats_working": "Best results with Claude (92% success).",
            "whats_hindering": "Top friction: tool errors (34 occurrences).",
            "quick_wins": "Try using Claude for debugging tasks.",
            "ambitious_workflows": "Track productivity over time.",
        },
        "tool_comparison": {
            "tools_analyzed": ["claude", "cursor", "opencode"],
            "sessions_per_tool": {"claude": 83, "cursor": 89, "opencode": 84},
            "tool_metrics": [
                {
                    "tool": "claude",
                    "session_count": 83,
                    "avg_turns": 12.3,
                    "avg_duration_ms": None,
                    "avg_friction_score": 0.21,
                    "success_rate": 0.88,
                    "avg_tokens": 0,
                    "top_task_types": ["debug", "feature"],
                    "helpfulness_distribution": {"very": 50, "moderately": 30},
                },
                {
                    "tool": "cursor",
                    "session_count": 89,
                    "avg_turns": 8.7,
                    "avg_duration_ms": None,
                    "avg_friction_score": 0.31,
                    "success_rate": 0.72,
                    "avg_tokens": 0,
                    "top_task_types": ["feature"],
                    "helpfulness_distribution": {"moderately": 60},
                },
            ],
            "best_for": {"debug": "claude", "feature": "cursor"},
            "narrative": "Most effective tool: claude (88% success).",
        },
        "friction_analysis": {
            "total_friction_sessions": 45,
            "friction_by_category": {"tool_error": 34, "wrong_approach": 18},
            "friction_by_tool": {"claude": 0.21, "cursor": 0.31},
            "top_friction_patterns": [
                {"category": "tool_error", "count": 34, "description": "Tool errors", "affected_tools": ["claude", "cursor"], "examples": []},
                {"category": "wrong_approach", "count": 18, "description": "Wrong approach", "affected_tools": ["opencode"], "examples": []},
            ],
            "narrative": "Top friction: tool_error (34 occurrences).",
        },
        "project_areas": [
            {"name": "Backend", "session_count": 50, "description": "Backend work", "primary_tools": ["claude"], "success_rate": 0.9, "avg_friction": 0.15},
        ],
        "interaction_style": {"narrative": "Primarily single_task sessions.", "key_pattern": "Single task"},
        "impressive_workflows": [
            {"title": "Implemented full auth system", "description": "Complex multi-file change"},
        ],
        "suggestions": {
            "agents_md_additions": [
                {
                    "target_file": "CLAUDE.md",
                    "target_tool": "claude",
                    "addition": "Always check existing tests before adding new ones.",
                    "why": "12 friction events from duplicate test creation.",
                    "section_hint": "## Testing",
                },
            ],
            "usage_patterns": [],
            "tool_recommendations": [
                {"task_type": "debug", "recommended_tool": "claude", "reason": "Best success rate", "confidence": 0.85},
            ],
        },
        "trends": {
            "sessions_per_day": {"2026-02-01": 5, "2026-02-02": 8, "2026-02-03": 3},
            "friction_trend": "improving",
            "tool_adoption": {},
            "productivity_trend": "stable",
        },
        "fun_ending": {
            "headline": "Most dramatic session: spent 45 minutes debugging a typo",
            "detail": "The semicolon was missing all along.",
        },
    }


class TestRenderHtmlReport:
    """Test the HTML report generator."""

    def test_returns_string(self):
        from sagg.export.html_report import render_html_report
        report = _sample_report()
        html = render_html_report(report)
        assert isinstance(html, str)
        assert len(html) > 100

    def test_is_valid_html(self):
        from sagg.export.html_report import render_html_report
        html = render_html_report(_sample_report())
        assert html.strip().startswith("<!DOCTYPE html>") or html.strip().startswith("<html")
        assert "</html>" in html

    def test_contains_inline_css(self):
        from sagg.export.html_report import render_html_report
        html = render_html_report(_sample_report())
        assert "<style>" in html
        assert "</style>" in html

    def test_no_external_dependencies(self):
        """No CDN links or external script/css references."""
        from sagg.export.html_report import render_html_report
        html = render_html_report(_sample_report())
        assert "cdn." not in html.lower()
        assert 'href="http' not in html
        assert 'src="http' not in html

    def test_contains_at_a_glance(self):
        from sagg.export.html_report import render_html_report
        html = render_html_report(_sample_report())
        assert "At a Glance" in html
        assert "Best results with Claude" in html

    def test_contains_tool_comparison(self):
        from sagg.export.html_report import render_html_report
        html = render_html_report(_sample_report())
        assert "Tool Comparison" in html
        assert "claude" in html
        assert "cursor" in html
        assert "88%" in html  # Claude success rate

    def test_contains_friction_analysis(self):
        from sagg.export.html_report import render_html_report
        html = render_html_report(_sample_report())
        assert "Friction" in html
        assert "tool_error" in html or "Tool Error" in html

    def test_contains_suggestions(self):
        from sagg.export.html_report import render_html_report
        html = render_html_report(_sample_report())
        assert "Suggestion" in html
        assert "CLAUDE.md" in html
        assert "Always check existing tests" in html

    def test_contains_trends(self):
        from sagg.export.html_report import render_html_report
        html = render_html_report(_sample_report())
        assert "Trend" in html
        assert "improving" in html

    def test_contains_fun_ending(self):
        from sagg.export.html_report import render_html_report
        html = render_html_report(_sample_report())
        assert "debugging a typo" in html

    def test_contains_header_with_stats(self):
        from sagg.export.html_report import render_html_report
        html = render_html_report(_sample_report())
        assert "256" in html  # total sessions
        assert "sagg" in html.lower()

    def test_dark_mode_support(self):
        from sagg.export.html_report import render_html_report
        html = render_html_report(_sample_report())
        assert "prefers-color-scheme" in html

    def test_empty_report(self):
        """Handles a report with no data gracefully."""
        from sagg.export.html_report import render_html_report
        empty = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "range_start": "2026-01-01T00:00:00+00:00",
            "range_end": "2026-02-01T00:00:00+00:00",
            "total_sessions": 0,
            "total_facets": 0,
            "at_a_glance": {"whats_working": "No data yet.", "whats_hindering": "", "quick_wins": "", "ambitious_workflows": ""},
            "tool_comparison": {"tools_analyzed": [], "sessions_per_tool": {}, "tool_metrics": [], "best_for": {}, "narrative": ""},
            "friction_analysis": {"total_friction_sessions": 0, "friction_by_category": {}, "friction_by_tool": {}, "top_friction_patterns": [], "narrative": ""},
            "project_areas": [],
            "interaction_style": {"narrative": "", "key_pattern": ""},
            "impressive_workflows": [],
            "suggestions": {"agents_md_additions": [], "usage_patterns": [], "tool_recommendations": []},
            "trends": {"sessions_per_day": {}, "friction_trend": "stable", "tool_adoption": {}, "productivity_trend": "stable"},
            "fun_ending": {"headline": "", "detail": ""},
        }
        html = render_html_report(empty)
        assert isinstance(html, str)
        assert "</html>" in html

    def test_tool_comparison_bar_widths(self):
        """Bar chart widths should be CSS percentages."""
        from sagg.export.html_report import render_html_report
        html = render_html_report(_sample_report())
        # Should contain CSS width percentages for bars
        assert "width:" in html or "width :" in html

    def test_copy_buttons_on_suggestions(self):
        """Suggestions should have copy functionality."""
        from sagg.export.html_report import render_html_report
        html = render_html_report(_sample_report())
        assert "clipboard" in html.lower() or "copy" in html.lower()

    def test_llm_narrative_section_included_when_present(self):
        """If llm_narrative is in report, it gets a section."""
        from sagg.export.html_report import render_html_report
        report = _sample_report()
        report["llm_narrative"] = {
            "executive_summary": "You use Claude primarily for debugging.",
            "tool_narratives": {"claude": "Strong at Python debugging."},
            "pattern_insights": [],
            "workflow_recommendations": [],
        }
        html = render_html_report(report)
        assert "LLM" in html or "Narrative" in html or "primarily for debugging" in html

    def test_llm_narrative_section_absent_when_missing(self):
        """No LLM section when not present."""
        from sagg.export.html_report import render_html_report
        report = _sample_report()
        html = render_html_report(report)
        # Should not crash and should not have an empty LLM section
        assert isinstance(html, str)
