"""Git utilities for associating sessions with commits."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path


def is_git_repo(path: Path) -> bool:
    """Check if a path is inside a git repository.

    Args:
        path: Path to check.

    Returns:
        True if the path is inside a git repository.
    """
    if not path.exists():
        return False

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=path,
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def get_repo_info(path: Path) -> dict | None:
    """Get git repository info for a path.

    Args:
        path: Path to the git repository or a directory inside it.

    Returns:
        Dictionary with branch, commit, and remote info, or None if not a git repo.
    """
    if not path.exists():
        return None

    try:
        # Get current branch
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if branch_result.returncode != 0:
            return None

        branch = branch_result.stdout.strip()

        # Get current commit SHA
        commit_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        commit = commit_result.stdout.strip() if commit_result.returncode == 0 else None

        # Get remote URL (optional, may not exist)
        remote_result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        remote = remote_result.stdout.strip() if remote_result.returncode == 0 else None

        return {
            "branch": branch,
            "commit": commit,
            "remote": remote,
        }

    except (subprocess.SubprocessError, OSError):
        return None


def get_commits_in_range(
    repo_path: Path,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Get commits between start and end timestamps.

    Args:
        repo_path: Path to the git repository.
        start: Start datetime (inclusive).
        end: End datetime (inclusive).

    Returns:
        List of commit dictionaries with sha, message, timestamp, and author.
    """
    if not repo_path.exists() or not is_git_repo(repo_path):
        return []

    try:
        # Format dates for git log
        # Git uses ISO 8601 format
        start_str = start.strftime("%Y-%m-%dT%H:%M:%S")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%S")

        # Use git log with date range
        # Format: sha|author|timestamp|message
        result = subprocess.run(
            [
                "git",
                "log",
                f"--after={start_str}",
                f"--before={end_str}",
                "--format=%H|%an|%aI|%s",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return []

        commits = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            parts = line.split("|", 3)
            if len(parts) >= 4:
                sha, author, timestamp_str, message = parts
                try:
                    # Parse ISO timestamp
                    timestamp = datetime.fromisoformat(timestamp_str)
                except ValueError:
                    timestamp = None

                commits.append(
                    {
                        "sha": sha,
                        "author": author,
                        "timestamp": timestamp,
                        "message": message,
                    }
                )

        return commits

    except (subprocess.SubprocessError, OSError):
        return []


def find_closest_commit(
    repo_path: Path,
    timestamp: datetime,
    window_hours: int = 2,
) -> dict | None:
    """Find the commit closest to the given timestamp.

    Looks for commits within +/- window_hours of the timestamp and returns
    the one with the smallest time difference.

    Args:
        repo_path: Path to the git repository.
        timestamp: Target timestamp to find commits near.
        window_hours: Hours before and after to search (default: 2).

    Returns:
        Commit dictionary with sha, message, timestamp, author, or None if not found.
    """
    if not repo_path.exists() or not is_git_repo(repo_path):
        return None

    # Ensure timestamp is timezone-aware
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    # Define search window
    window = timedelta(hours=window_hours)
    start = timestamp - window
    end = timestamp + window

    commits = get_commits_in_range(repo_path, start, end)

    if not commits:
        return None

    # Find the commit with the smallest time difference
    closest_commit = None
    smallest_diff = None

    for commit in commits:
        if commit["timestamp"] is None:
            continue

        commit_ts = commit["timestamp"]
        # Ensure timezone-aware comparison
        if commit_ts.tzinfo is None:
            commit_ts = commit_ts.replace(tzinfo=timezone.utc)

        diff = abs((commit_ts - timestamp).total_seconds())

        if smallest_diff is None or diff < smallest_diff:
            smallest_diff = diff
            closest_commit = commit

    return closest_commit


def link_session_to_commit(
    project_path: str | Path | None,
    session_timestamp: datetime,
    window_hours: int = 2,
) -> dict | None:
    """Find the closest commit for a session based on its timestamp.

    This is a convenience function that wraps find_closest_commit with
    proper path handling.

    Args:
        project_path: Path to the project (git repository).
        session_timestamp: The session's updated_at or created_at timestamp.
        window_hours: Hours before and after to search.

    Returns:
        Commit dictionary or None if no matching commit found.
    """
    if project_path is None:
        return None

    path = Path(project_path) if isinstance(project_path, str) else project_path

    if not path.exists():
        return None

    return find_closest_commit(path, session_timestamp, window_hours)
