"""Oracle semantic search - 'Have I solved this before?'

This module provides semantic search over session history, helping users
find past solutions to similar problems.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagg.storage import SessionStore


@dataclass
class OracleResult:
    """A single result from the oracle search.

    Attributes:
        session_id: The unique identifier of the matching session.
        title: The title of the session.
        relevance_score: Score from 0.0 to 1.0 indicating match quality.
        matched_text: A snippet showing the matching content.
        project: The project name where this session occurred.
        timestamp: When the session was created.
    """

    session_id: str
    title: str
    relevance_score: float
    matched_text: str
    project: str
    timestamp: datetime


def search_history(
    store: SessionStore,
    query: str,
    limit: int = 10,
) -> list[OracleResult]:
    """Search session history for similar problems.

    Uses FTS5 for initial matching, then ranks by:
    - Title match (high weight)
    - Content match (medium weight)
    - Recency (slight boost for recent sessions)

    Args:
        store: The session store to search.
        query: The search query string.
        limit: Maximum number of results to return.

    Returns:
        List of OracleResult objects sorted by relevance.
    """
    # Use the store's ranked search method
    search_results = store.search_sessions_ranked(query, limit=limit * 2)

    if not search_results:
        return []

    results: list[OracleResult] = []

    for session, raw_rank in search_results:
        # FTS5 rank is negative (more negative = better match)
        # Convert to 0-1 scale where 1 is best
        # Typical rank values range from -0.1 to -50 or more
        # We'll normalize assuming -30 is a very good match
        normalized_score = min(1.0, max(0.0, (-raw_rank) / 30.0))

        # Apply recency boost (sessions within last week get up to 10% boost)
        now = datetime.now(timezone.utc)
        if session.created_at.tzinfo is None:
            session_time = session.created_at.replace(tzinfo=timezone.utc)
        else:
            session_time = session.created_at

        age_days = (now - session_time).days
        recency_boost = max(0, 0.1 * (1 - age_days / 7)) if age_days < 7 else 0
        final_score = min(1.0, normalized_score + recency_boost)

        # Get the matched text snippet from session content
        content = session.extract_text_content()
        matched_text = extract_snippet(content, query, context_chars=100)

        # Fall back to title if no content match
        if not matched_text and session.title:
            matched_text = extract_snippet(session.title, query, context_chars=50)

        # If still no match, just show beginning of content
        if not matched_text:
            matched_text = content[:100] + "..." if len(content) > 100 else content

        results.append(
            OracleResult(
                session_id=session.id,
                title=session.title or "Untitled Session",
                relevance_score=round(final_score, 2),
                matched_text=matched_text,
                project=session.project_name or "Unknown",
                timestamp=session.created_at,
            )
        )

    # Sort by relevance score (descending)
    results.sort(key=lambda r: r.relevance_score, reverse=True)

    # Apply limit after sorting
    return results[:limit]


def extract_snippet(content: str, query: str, context_chars: int = 100) -> str:
    """Extract a text snippet around the match.

    Args:
        content: The full text content to search.
        query: The search query to find.
        context_chars: Number of characters to show before and after the match.

    Returns:
        A snippet of text with the match and surrounding context.
    """
    if not content or not query:
        return ""

    # Try case-insensitive search
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    match = pattern.search(content)

    if not match:
        # No match found - return empty string
        return ""

    start_pos = match.start()
    end_pos = match.end()

    # Calculate snippet boundaries
    snippet_start = max(0, start_pos - context_chars)
    snippet_end = min(len(content), end_pos + context_chars)

    # Extract the snippet
    snippet = content[snippet_start:snippet_end]

    # Add ellipsis if truncated
    prefix = "..." if snippet_start > 0 else ""
    suffix = "..." if snippet_end < len(content) else ""

    return f"{prefix}{snippet}{suffix}"


def format_result(result: OracleResult) -> str:
    """Format a result for terminal display.

    Args:
        result: The OracleResult to format.

    Returns:
        A formatted string representation of the result.
    """
    # Calculate time ago
    now = datetime.now(timezone.utc)
    if result.timestamp.tzinfo is None:
        timestamp = result.timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = result.timestamp

    delta = now - timestamp
    seconds = delta.total_seconds()

    if seconds < 3600:
        time_ago = f"{int(seconds / 60)}m ago"
    elif seconds < 86400:
        time_ago = f"{int(seconds / 3600)}h ago"
    elif seconds < 604800:
        time_ago = f"{int(seconds / 86400)} days ago"
    else:
        time_ago = f"{int(seconds / 604800)} weeks ago"

    # Format relevance as percentage
    relevance_pct = int(result.relevance_score * 100)

    # Build the formatted output
    output = f"""Session: {result.title} ({relevance_pct}% match)
Project: {result.project} - {time_ago}

"{result.matched_text}"
"""

    return output


def format_results_rich(
    results: list[OracleResult],
    query: str,
) -> None:
    """Display results using Rich panels.

    Args:
        results: List of OracleResult objects to display.
        query: The original search query.
    """
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    console = Console()

    if not results:
        console.print(f"[dim]No sessions found matching '{query}'[/dim]")
        return

    console.print(f'[bold]Oracle: "{query}"[/bold]')
    console.print(f"Found {len(results)} relevant session(s):\n")

    for result in results:
        # Calculate time ago
        now = datetime.now(timezone.utc)
        if result.timestamp.tzinfo is None:
            timestamp = result.timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = result.timestamp

        delta = now - timestamp
        seconds = delta.total_seconds()

        if seconds < 3600:
            time_ago = f"{int(seconds / 60)}m ago"
        elif seconds < 86400:
            time_ago = f"{int(seconds / 3600)}h ago"
        elif seconds < 604800:
            time_ago = f"{int(seconds / 86400)} days ago"
        else:
            time_ago = f"{int(seconds / 604800)} weeks ago"

        # Format relevance as percentage
        relevance_pct = int(result.relevance_score * 100)

        # Build panel content
        panel_content = Text()
        panel_content.append(f"Project: {result.project}", style="green")
        panel_content.append(" - ", style="dim")
        panel_content.append(time_ago, style="yellow")
        panel_content.append("\n\n")
        panel_content.append(f'"{result.matched_text}"', style="italic")

        # Create panel with title showing relevance
        panel_title = f"Session: {result.title} ({relevance_pct}% match)"

        console.print(
            Panel(
                panel_content,
                title=panel_title,
                border_style="blue",
            )
        )
        console.print()  # Spacing between panels
