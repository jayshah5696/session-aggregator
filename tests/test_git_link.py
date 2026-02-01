"""Tests for git-link command and git utilities."""

import subprocess
import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from sagg.models import (
    UnifiedSession,
    Turn,
    Message,
    TextPart,
    SessionStats,
    SourceTool,
    GitContext,
    generate_session_id,
    TokenUsage,
)
from sagg.git_utils import (
    get_commits_in_range,
    find_closest_commit,
    get_repo_info,
    is_git_repo,
)


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository with some commits."""
    temp_dir = tempfile.mkdtemp()
    repo_path = Path(temp_dir)

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Create initial commit
    (repo_path / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    yield repo_path

    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def temp_git_repo_with_commits(temp_git_repo):
    """Create a git repo with multiple commits at known times."""
    repo_path = temp_git_repo

    # Add more commits with specific dates
    commits = []

    # Commit 1: Add auth module
    (repo_path / "auth.py").write_text("# Auth module")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    env = {"GIT_AUTHOR_DATE": "2024-01-15T10:00:00", "GIT_COMMITTER_DATE": "2024-01-15T10:00:00"}
    result = subprocess.run(
        ["git", "commit", "-m", "Add auth module"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        env={**subprocess.os.environ, **env},
    )

    # Commit 2: Fix auth bug
    (repo_path / "auth.py").write_text("# Auth module\n# Bug fix")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    env = {"GIT_AUTHOR_DATE": "2024-01-15T14:30:00", "GIT_COMMITTER_DATE": "2024-01-15T14:30:00"}
    subprocess.run(
        ["git", "commit", "-m", "Fix auth bug"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        env={**subprocess.os.environ, **env},
    )

    # Commit 3: Add user profile
    (repo_path / "profile.py").write_text("# User profile")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    env = {"GIT_AUTHOR_DATE": "2024-01-16T09:00:00", "GIT_COMMITTER_DATE": "2024-01-16T09:00:00"}
    subprocess.run(
        ["git", "commit", "-m", "Add user profile"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        env={**subprocess.os.environ, **env},
    )

    return repo_path


@pytest.fixture
def temp_non_git_dir():
    """Create a temporary directory that is NOT a git repo."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


class TestIsGitRepo:
    """Tests for is_git_repo function."""

    def test_is_git_repo_true(self, temp_git_repo):
        """Test that a git repo is correctly identified."""
        assert is_git_repo(temp_git_repo) is True

    def test_is_git_repo_false(self, temp_non_git_dir):
        """Test that a non-git directory returns False."""
        assert is_git_repo(temp_non_git_dir) is False

    def test_is_git_repo_nonexistent_path(self):
        """Test that a non-existent path returns False."""
        assert is_git_repo(Path("/nonexistent/path/xyz123")) is False


class TestGetRepoInfo:
    """Tests for get_repo_info function."""

    def test_get_repo_info_valid_repo(self, temp_git_repo):
        """Test getting repo info from a valid git repo."""
        info = get_repo_info(temp_git_repo)

        assert info is not None
        assert "branch" in info
        assert "commit" in info
        # Initial branch might be 'main' or 'master' depending on git config
        assert info["branch"] in ("main", "master")
        assert len(info["commit"]) == 40  # Full SHA

    def test_get_repo_info_non_git_dir(self, temp_non_git_dir):
        """Test that non-git directory returns None."""
        info = get_repo_info(temp_non_git_dir)
        assert info is None

    def test_get_repo_info_nonexistent_path(self):
        """Test that non-existent path returns None."""
        info = get_repo_info(Path("/nonexistent/path"))
        assert info is None


class TestGetCommitsInRange:
    """Tests for get_commits_in_range function."""

    def test_get_commits_in_range_finds_commits(self, temp_git_repo_with_commits):
        """Test finding commits within a time range."""
        repo_path = temp_git_repo_with_commits

        # Search for commits on Jan 15, 2024
        start = datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2024, 1, 15, 23, 59, 59, tzinfo=timezone.utc)

        commits = get_commits_in_range(repo_path, start, end)

        assert len(commits) == 2
        messages = [c["message"] for c in commits]
        assert "Add auth module" in messages
        assert "Fix auth bug" in messages

    def test_get_commits_in_range_no_commits(self, temp_git_repo_with_commits):
        """Test when no commits are in range."""
        repo_path = temp_git_repo_with_commits

        # Search for commits in a range with no commits
        start = datetime(2024, 1, 20, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2024, 1, 20, 23, 59, 59, tzinfo=timezone.utc)

        commits = get_commits_in_range(repo_path, start, end)

        assert len(commits) == 0

    def test_get_commits_in_range_non_git_dir(self, temp_non_git_dir):
        """Test that non-git directory returns empty list."""
        start = datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2024, 1, 15, 23, 59, 59, tzinfo=timezone.utc)

        commits = get_commits_in_range(temp_non_git_dir, start, end)

        assert commits == []


class TestFindClosestCommit:
    """Tests for find_closest_commit function."""

    def test_find_closest_commit_exact_match(self, temp_git_repo_with_commits):
        """Test finding commit at exact timestamp."""
        repo_path = temp_git_repo_with_commits

        # Session timestamp matches auth bug fix time
        timestamp = datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc)

        commit = find_closest_commit(repo_path, timestamp)

        assert commit is not None
        assert "Fix auth bug" in commit["message"]

    def test_find_closest_commit_within_window(self, temp_git_repo_with_commits):
        """Test finding closest commit when session is within the window."""
        repo_path = temp_git_repo_with_commits

        # Session timestamp is 15 minutes after auth bug fix
        timestamp = datetime(2024, 1, 15, 14, 45, 0, tzinfo=timezone.utc)

        commit = find_closest_commit(repo_path, timestamp)

        assert commit is not None
        assert "Fix auth bug" in commit["message"]

    def test_find_closest_commit_no_match(self, temp_git_repo_with_commits):
        """Test when no commit is within the search window."""
        repo_path = temp_git_repo_with_commits

        # Session timestamp is far from any commit
        timestamp = datetime(2024, 2, 1, 12, 0, 0, tzinfo=timezone.utc)

        commit = find_closest_commit(repo_path, timestamp)

        assert commit is None

    def test_find_closest_commit_picks_nearest(self, temp_git_repo_with_commits):
        """Test that the nearest commit is picked when multiple are in range."""
        repo_path = temp_git_repo_with_commits

        # Timestamp between auth module (10:00) and auth bug fix (14:30)
        # Closer to auth module
        timestamp = datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc)

        commit = find_closest_commit(repo_path, timestamp)

        assert commit is not None
        assert "Add auth module" in commit["message"]

    def test_find_closest_commit_non_git_dir(self, temp_non_git_dir):
        """Test that non-git directory returns None."""
        timestamp = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        commit = find_closest_commit(temp_non_git_dir, timestamp)

        assert commit is None


class TestGitLinkIntegration:
    """Integration tests for the git-link functionality."""

    def test_link_session_to_commit(self, temp_git_repo_with_commits, session_store):
        """Test linking a session to the closest commit."""
        repo_path = temp_git_repo_with_commits

        # Create a session with timestamp close to a commit
        session = UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.OPENCODE,
            source_id="test-session-git-1",
            source_path="/tmp/test/session.json",
            title="Fix auth bug",
            project_name="test-project",
            project_path=str(repo_path),
            created_at=datetime(2024, 1, 15, 14, 35, 0, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 15, 14, 35, 0, tzinfo=timezone.utc),
            stats=SessionStats(turn_count=1, message_count=2),
            turns=[
                Turn(
                    id="turn-1",
                    index=0,
                    started_at=datetime(2024, 1, 15, 14, 35, 0, tzinfo=timezone.utc),
                    messages=[
                        Message(
                            id="msg-1",
                            role="user",
                            timestamp=datetime(2024, 1, 15, 14, 35, 0, tzinfo=timezone.utc),
                            parts=[TextPart(content="Fix the auth bug")],
                        ),
                    ],
                )
            ],
        )

        session_store.save_session(session)

        # Find the closest commit
        commit = find_closest_commit(repo_path, session.updated_at)

        assert commit is not None
        assert "Fix auth bug" in commit["message"]

    def test_multiple_sessions_to_commits(self, temp_git_repo_with_commits, session_store):
        """Test associating multiple sessions with their respective commits."""
        repo_path = temp_git_repo_with_commits

        # Create sessions at different times
        sessions_data = [
            ("Session for auth module", datetime(2024, 1, 15, 10, 5, 0, tzinfo=timezone.utc)),
            ("Session for auth bug", datetime(2024, 1, 15, 14, 35, 0, tzinfo=timezone.utc)),
            ("Session for profile", datetime(2024, 1, 16, 9, 10, 0, tzinfo=timezone.utc)),
        ]

        expected_commits = ["Add auth module", "Fix auth bug", "Add user profile"]

        for i, (title, timestamp) in enumerate(sessions_data):
            session = UnifiedSession(
                id=generate_session_id(),
                source=SourceTool.OPENCODE,
                source_id=f"test-session-multi-{i}",
                source_path="/tmp/test/session.json",
                title=title,
                project_name="test-project",
                project_path=str(repo_path),
                created_at=timestamp,
                updated_at=timestamp,
                stats=SessionStats(turn_count=1, message_count=1),
                turns=[],
            )
            session_store.save_session(session)

            commit = find_closest_commit(repo_path, session.updated_at)

            assert commit is not None, f"Expected commit for session '{title}'"
            assert expected_commits[i] in commit["message"]

    def test_session_without_project_path(self, session_store):
        """Test handling session without a project path."""
        session = UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.OPENCODE,
            source_id="test-session-no-path",
            source_path="/tmp/test/session.json",
            title="Session without project",
            project_name=None,
            project_path=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            stats=SessionStats(turn_count=1, message_count=1),
            turns=[],
        )

        session_store.save_session(session)

        # Should gracefully handle None project_path
        result = find_closest_commit(Path("/nonexistent"), session.updated_at)
        assert result is None
