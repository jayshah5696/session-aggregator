"""Heatmap generation for session activity visualization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagg.storage import SessionStore


# Block characters for intensity levels (0-4)
INTENSITY_CHARS = [" ", "░", "▒", "▓", "█"]

# Day labels for the heatmap
DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def get_activity_by_day(
    store: SessionStore, weeks: int = 12, metric: str = "sessions"
) -> dict[str, int]:
    """Get daily activity counts from the session store.

    Args:
        store: SessionStore instance to query.
        weeks: Number of weeks to look back.
        metric: 'sessions' for session count, 'tokens' for token usage.

    Returns:
        Dictionary mapping date strings (YYYY-MM-DD) to counts.
    """
    since = datetime.now(timezone.utc) - timedelta(weeks=weeks)
    data = store.get_sessions_by_day(since)

    result: dict[str, int] = {}
    for day, stats in data.items():
        if metric == "tokens":
            result[day] = stats.get("tokens", 0) or 0
        else:
            result[day] = stats.get("count", 0) or 0

    return result


def calculate_intensity(value: int, max_value: int) -> int:
    """Calculate intensity level (0-4) based on value and max.

    Uses quartile-based distribution:
    - 0: No activity
    - 1: 1-25% of max
    - 2: 26-50% of max
    - 3: 51-75% of max
    - 4: 76-100% of max

    Args:
        value: The value to calculate intensity for.
        max_value: The maximum value in the dataset.

    Returns:
        Intensity level from 0 to 4.
    """
    if value == 0:
        return 0
    if max_value == 0:
        return 4  # Any positive value when max is 0

    ratio = value / max_value
    if ratio <= 0.25:
        return 1
    elif ratio <= 0.50:
        return 2
    elif ratio <= 0.75:
        return 3
    else:
        return 4


def generate_heatmap_data(activity: dict[str, int], weeks: int) -> list[list[int]]:
    """Generate 7xN grid of activity levels (0-4 intensity).

    Args:
        activity: Dictionary mapping date strings (YYYY-MM-DD) to counts.
        weeks: Number of weeks to include.

    Returns:
        List of 7 rows (Sun-Sat) x N weeks columns, each cell is 0-4 intensity.
    """
    # Initialize grid: 7 rows (days) x weeks columns
    grid: list[list[int]] = [[0] * weeks for _ in range(7)]

    if not activity:
        return grid

    # Calculate the date range
    today = datetime.now(timezone.utc).date()
    # Find the most recent Sunday to align the grid
    days_since_sunday = today.weekday() + 1  # Monday=0, Sunday=6 -> we want Sunday=0
    if days_since_sunday == 7:
        days_since_sunday = 0
    end_date = today  # Current day

    # Start date is (weeks) weeks ago, adjusted to start on Sunday
    start_date = today - timedelta(days=(weeks * 7) - 1)
    # Adjust start to the Sunday of that week
    days_from_sunday = (start_date.weekday() + 1) % 7
    start_date = start_date - timedelta(days=days_from_sunday)

    # Find max value for intensity calculation
    max_value = max(activity.values()) if activity else 0

    # Fill in the grid
    current_date = start_date
    for week_idx in range(weeks):
        for day_idx in range(7):
            date_str = current_date.strftime("%Y-%m-%d")
            if date_str in activity:
                value = activity[date_str]
                grid[day_idx][week_idx] = calculate_intensity(value, max_value)
            current_date += timedelta(days=1)

    return grid


def render_heatmap(data: list[list[int]], legend: bool = True) -> str:
    """Render heatmap as terminal string using block characters.

    Args:
        data: 7xN grid of intensity levels (0-4).
        legend: Whether to include a legend at the bottom.

    Returns:
        Rendered heatmap string.
    """
    lines: list[str] = []

    # Calculate the width for alignment
    label_width = 5  # "  Sun " etc.

    # Render each row (day)
    for day_idx, row in enumerate(data):
        day_label = f"  {DAY_LABELS[day_idx]} "
        cells = "".join(INTENSITY_CHARS[intensity] for intensity in row)
        lines.append(f"{day_label}{cells}")

    # Add legend if requested
    if legend:
        lines.append("")
        legend_chars = " ".join(INTENSITY_CHARS[1:])  # Skip the space for 0
        lines.append(f"  Less {legend_chars} More")

    return "\n".join(lines)


def get_month_labels(weeks: int) -> list[tuple[int, str]]:
    """Get month labels with their positions for the heatmap header.

    Args:
        weeks: Number of weeks in the heatmap.

    Returns:
        List of (week_position, month_name) tuples.
    """
    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=(weeks * 7) - 1)
    # Adjust start to the Sunday of that week
    days_from_sunday = (start_date.weekday() + 1) % 7
    start_date = start_date - timedelta(days=days_from_sunday)

    labels: list[tuple[int, str]] = []
    current_month = None

    for week_idx in range(weeks):
        week_start = start_date + timedelta(weeks=week_idx)
        month_name = week_start.strftime("%b")
        if month_name != current_month:
            labels.append((week_idx, month_name))
            current_month = month_name

    return labels
