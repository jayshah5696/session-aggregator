"""Friction points detection for session analysis.

This module provides tools to detect sessions with excessive back-and-forth,
retries, errors, and other friction indicators that suggest difficult or
problematic coding sessions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sagg.models import ToolCallPart, ToolResultPart, TextPart

if TYPE_CHECKING:
    from sagg.models import UnifiedSession
    from sagg.storage import SessionStore


class FrictionType(Enum):
    """Types of friction indicators in coding sessions."""

    HIGH_RETRIES = "high_retries"
    ERROR_RATE = "high_errors"
    BACK_AND_FORTH = "back_and_forth"
    LOW_EFFICIENCY = "low_efficiency"


@dataclass
class FrictionPoint:
    """A session identified as having significant friction.

    Attributes:
        session_id: Unique identifier for the session.
        title: Session title or summary.
        friction_types: List of friction indicators detected.
        friction_score: Overall friction score from 0.0 to 1.0.
        details: Dictionary with specific metrics.
        project: Project name associated with the session.
    """

    session_id: str
    title: str
    friction_types: list[FrictionType]
    friction_score: float
    details: dict
    project: str


def analyze_retries(session: UnifiedSession) -> tuple[int, list[str]]:
    """Count sequential retries of the same tool.

    A retry is when the same tool is called multiple times in sequence,
    typically indicating failed attempts that required retrying.

    Args:
        session: Session to analyze.

    Returns:
        Tuple of (total_retry_count, list_of_tools_with_retries).
    """
    if not session.turns:
        return 0, []

    tool_calls = []

    # Extract all tool call names in order
    for turn in session.turns:
        for message in turn.messages:
            for part in message.parts:
                if isinstance(part, ToolCallPart):
                    tool_calls.append(part.tool_name)

    if not tool_calls:
        return 0, []

    # Count sequential retries
    retry_count = 0
    tools_with_retries: set[str] = set()
    current_tool = None
    current_streak = 0

    for tool_name in tool_calls:
        if tool_name == current_tool:
            current_streak += 1
        else:
            if current_streak > 0:
                retry_count += current_streak
                if current_tool:
                    tools_with_retries.add(current_tool)
            current_tool = tool_name
            current_streak = 0

    # Don't forget the last streak
    if current_streak > 0:
        retry_count += current_streak
        if current_tool:
            tools_with_retries.add(current_tool)

    return retry_count, list(tools_with_retries)


def analyze_error_rate(session: UnifiedSession) -> float:
    """Calculate ratio of error results to total tool calls.

    Args:
        session: Session to analyze.

    Returns:
        Error rate from 0.0 to 1.0, or 0.0 if no tool calls.
    """
    if not session.turns:
        return 0.0

    total_results = 0
    error_results = 0

    for turn in session.turns:
        for message in turn.messages:
            for part in message.parts:
                if isinstance(part, ToolResultPart):
                    total_results += 1
                    if part.is_error:
                        error_results += 1

    if total_results == 0:
        return 0.0

    return error_results / total_results


def analyze_back_and_forth(session: UnifiedSession) -> int:
    """Count short user messages that likely indicate corrections.

    Short user messages (< 50 chars) after assistant responses typically
    indicate corrections, clarifications, or "try again" type interactions.

    Args:
        session: Session to analyze.

    Returns:
        Count of short user messages.
    """
    if not session.turns:
        return 0

    short_message_count = 0
    saw_assistant_response = False

    for turn in session.turns:
        for message in turn.messages:
            if message.role == "assistant":
                saw_assistant_response = True
            elif message.role == "user" and saw_assistant_response:
                # Check if this is a short message
                text_content = ""
                for part in message.parts:
                    if isinstance(part, TextPart):
                        text_content += part.content

                if len(text_content.strip()) < 50:
                    short_message_count += 1

    return short_message_count


def calculate_friction_score(
    retry_count: int,
    error_rate: float,
    back_forth_count: int,
) -> float:
    """Calculate a composite friction score.

    Combines multiple friction indicators into a single score from 0.0 to 1.0.

    Args:
        retry_count: Number of sequential tool retries.
        error_rate: Ratio of errors to total tool calls (0.0-1.0).
        back_forth_count: Number of short correction messages.

    Returns:
        Friction score from 0.0 (no friction) to 1.0 (high friction).
    """
    # Weight each factor
    # Retries: 0-10+ retries maps to 0-0.4 score
    retry_score = min(retry_count / 10.0, 1.0) * 0.4

    # Error rate: 0-100% maps to 0-0.35 score
    error_score = error_rate * 0.35

    # Back and forth: 0-10+ messages maps to 0-0.25 score
    back_forth_score = min(back_forth_count / 10.0, 1.0) * 0.25

    total_score = retry_score + error_score + back_forth_score

    # Ensure bounded between 0 and 1
    return min(max(total_score, 0.0), 1.0)


def detect_friction_points(
    store: SessionStore,
    since: datetime | None = None,
    retry_threshold: int = 3,
    error_threshold: float = 0.3,
    back_forth_threshold: int = 5,
    limit: int = 500,
) -> list[FrictionPoint]:
    """Analyze sessions for friction patterns.

    Args:
        store: SessionStore instance to query.
        since: Only analyze sessions created after this datetime.
        retry_threshold: Minimum retries to flag as HIGH_RETRIES.
        error_threshold: Minimum error rate to flag as ERROR_RATE.
        back_forth_threshold: Minimum back-and-forth count to flag.
        limit: Maximum number of sessions to analyze.

    Returns:
        List of FrictionPoint objects sorted by friction score descending.
    """
    # Get sessions from store
    sessions = store.list_sessions(since=since, limit=limit)

    friction_points: list[FrictionPoint] = []

    for session_meta in sessions:
        # Load full content for analysis
        full_session = store.get_session(session_meta.id)
        if full_session is None:
            continue

        # Analyze each friction type
        retries, retry_tools = analyze_retries(full_session)
        error_rate = analyze_error_rate(full_session)
        back_forth = analyze_back_and_forth(full_session)

        # Determine which friction types apply
        friction_types: list[FrictionType] = []
        details: dict = {}

        if retries >= retry_threshold:
            friction_types.append(FrictionType.HIGH_RETRIES)
            details["retry_count"] = retries
            details["retry_tools"] = retry_tools

        if error_rate >= error_threshold:
            friction_types.append(FrictionType.ERROR_RATE)
            details["error_rate"] = round(error_rate, 2)

        if back_forth >= back_forth_threshold:
            friction_types.append(FrictionType.BACK_AND_FORTH)
            details["back_forth_count"] = back_forth

        # Only include sessions with at least one friction indicator
        if friction_types:
            friction_score = calculate_friction_score(
                retry_count=retries,
                error_rate=error_rate,
                back_forth_count=back_forth,
            )

            friction_points.append(
                FrictionPoint(
                    session_id=full_session.id,
                    title=full_session.title or "Untitled",
                    friction_types=friction_types,
                    friction_score=friction_score,
                    details=details,
                    project=full_session.project_name or "Unknown",
                )
            )

    # Sort by friction score descending
    return sorted(friction_points, key=lambda x: x.friction_score, reverse=True)
