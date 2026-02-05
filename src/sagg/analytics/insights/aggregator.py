"""Insights report aggregation from session facets.

Aggregates per-session facets into a cross-tool InsightsReport with
tool comparison, friction analysis, trends, and suggestions.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagg.storage import SessionStore


def generate_insights(
    facets: list[dict],
    stats: dict,
    range_start: datetime,
    range_end: datetime,
) -> dict:
    """Generate an InsightsReport from aggregated facets.

    Args:
        facets: List of facet dicts from store.get_facets().
        stats: Aggregate stats from store.get_stats().
        range_start: Start of the analysis range.
        range_end: End of the analysis range.

    Returns:
        Dictionary matching InsightsReport schema.
    """
    if not facets:
        return _empty_report(range_start, range_end)

    tool_comparison = _build_tool_comparison(facets)
    project_areas = _cluster_project_areas(facets)
    friction = _aggregate_friction(facets)
    style = _analyze_interaction_style(facets, stats)
    workflows = _find_impressive_workflows(facets)
    trends = _compute_trends(facets)
    suggestions = _generate_suggestions(facets, friction, tool_comparison)
    fun = _pick_fun_ending(facets)

    # At a glance
    at_a_glance = _build_at_a_glance(tool_comparison, friction, suggestions)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "range_start": range_start.isoformat(),
        "range_end": range_end.isoformat(),
        "total_sessions": stats.get("total_sessions", 0),
        "total_facets": len(facets),
        "at_a_glance": at_a_glance,
        "project_areas": project_areas,
        "interaction_style": style,
        "impressive_workflows": workflows,
        "friction_analysis": friction,
        "tool_comparison": tool_comparison,
        "suggestions": suggestions,
        "trends": trends,
        "fun_ending": fun,
    }


def _empty_report(range_start: datetime, range_end: datetime) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "range_start": range_start.isoformat(),
        "range_end": range_end.isoformat(),
        "total_sessions": 0,
        "total_facets": 0,
        "at_a_glance": {"whats_working": "No data yet.", "whats_hindering": "", "quick_wins": "", "ambitious_workflows": ""},
        "project_areas": [],
        "interaction_style": {"narrative": "", "key_pattern": ""},
        "impressive_workflows": [],
        "friction_analysis": {"total_friction_sessions": 0, "friction_by_category": {}, "friction_by_tool": {}, "top_friction_patterns": [], "narrative": ""},
        "tool_comparison": {"tools_analyzed": [], "sessions_per_tool": {}, "tool_metrics": [], "best_for": {}, "narrative": ""},
        "suggestions": {"agents_md_additions": [], "usage_patterns": [], "tool_recommendations": []},
        "trends": {"sessions_per_day": {}, "friction_trend": "stable", "tool_adoption": {}, "productivity_trend": "stable"},
        "fun_ending": {"headline": "", "detail": ""},
    }


def _build_tool_comparison(facets: list[dict]) -> dict:
    """Build cross-tool comparison metrics."""
    by_tool: dict[str, list[dict]] = defaultdict(list)
    for f in facets:
        by_tool[f["source"]].append(f)

    tools_analyzed = sorted(by_tool.keys())
    sessions_per_tool = {t: len(fs) for t, fs in by_tool.items()}

    tool_metrics = []
    for tool, tool_facets in by_tool.items():
        success_count = sum(
            1 for f in tool_facets
            if f["outcome"] in ("fully_achieved", "partially_achieved")
        )
        success_rate = success_count / len(tool_facets) if tool_facets else 0.0

        avg_friction = sum(f.get("friction_score", 0) for f in tool_facets) / len(tool_facets)

        # Task types
        task_counter: Counter[str] = Counter()
        helpfulness_counter: Counter[str] = Counter()
        complexity_total = 0

        for f in tool_facets:
            task_counter[f["task_type"]] += 1
            helpfulness_counter[f.get("tool_helpfulness", "moderately")] += 1
            complexity_total += f.get("complexity_score", 3)

        top_tasks = [t for t, _ in task_counter.most_common(3)]

        tool_metrics.append({
            "tool": tool,
            "session_count": len(tool_facets),
            "avg_turns": 0.0,  # Would need session data
            "avg_duration_ms": None,
            "avg_friction_score": round(avg_friction, 3),
            "success_rate": round(success_rate, 3),
            "avg_tokens": 0,
            "top_task_types": top_tasks,
            "helpfulness_distribution": dict(helpfulness_counter),
        })

    # Sort by success rate descending
    tool_metrics.sort(key=lambda m: m["success_rate"], reverse=True)

    # Best-for recommendations
    best_for: dict[str, str] = {}
    task_tool_scores: dict[str, dict[str, float]] = defaultdict(dict)

    for f in facets:
        task = f["task_type"]
        tool = f["source"]
        score = 1.0 if f["outcome"] == "fully_achieved" else 0.5 if f["outcome"] == "partially_achieved" else 0.0
        if task not in task_tool_scores[tool]:
            task_tool_scores[tool][task] = 0.0
        task_tool_scores[tool][task] = (task_tool_scores[tool].get(task, 0.0) + score)

    # For each task type, find best tool
    all_tasks: set[str] = set()
    for tool_scores in task_tool_scores.values():
        all_tasks.update(tool_scores.keys())

    for task in all_tasks:
        best_tool = None
        best_score = -1.0
        for tool, scores in task_tool_scores.items():
            if scores.get(task, 0.0) > best_score:
                best_score = scores.get(task, 0.0)
                best_tool = tool
        if best_tool:
            best_for[task] = best_tool

    # Narrative
    if tool_metrics:
        best = tool_metrics[0]
        narrative = f"Most effective tool: {best['tool']} ({best['success_rate']:.0%} success rate, {best['avg_friction_score']:.2f} avg friction)."
        if len(tool_metrics) > 1:
            worst = tool_metrics[-1]
            narrative += f" {worst['tool']} has the highest friction ({worst['avg_friction_score']:.2f})."
    else:
        narrative = "No tool data available."

    return {
        "tools_analyzed": tools_analyzed,
        "sessions_per_tool": sessions_per_tool,
        "tool_metrics": tool_metrics,
        "best_for": best_for,
        "narrative": narrative,
    }


def _cluster_project_areas(facets: list[dict]) -> list[dict]:
    """Group facets by project area."""
    # Use session metadata - group by project area from goal categories
    area_sessions: dict[str, list[dict]] = defaultdict(list)

    for f in facets:
        categories = f.get("goal_categories", {})
        if categories:
            for cat in categories:
                area_sessions[cat].append(f)
        else:
            area_sessions["general"].append(f)

    areas = []
    for name, area_facets in sorted(area_sessions.items(), key=lambda x: -len(x[1])):
        if len(area_facets) < 1:
            continue

        tools = list({f["source"] for f in area_facets})
        success_count = sum(1 for f in area_facets if f["outcome"] in ("fully_achieved", "partially_achieved"))
        avg_friction = sum(f.get("friction_score", 0) for f in area_facets) / len(area_facets)

        areas.append({
            "name": name.replace("_", " ").title(),
            "session_count": len(area_facets),
            "description": f"{len(area_facets)} sessions across {', '.join(tools)}",
            "primary_tools": tools,
            "success_rate": round(success_count / len(area_facets), 3) if area_facets else 0.0,
            "avg_friction": round(avg_friction, 3),
        })

    return areas[:10]  # Top 10 areas


def _aggregate_friction(facets: list[dict]) -> dict:
    """Aggregate friction patterns across all facets."""
    category_counts: Counter[str] = Counter()
    tool_friction: dict[str, list[float]] = defaultdict(list)
    friction_sessions = 0

    for f in facets:
        score = f.get("friction_score", 0.0)
        tool_friction[f["source"]].append(score)

        if score > 0.2:
            friction_sessions += 1

        for cat, count in f.get("friction_counts", {}).items():
            category_counts[cat] += count

    friction_by_tool = {
        tool: round(sum(scores) / len(scores), 3)
        for tool, scores in tool_friction.items()
    }

    # Top patterns
    patterns = []
    for cat, count in category_counts.most_common(5):
        affected = [
            tool for tool, tool_facets in defaultdict(list, {
                f["source"]: f for f in facets
                if cat in f.get("friction_counts", {})
            }).items()
        ]
        patterns.append({
            "category": cat,
            "count": count,
            "description": f"{cat.replace('_', ' ').title()} occurred {count} times",
            "affected_tools": affected,
            "examples": [],
        })

    narrative = ""
    if category_counts:
        top_cat = category_counts.most_common(1)[0]
        narrative = f"Top friction: {top_cat[0].replace('_', ' ')} ({top_cat[1]} occurrences)."

    return {
        "total_friction_sessions": friction_sessions,
        "friction_by_category": dict(category_counts),
        "friction_by_tool": friction_by_tool,
        "top_friction_patterns": patterns,
        "narrative": narrative,
    }


def _analyze_interaction_style(facets: list[dict], stats: dict) -> dict:
    """Analyze interaction patterns."""
    type_counts: Counter[str] = Counter()
    complexity_total = 0

    for f in facets:
        type_counts[f.get("session_type", "unknown")] += 1
        complexity_total += f.get("complexity_score", 3)

    avg_complexity = complexity_total / len(facets) if facets else 3

    most_common_type = type_counts.most_common(1)[0][0] if type_counts else "unknown"

    narrative = f"Your most common session type is {most_common_type.replace('_', ' ')} ({type_counts[most_common_type]} sessions). "
    narrative += f"Average complexity: {avg_complexity:.1f}/5."

    return {
        "narrative": narrative,
        "key_pattern": f"Primarily {most_common_type.replace('_', ' ')} sessions with complexity {avg_complexity:.1f}/5.",
    }


def _find_impressive_workflows(facets: list[dict]) -> list[dict]:
    """Find the most successful workflows."""
    successful = [
        f for f in facets
        if f["outcome"] == "fully_achieved" and f.get("complexity_score", 0) >= 3
    ]

    # Sort by complexity (most impressive first)
    successful.sort(key=lambda f: f.get("complexity_score", 0), reverse=True)

    workflows = []
    for f in successful[:3]:
        workflows.append({
            "title": f.get("underlying_goal", "")[:80],
            "description": f.get("brief_summary", ""),
        })

    return workflows


def _compute_trends(facets: list[dict]) -> dict:
    """Compute usage trends over time."""
    # Group by date (from analyzed_at timestamp)
    daily: Counter[str] = Counter()
    weekly_by_tool: dict[str, list[int]] = defaultdict(lambda: [0] * 4)

    for f in facets:
        ts = f.get("analyzed_at", 0)
        if ts:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            daily[dt.strftime("%Y-%m-%d")] += 1

    # Friction trend: compare first half to second half
    if len(facets) >= 4:
        mid = len(facets) // 2
        first_half_friction = sum(f.get("friction_score", 0) for f in facets[:mid]) / mid
        second_half_friction = sum(f.get("friction_score", 0) for f in facets[mid:]) / (len(facets) - mid)

        if second_half_friction < first_half_friction * 0.8:
            friction_trend = "improving"
        elif second_half_friction > first_half_friction * 1.2:
            friction_trend = "worsening"
        else:
            friction_trend = "stable"
    else:
        friction_trend = "stable"

    # Productivity: success rate trend
    if len(facets) >= 4:
        mid = len(facets) // 2
        first_success = sum(1 for f in facets[:mid] if f["outcome"] in ("fully_achieved", "partially_achieved")) / mid
        second_success = sum(1 for f in facets[mid:] if f["outcome"] in ("fully_achieved", "partially_achieved")) / (len(facets) - mid)

        if second_success > first_success * 1.1:
            productivity_trend = "improving"
        elif second_success < first_success * 0.9:
            productivity_trend = "worsening"
        else:
            productivity_trend = "stable"
    else:
        productivity_trend = "stable"

    return {
        "sessions_per_day": dict(daily),
        "friction_trend": friction_trend,
        "tool_adoption": {},
        "productivity_trend": productivity_trend,
    }


def _generate_suggestions(facets: list[dict], friction: dict, tool_comp: dict) -> dict:
    """Generate actionable suggestions from analysis."""
    suggestions: list[dict] = []
    patterns: list[dict] = []
    recommendations: list[dict] = []

    # AGENTS.md suggestions from friction patterns
    friction_by_cat = friction.get("friction_by_category", {})

    # Detect cross-tool patterns
    tool_friction: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for f in facets:
        for cat, count in f.get("friction_counts", {}).items():
            tool_friction[f["source"]][cat] += count

    for cat, total_count in sorted(friction_by_cat.items(), key=lambda x: -x[1]):
        if total_count < 3:
            continue

        # Which tools have this friction?
        affected_tools = [t for t, cats in tool_friction.items() if cats.get(cat, 0) > 0]

        # Cross-tool pattern → AGENTS.md suggestion
        if len(affected_tools) >= 2:
            suggestions.append({
                "target_file": "AGENTS.md",
                "target_tool": "universal",
                "addition": f"Watch out for {cat.replace('_', ' ')} issues. This pattern was detected across {', '.join(affected_tools)}.",
                "why": f"{total_count} occurrences across {len(affected_tools)} tools",
                "section_hint": "## Known Friction Points",
            })
        else:
            # Tool-specific suggestion
            tool = affected_tools[0] if affected_tools else "unknown"
            target = {
                "claude": "CLAUDE.md",
                "cursor": ".cursorrules",
                "opencode": "AGENTS.md",
                "codex": "codex.md",
            }.get(tool, "AGENTS.md")

            suggestions.append({
                "target_file": target,
                "target_tool": tool,
                "addition": f"Be aware of {cat.replace('_', ' ')} patterns when working with this tool.",
                "why": f"{total_count} occurrences in {tool} sessions",
                "section_hint": "## Workflow Notes",
            })

    # Tool recommendations from best_for
    best_for = tool_comp.get("best_for", {})
    for task_type, tool in best_for.items():
        # Find the metric for this tool
        metrics = tool_comp.get("tool_metrics", [])
        tool_metric = next((m for m in metrics if m["tool"] == tool), None)

        confidence = 0.0
        if tool_metric:
            confidence = min(tool_metric["session_count"] / 20.0, 1.0)

        recommendations.append({
            "task_type": task_type,
            "recommended_tool": tool,
            "reason": f"Best success rate for {task_type} tasks",
            "confidence": round(confidence, 2),
        })

    # Usage patterns
    patterns.append({
        "title": "Profile data quality first",
        "suggestion": "Start sessions by checking data characteristics",
        "detail": "Reduces friction from wrong initial approaches.",
        "copyable_prompt": "Profile this dataset first - check types, missing values, and size before processing.",
    })

    return {
        "agents_md_additions": suggestions,
        "usage_patterns": patterns,
        "tool_recommendations": recommendations,
    }


def _build_at_a_glance(tool_comp: dict, friction: dict, suggestions: dict) -> dict:
    """Build the at-a-glance summary."""
    metrics = tool_comp.get("tool_metrics", [])

    # What's working
    working_parts = []
    if metrics:
        best = metrics[0]
        working_parts.append(f"Best results with {best['tool']} ({best['success_rate']:.0%} success rate).")
    working = " ".join(working_parts) if working_parts else "Gathering data."

    # What's hindering
    hindering_parts = []
    narrative = friction.get("narrative", "")
    if narrative:
        hindering_parts.append(narrative)
    hindering = " ".join(hindering_parts) if hindering_parts else "No major friction detected."

    # Quick wins
    recs = suggestions.get("tool_recommendations", [])
    if recs:
        quick = f"Try using {recs[0]['recommended_tool']} for {recs[0]['task_type']} tasks."
    else:
        quick = "Analyze more sessions for personalized suggestions."

    return {
        "whats_working": working,
        "whats_hindering": hindering,
        "quick_wins": quick,
        "ambitious_workflows": "Run sagg insights regularly to track your productivity trends across tools.",
    }


def _pick_fun_ending(facets: list[dict]) -> dict:
    """Pick a fun/memorable moment from session history."""
    # Find highest friction session for a funny headline
    if not facets:
        return {"headline": "", "detail": ""}

    highest_friction = max(facets, key=lambda f: f.get("friction_score", 0))

    if highest_friction.get("friction_score", 0) > 0.5:
        return {
            "headline": f"Most dramatic session: {highest_friction.get('brief_summary', 'Unknown')[:80]}",
            "detail": highest_friction.get("friction_detail", "") or "It was a struggle.",
        }

    # Alternatively, find most complex successful session
    complex_wins = [f for f in facets if f["outcome"] == "fully_achieved"]
    if complex_wins:
        best = max(complex_wins, key=lambda f: f.get("complexity_score", 0))
        return {
            "headline": f"Most impressive win: {best.get('brief_summary', '')[:80]}",
            "detail": f"Complexity {best.get('complexity_score', 0)}/5, nailed it.",
        }

    return {"headline": "Keep coding!", "detail": "More sessions = better insights."}
