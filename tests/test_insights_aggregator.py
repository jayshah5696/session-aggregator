"""Tests for insights report aggregation logic."""

import time

import pytest
from datetime import datetime, timezone

from sagg.analytics.insights.aggregator import (
    generate_insights,
    _build_tool_comparison,
    _cluster_project_areas,
    _aggregate_friction,
    _compute_trends,
    _generate_suggestions,
    _build_at_a_glance,
    _pick_fun_ending,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_facet(
    source="claude",
    task_type="feature",
    outcome="fully_achieved",
    friction_score=0.0,
    goal_categories=None,
    friction_counts=None,
    complexity_score=3,
):
    return {
        "session_id": f"test-{source}-{task_type}",
        "source": source,
        "analyzed_at": int(time.time()),
        "analyzer_version": "heuristic_v1",
        "underlying_goal": f"Test {task_type} goal",
        "goal_categories": goal_categories or {task_type: 1},
        "task_type": task_type,
        "outcome": outcome,
        "completion_confidence": 0.7,
        "session_type": "single_task",
        "complexity_score": complexity_score,
        "friction_counts": friction_counts or {},
        "friction_detail": None,
        "friction_score": friction_score,
        "tools_that_helped": [],
        "tools_that_didnt": [],
        "tool_helpfulness": "moderately",
        "primary_language": "python",
        "files_pattern": None,
        "brief_summary": f"Test {task_type} session",
        "key_decisions": [],
    }


# ---------------------------------------------------------------------------
# TestGenerateInsights
# ---------------------------------------------------------------------------

class TestGenerateInsights:
    """Tests for the top-level generate_insights function."""

    def _range(self):
        return (
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 31, tzinfo=timezone.utc),
        )

    def test_empty_facets_returns_empty_report(self):
        start, end = self._range()
        report = generate_insights([], {}, start, end)

        assert report["total_sessions"] == 0
        assert report["total_facets"] == 0
        assert report["project_areas"] == []
        assert report["tool_comparison"]["tool_metrics"] == []
        assert report["friction_analysis"]["total_friction_sessions"] == 0
        assert report["suggestions"]["agents_md_additions"] == []

    def test_basic_report_structure(self):
        """All top-level keys are present in a populated report."""
        start, end = self._range()
        facets = [make_facet()]
        stats = {"total_sessions": 1}
        report = generate_insights(facets, stats, start, end)

        expected_keys = {
            "generated_at",
            "range_start",
            "range_end",
            "total_sessions",
            "total_facets",
            "at_a_glance",
            "project_areas",
            "interaction_style",
            "impressive_workflows",
            "friction_analysis",
            "tool_comparison",
            "suggestions",
            "trends",
            "fun_ending",
        }
        assert expected_keys == set(report.keys())

    def test_report_with_single_tool(self):
        start, end = self._range()
        facets = [make_facet(source="claude"), make_facet(source="claude", task_type="bugfix")]
        stats = {"total_sessions": 2}
        report = generate_insights(facets, stats, start, end)

        assert report["total_sessions"] == 2
        assert report["total_facets"] == 2
        assert report["tool_comparison"]["tools_analyzed"] == ["claude"]

    def test_report_with_multiple_tools(self):
        start, end = self._range()
        facets = [
            make_facet(source="claude"),
            make_facet(source="cursor"),
            make_facet(source="opencode"),
        ]
        stats = {"total_sessions": 3}
        report = generate_insights(facets, stats, start, end)

        assert report["total_facets"] == 3
        tools = report["tool_comparison"]["tools_analyzed"]
        assert sorted(tools) == ["claude", "cursor", "opencode"]


# ---------------------------------------------------------------------------
# TestBuildToolComparison
# ---------------------------------------------------------------------------

class TestBuildToolComparison:
    """Tests for _build_tool_comparison."""

    def test_single_tool(self):
        facets = [make_facet(source="claude")]
        result = _build_tool_comparison(facets)

        assert result["tools_analyzed"] == ["claude"]
        assert len(result["tool_metrics"]) == 1

        metric = result["tool_metrics"][0]
        assert metric["tool"] == "claude"
        assert metric["session_count"] == 1
        assert metric["success_rate"] == 1.0  # fully_achieved

    def test_multiple_tools_sorted_by_success(self):
        facets = [
            make_facet(source="cursor", outcome="abandoned"),
            make_facet(source="cursor", outcome="abandoned"),
            make_facet(source="claude", outcome="fully_achieved"),
            make_facet(source="claude", outcome="fully_achieved"),
        ]
        result = _build_tool_comparison(facets)
        metrics = result["tool_metrics"]

        # claude has 100% success, cursor has 0% -- sorted desc
        assert metrics[0]["tool"] == "claude"
        assert metrics[0]["success_rate"] == 1.0
        assert metrics[1]["tool"] == "cursor"
        assert metrics[1]["success_rate"] == 0.0

    def test_best_for_recommendations(self):
        facets = [
            make_facet(source="claude", task_type="feature", outcome="fully_achieved"),
            make_facet(source="cursor", task_type="feature", outcome="abandoned"),
            make_facet(source="cursor", task_type="bugfix", outcome="fully_achieved"),
            make_facet(source="claude", task_type="bugfix", outcome="abandoned"),
        ]
        result = _build_tool_comparison(facets)
        best_for = result["best_for"]

        assert best_for["feature"] == "claude"
        assert best_for["bugfix"] == "cursor"

    def test_sessions_per_tool_counts(self):
        facets = [
            make_facet(source="claude"),
            make_facet(source="claude"),
            make_facet(source="cursor"),
        ]
        result = _build_tool_comparison(facets)

        assert result["sessions_per_tool"]["claude"] == 2
        assert result["sessions_per_tool"]["cursor"] == 1


# ---------------------------------------------------------------------------
# TestClusterProjectAreas
# ---------------------------------------------------------------------------

class TestClusterProjectAreas:
    """Tests for _cluster_project_areas."""

    def test_groups_by_goal_categories(self):
        facets = [
            make_facet(goal_categories={"data_pipeline": 1}),
            make_facet(goal_categories={"data_pipeline": 1}),
            make_facet(goal_categories={"web_frontend": 1}),
        ]
        areas = _cluster_project_areas(facets)
        area_names = [a["name"] for a in areas]

        assert "Data Pipeline" in area_names
        assert "Web Frontend" in area_names

        dp = next(a for a in areas if a["name"] == "Data Pipeline")
        assert dp["session_count"] == 2

    def test_calculates_success_rate(self):
        facets = [
            make_facet(goal_categories={"testing": 1}, outcome="fully_achieved"),
            make_facet(goal_categories={"testing": 1}, outcome="abandoned"),
        ]
        areas = _cluster_project_areas(facets)
        testing = next(a for a in areas if a["name"] == "Testing")

        assert testing["success_rate"] == 0.5

    def test_limits_to_10_areas(self):
        facets = []
        for i in range(15):
            facets.append(make_facet(goal_categories={f"area_{i}": 1}))

        areas = _cluster_project_areas(facets)
        assert len(areas) <= 10


# ---------------------------------------------------------------------------
# TestAggregateFriction
# ---------------------------------------------------------------------------

class TestAggregateFriction:
    """Tests for _aggregate_friction."""

    def test_counts_friction_categories(self):
        facets = [
            make_facet(friction_counts={"retries": 3, "error_rate": 2}),
            make_facet(friction_counts={"retries": 1}),
        ]
        result = _aggregate_friction(facets)

        assert result["friction_by_category"]["retries"] == 4
        assert result["friction_by_category"]["error_rate"] == 2

    def test_friction_by_tool(self):
        facets = [
            make_facet(source="claude", friction_score=0.4),
            make_facet(source="claude", friction_score=0.6),
            make_facet(source="cursor", friction_score=0.1),
        ]
        result = _aggregate_friction(facets)

        assert result["friction_by_tool"]["claude"] == 0.5
        assert result["friction_by_tool"]["cursor"] == 0.1

    def test_identifies_friction_sessions(self):
        """Sessions with friction_score > 0.2 are counted as friction sessions."""
        facets = [
            make_facet(friction_score=0.1),  # not friction
            make_facet(friction_score=0.2),  # not friction (need > 0.2)
            make_facet(friction_score=0.3),  # friction
            make_facet(friction_score=0.8),  # friction
        ]
        result = _aggregate_friction(facets)

        assert result["total_friction_sessions"] == 2

    def test_top_patterns_sorted(self):
        facets = [
            make_facet(friction_counts={"retries": 10, "back_forth": 2}),
            make_facet(friction_counts={"retries": 5, "error_rate": 7}),
        ]
        result = _aggregate_friction(facets)
        patterns = result["top_friction_patterns"]

        # retries=15 should be first, error_rate=7 second, back_forth=2 third
        assert len(patterns) == 3
        assert patterns[0]["category"] == "retries"
        assert patterns[0]["count"] == 15
        assert patterns[1]["category"] == "error_rate"
        assert patterns[1]["count"] == 7
        assert patterns[2]["category"] == "back_forth"
        assert patterns[2]["count"] == 2


# ---------------------------------------------------------------------------
# TestComputeTrends
# ---------------------------------------------------------------------------

class TestComputeTrends:
    """Tests for _compute_trends."""

    def test_sessions_per_day(self):
        ts = int(datetime(2025, 3, 15, 12, 0, tzinfo=timezone.utc).timestamp())
        facets = [
            make_facet(),
            make_facet(),
        ]
        # Override analyzed_at to a known day
        for f in facets:
            f["analyzed_at"] = ts

        result = _compute_trends(facets)
        assert result["sessions_per_day"]["2025-03-15"] == 2

    def test_friction_trend_improving(self):
        """Second half friction < 80% of first half -> improving."""
        facets = [
            make_facet(friction_score=0.9),
            make_facet(friction_score=0.8),
            make_facet(friction_score=0.1),
            make_facet(friction_score=0.1),
        ]
        result = _compute_trends(facets)
        assert result["friction_trend"] == "improving"

    def test_friction_trend_worsening(self):
        """Second half friction > 120% of first half -> worsening."""
        facets = [
            make_facet(friction_score=0.1),
            make_facet(friction_score=0.1),
            make_facet(friction_score=0.9),
            make_facet(friction_score=0.9),
        ]
        result = _compute_trends(facets)
        assert result["friction_trend"] == "worsening"

    def test_friction_trend_stable(self):
        """Similar friction in both halves -> stable."""
        facets = [
            make_facet(friction_score=0.3),
            make_facet(friction_score=0.3),
            make_facet(friction_score=0.3),
            make_facet(friction_score=0.3),
        ]
        result = _compute_trends(facets)
        assert result["friction_trend"] == "stable"

    def test_few_facets_stable(self):
        """Fewer than 4 facets always returns stable."""
        facets = [make_facet(friction_score=0.9)]
        result = _compute_trends(facets)
        assert result["friction_trend"] == "stable"


# ---------------------------------------------------------------------------
# TestGenerateSuggestions
# ---------------------------------------------------------------------------

class TestGenerateSuggestions:
    """Tests for _generate_suggestions."""

    def _make_friction(self, by_category=None):
        return {
            "total_friction_sessions": 0,
            "friction_by_category": by_category or {},
            "friction_by_tool": {},
            "top_friction_patterns": [],
            "narrative": "",
        }

    def _make_tool_comp(self, best_for=None, tool_metrics=None):
        return {
            "tools_analyzed": [],
            "sessions_per_tool": {},
            "tool_metrics": tool_metrics or [],
            "best_for": best_for or {},
            "narrative": "",
        }

    def test_cross_tool_friction_suggests_agents_md(self):
        """When a friction category appears in >=2 tools, suggest AGENTS.md."""
        facets = [
            make_facet(source="claude", friction_counts={"retries": 4}),
            make_facet(source="cursor", friction_counts={"retries": 3}),
        ]
        friction = self._make_friction(by_category={"retries": 7})
        tool_comp = self._make_tool_comp()

        result = _generate_suggestions(facets, friction, tool_comp)
        agents_suggestions = result["agents_md_additions"]

        # Should have an AGENTS.md suggestion
        agents_targets = [s for s in agents_suggestions if s["target_file"] == "AGENTS.md"]
        assert len(agents_targets) >= 1
        assert agents_targets[0]["target_tool"] == "universal"

    def test_single_tool_friction_suggests_tool_config(self):
        """When friction is in one tool only, suggest tool-specific config file."""
        facets = [
            make_facet(source="claude", friction_counts={"retries": 5}),
        ]
        friction = self._make_friction(by_category={"retries": 5})
        tool_comp = self._make_tool_comp()

        result = _generate_suggestions(facets, friction, tool_comp)
        agents_suggestions = result["agents_md_additions"]

        tool_specific = [s for s in agents_suggestions if s["target_tool"] == "claude"]
        assert len(tool_specific) >= 1
        assert tool_specific[0]["target_file"] == "CLAUDE.md"

    def test_tool_recommendations_from_best_for(self):
        """Tool recommendations are built from best_for mapping."""
        facets = [make_facet(source="claude", task_type="feature")]
        friction = self._make_friction()
        tool_comp = self._make_tool_comp(
            best_for={"feature": "claude", "bugfix": "cursor"},
            tool_metrics=[
                {"tool": "claude", "session_count": 10, "success_rate": 0.9},
                {"tool": "cursor", "session_count": 5, "success_rate": 0.8},
            ],
        )

        result = _generate_suggestions(facets, friction, tool_comp)
        recs = result["tool_recommendations"]
        rec_map = {r["task_type"]: r["recommended_tool"] for r in recs}

        assert rec_map["feature"] == "claude"
        assert rec_map["bugfix"] == "cursor"


# ---------------------------------------------------------------------------
# TestBuildAtAGlance
# ---------------------------------------------------------------------------

class TestBuildAtAGlance:
    """Tests for _build_at_a_glance."""

    def test_includes_best_tool(self):
        tool_comp = {
            "tool_metrics": [
                {"tool": "claude", "success_rate": 0.95, "avg_friction_score": 0.1},
            ],
        }
        friction = {"narrative": ""}
        suggestions = {"tool_recommendations": []}

        result = _build_at_a_glance(tool_comp, friction, suggestions)
        assert "claude" in result["whats_working"]
        assert "95%" in result["whats_working"]

    def test_includes_friction_narrative(self):
        tool_comp = {"tool_metrics": []}
        friction = {"narrative": "Top friction: retries (12 occurrences)."}
        suggestions = {"tool_recommendations": []}

        result = _build_at_a_glance(tool_comp, friction, suggestions)
        assert "retries" in result["whats_hindering"]

    def test_includes_quick_win(self):
        tool_comp = {"tool_metrics": []}
        friction = {"narrative": ""}
        suggestions = {
            "tool_recommendations": [
                {"recommended_tool": "cursor", "task_type": "refactor"},
            ],
        }

        result = _build_at_a_glance(tool_comp, friction, suggestions)
        assert "cursor" in result["quick_wins"]
        assert "refactor" in result["quick_wins"]


# ---------------------------------------------------------------------------
# TestPickFunEnding
# ---------------------------------------------------------------------------

class TestPickFunEnding:
    """Tests for _pick_fun_ending."""

    def test_high_friction_gets_dramatic_headline(self):
        facets = [
            make_facet(friction_score=0.8, task_type="deploy"),
        ]
        result = _pick_fun_ending(facets)

        assert "dramatic" in result["headline"].lower() or "Most dramatic" in result["headline"]
        assert result["detail"] != ""

    def test_successful_complex_gets_impressive_headline(self):
        facets = [
            make_facet(
                outcome="fully_achieved",
                complexity_score=5,
                friction_score=0.1,
            ),
        ]
        result = _pick_fun_ending(facets)

        assert "impressive" in result["headline"].lower() or "Most impressive" in result["headline"]
        assert "5/5" in result["detail"]

    def test_empty_facets(self):
        result = _pick_fun_ending([])

        assert result["headline"] == ""
        assert result["detail"] == ""
