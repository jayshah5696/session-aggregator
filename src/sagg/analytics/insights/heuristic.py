"""Heuristic-based session facet extraction.

Extracts structured facets from sessions using pattern matching,
tool usage analysis, and existing friction analytics. No LLM required.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import TYPE_CHECKING

from sagg.analytics.friction import (
    analyze_back_and_forth,
    analyze_error_rate,
    analyze_retries,
    calculate_friction_score,
)
from sagg.models import TextPart, ToolCallPart, ToolResultPart

if TYPE_CHECKING:
    from sagg.models import UnifiedSession


# File extension to language mapping
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".md": "markdown",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".toml": "toml",
}


def analyze_session(session: UnifiedSession) -> dict:
    """Extract a facet from a session using heuristic analysis.

    Args:
        session: The session to analyze.

    Returns:
        Dictionary matching the session_facets schema.
    """
    goal = _extract_goal(session)
    task_type = _classify_task_type(session)
    outcome = _assess_outcome(session)
    session_type = _classify_session_type(session)
    complexity = _assess_complexity(session)
    language = _detect_primary_language(session)
    files_pattern = _detect_files_pattern(session)
    summary = _generate_summary(session)

    # Friction analysis (reuse existing module)
    retries, retry_tools = analyze_retries(session)
    error_rate = analyze_error_rate(session)
    back_forth = analyze_back_and_forth(session)
    friction_score = calculate_friction_score(retries, error_rate, back_forth)

    friction_counts: dict[str, int] = {}
    if retries >= 3:
        friction_counts["wrong_approach"] = retries
    if error_rate >= 0.3:
        friction_counts["tool_error"] = int(error_rate * 100)
    if back_forth >= 5:
        friction_counts["user_rejected_action"] = back_forth

    friction_detail = None
    if friction_counts:
        parts = []
        if "wrong_approach" in friction_counts:
            parts.append(f"{retries} sequential retries on {', '.join(retry_tools[:3])}")
        if "tool_error" in friction_counts:
            parts.append(f"{int(error_rate * 100)}% error rate")
        if "user_rejected_action" in friction_counts:
            parts.append(f"{back_forth} short corrections")
        friction_detail = "; ".join(parts)

    # Tool effectiveness
    tool_counts = session.get_tool_counts()
    tools_helped = [t for t, c in sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:3]]
    tools_didnt = list(retry_tools[:3]) if retry_tools else []

    # Helpfulness heuristic
    if friction_score < 0.2:
        helpfulness = "very"
    elif friction_score < 0.4:
        helpfulness = "moderately"
    elif friction_score < 0.6:
        helpfulness = "slightly"
    else:
        helpfulness = "unhelpful"

    return {
        "session_id": session.id,
        "source": session.source.value,
        "analyzed_at": int(time.time()),
        "analyzer_version": "heuristic_v1",
        "analyzer_model": None,
        "underlying_goal": goal,
        "goal_categories": _extract_goal_categories(session),
        "task_type": task_type,
        "outcome": outcome,
        "completion_confidence": _outcome_confidence(session, outcome),
        "session_type": session_type,
        "complexity_score": complexity,
        "friction_counts": friction_counts,
        "friction_detail": friction_detail,
        "friction_score": round(friction_score, 3),
        "tools_that_helped": tools_helped,
        "tools_that_didnt": tools_didnt,
        "tool_helpfulness": helpfulness,
        "primary_language": language,
        "files_pattern": files_pattern,
        "brief_summary": summary,
        "key_decisions": [],
    }


def _extract_goal(session: UnifiedSession) -> str:
    """Extract the user's goal from the first user message."""
    for turn in session.turns:
        for message in turn.messages:
            if message.role == "user":
                for part in message.parts:
                    if isinstance(part, TextPart) and part.content.strip():
                        text = part.content.strip()
                        # Truncate to first 200 chars
                        if len(text) > 200:
                            return text[:200] + "..."
                        return text
    return session.title or "Unknown goal"


def _extract_goal_categories(session: UnifiedSession) -> dict[str, int]:
    """Classify goals from user messages and tool patterns."""
    categories: dict[str, int] = {}

    # Check first user message for keywords
    goal_text = _extract_goal(session).lower()

    keyword_map = {
        "bugfix": ["fix", "bug", "error", "broken", "crash", "fail", "issue"],
        "feature": ["add", "create", "implement", "build", "new"],
        "refactor": ["refactor", "clean", "reorganize", "restructure", "rename"],
        "docs": ["document", "readme", "docs", "comment", "spec"],
        "debug": ["debug", "investigate", "why", "trace", "log"],
        "config": ["config", "setup", "install", "deploy", "ci", "yaml"],
        "testing": ["test", "coverage", "assert", "mock", "spec"],
    }

    for category, keywords in keyword_map.items():
        for keyword in keywords:
            if keyword in goal_text:
                categories[category] = 1
                break

    if not categories:
        categories["general"] = 1

    return categories


def _classify_task_type(session: UnifiedSession) -> str:
    """Classify the primary task type from tool usage and content."""
    tool_counts = session.get_tool_counts()
    goal = _extract_goal(session).lower()

    # Check goal text first (debug before bugfix since "bug" is substring of "debug")
    if any(w in goal for w in ["debug", "investigate"]):
        return "debug"
    if any(w in goal for w in ["fix", "bug", "error", "broken"]):
        return "bugfix"
    if any(w in goal for w in ["refactor", "clean", "reorganize"]):
        return "refactor"
    if any(w in goal for w in ["doc", "readme", "spec", "comment"]):
        return "docs"
    if any(w in goal for w in ["config", "setup", "install", "deploy"]):
        return "config"
    if any(w in goal for w in ["test", "coverage"]):
        return "feature"

    # Infer from tool usage
    read_heavy = tool_counts.get("Read", 0) + tool_counts.get("Grep", 0) + tool_counts.get("Glob", 0)
    write_heavy = tool_counts.get("Edit", 0) + tool_counts.get("Write", 0)

    if read_heavy > write_heavy * 2:
        return "exploration"
    if write_heavy > 0:
        return "feature"

    return "exploration"


def _assess_outcome(session: UnifiedSession) -> str:
    """Assess session outcome from how it ended."""
    if not session.turns:
        return "unclear"

    turn_count = len(session.turns)

    if turn_count <= 1:
        return "abandoned"

    # Check if last message was from assistant (natural ending)
    last_turn = session.turns[-1]
    if last_turn.messages:
        last_msg = last_turn.messages[-1]
        if last_msg.role == "assistant":
            # Check friction
            retries, _ = analyze_retries(session)
            error_rate = analyze_error_rate(session)

            if error_rate < 0.2 and retries < 5:
                return "fully_achieved"
            elif error_rate < 0.4:
                return "partially_achieved"
            else:
                return "partially_achieved"

    return "unclear"


def _outcome_confidence(session: UnifiedSession, outcome: str) -> float:
    """Estimate confidence in the outcome assessment."""
    if outcome == "unclear":
        return 0.3
    if outcome == "abandoned":
        return 0.7

    turn_count = len(session.turns)
    # More turns = more data = higher confidence
    base = 0.5
    turn_bonus = min(turn_count / 20.0, 0.3)
    return round(base + turn_bonus, 2)


def _classify_session_type(session: UnifiedSession) -> str:
    """Classify the session type by turn count and pattern."""
    turn_count = len(session.turns)

    if turn_count <= 2:
        return "quick_question"
    elif turn_count <= 5:
        return "single_task"
    elif turn_count <= 15:
        return "multi_task"
    else:
        return "iterative_refinement"


def _assess_complexity(session: UnifiedSession) -> int:
    """Assess session complexity on a 1-5 scale."""
    turn_count = len(session.turns)
    tool_count = session.stats.tool_call_count
    file_count = len(session.stats.files_modified)

    score = 1

    if turn_count > 5:
        score += 1
    if turn_count > 15:
        score += 1
    if tool_count > 20:
        score += 1
    if file_count > 5:
        score += 1

    return min(score, 5)


def _detect_primary_language(session: UnifiedSession) -> str | None:
    """Detect the dominant language from modified files."""
    if not session.stats.files_modified:
        return None

    lang_counts: Counter[str] = Counter()
    for filepath in session.stats.files_modified:
        # Get extension
        dot_idx = filepath.rfind(".")
        if dot_idx >= 0:
            ext = filepath[dot_idx:].lower()
            lang = EXTENSION_TO_LANGUAGE.get(ext)
            if lang:
                lang_counts[lang] += 1

    if not lang_counts:
        return None

    return lang_counts.most_common(1)[0][0]


def _detect_files_pattern(session: UnifiedSession) -> str | None:
    """Detect the file pattern category."""
    language = _detect_primary_language(session)
    files = session.stats.files_modified

    if not files:
        return None

    has_test = any("test" in f.lower() for f in files)
    has_config = any(f.endswith((".yml", ".yaml", ".toml", ".json", ".env")) for f in files)
    has_docs = any(f.endswith((".md", ".rst", ".txt")) for f in files)

    if has_docs and not has_test and not has_config:
        return "docs"
    if has_config and len(files) <= 3:
        return "config"
    if has_test:
        return f"{language}_testing" if language else "testing"
    if language:
        return f"{language}_backend" if language in ("python", "go", "rust", "java") else f"{language}_frontend"

    return None


def _generate_summary(session: UnifiedSession) -> str:
    """Generate a brief summary of the session."""
    goal = _extract_goal(session)
    turn_count = len(session.turns)
    tool_count = session.stats.tool_call_count
    file_count = len(session.stats.files_modified)

    parts = []
    if session.title and session.title != goal:
        parts.append(session.title)
    else:
        # Truncate goal for summary
        short_goal = goal[:100] + "..." if len(goal) > 100 else goal
        parts.append(short_goal)

    stats_parts = []
    if turn_count > 0:
        stats_parts.append(f"{turn_count} turns")
    if file_count > 0:
        stats_parts.append(f"{file_count} files")
    if tool_count > 0:
        stats_parts.append(f"{tool_count} tool calls")

    if stats_parts:
        parts.append(f"({', '.join(stats_parts)})")

    return " ".join(parts)
