"""Session tree widget for navigating sessions by project and date."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rich.text import Text
from textual.message import Message as TextualMessage
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

if TYPE_CHECKING:
    from sagg.models import UnifiedSession


def format_tokens(tokens: int) -> str:
    """Format token count for display."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    elif tokens >= 1_000:
        return f"{tokens / 1_000:.1f}k"
    return str(tokens)


def get_date_bucket(dt: datetime) -> str:
    """Categorize a datetime into a date bucket."""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    delta = now - dt
    days = delta.days

    if days == 0:
        return "Today"
    elif days == 1:
        return "Yesterday"
    elif days < 7:
        return "This Week"
    elif days < 30:
        return "This Month"
    else:
        return "Older"


class SessionTree(Tree[str]):
    """Tree widget for navigating sessions grouped by project and date.

    Sessions are organized hierarchically:
    - Project name
      - Date bucket (Today, Yesterday, This Week, etc.)
        - Individual sessions

    Supports lazy loading for performance with large session counts.
    """

    class SessionSelected(TextualMessage):
        """Emitted when a session is selected."""

        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    class SessionHighlighted(TextualMessage):
        """Emitted when a session node is highlighted (cursor moved)."""

        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    def __init__(
        self,
        label: str = "Sessions",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(label, id=id, classes=classes)
        # Hide the root node - we only want to show project nodes
        self.show_root = False
        self._sessions: list[UnifiedSession] = []
        self._visible_session_ids: set[str] = set()
        self._session_nodes: dict[str, TreeNode[str]] = {}
        self._project_nodes: dict[str, TreeNode[str]] = {}
        self._date_nodes: dict[str, dict[str, TreeNode[str]]] = defaultdict(dict)

    def load_sessions(self, sessions: list[UnifiedSession]) -> None:
        """Load sessions into the tree, grouped by project and date.

        Args:
            sessions: List of sessions to display.
        """
        self._sessions = sessions
        self._session_nodes.clear()
        self._project_nodes.clear()
        self._date_nodes.clear()

        # Clear existing tree
        self.clear()

        # Group sessions by project, then by date
        grouped: dict[str, dict[str, list[UnifiedSession]]] = defaultdict(lambda: defaultdict(list))
        project_stats: dict[str, int] = defaultdict(int)

        for session in sessions:
            project = session.project_name or "Unknown"
            date_bucket = get_date_bucket(session.created_at)
            grouped[project][date_bucket].append(session)
            total = session.stats.input_tokens + session.stats.output_tokens
            project_stats[project] += total

        # Sort projects by token usage (descending)
        sorted_projects = sorted(
            grouped.keys(),
            key=lambda p: project_stats[p],
            reverse=True,
        )

        # Date bucket ordering
        date_order = ["Today", "Yesterday", "This Week", "This Month", "Older"]

        for project in sorted_projects:
            # Create project node with token stats
            tokens = project_stats[project]
            project_label = Text()
            project_label.append(" ", style="bold")
            project_label.append(project, style="bold")
            project_label.append(f"  {format_tokens(tokens)}", style="dim")

            project_node = self.root.add(project_label, data=f"project:{project}")
            self._project_nodes[project] = project_node

            # Add date buckets in order
            for date_bucket in date_order:
                if date_bucket not in grouped[project]:
                    continue

                sessions_in_bucket = grouped[project][date_bucket]
                # Sort by created_at descending
                sessions_in_bucket.sort(key=lambda s: s.created_at, reverse=True)

                date_label = Text()
                date_label.append(date_bucket, style="italic")
                date_label.append(f" ({len(sessions_in_bucket)})", style="dim")

                date_node = project_node.add(date_label, data=f"date:{project}:{date_bucket}")
                self._date_nodes[project][date_bucket] = date_node

                # Add session nodes
                for session in sessions_in_bucket:
                    self._add_session_node(date_node, session)

        # Auto-expand: Expand first 3 projects and their first date buckets
        for i, project in enumerate(sorted_projects[:3]):
            if project in self._project_nodes:
                self._project_nodes[project].expand()
                # Expand first date bucket in each project
                if self._date_nodes[project]:
                    first_date = next(iter(self._date_nodes[project].values()))
                    first_date.expand()

        # Select the first session if available
        if self._sessions:
            first_session = self._sessions[0]
            if first_session.id in self._session_nodes:
                self.select_node(self._session_nodes[first_session.id])

    def _add_session_node(self, parent: TreeNode[str], session: UnifiedSession) -> TreeNode[str]:
        """Add a session node to the tree.

        Args:
            parent: Parent node (date bucket).
            session: Session to add.

        Returns:
            The created tree node.
        """
        # Build session label
        label = Text()

        # Session title or truncated ID
        title = session.title or session.id[:12]
        if len(title) > 24:
            title = title[:21] + "..."
        label.append(title)

        # Token count
        total_tokens = session.stats.input_tokens + session.stats.output_tokens
        label.append(f"  {format_tokens(total_tokens)}", style="dim cyan")

        # Source indicator
        source_colors = {
            "opencode": "green",
            "claude": "yellow",
            "codex": "blue",
            "cursor": "magenta",
        }
        source_color = source_colors.get(session.source.value, "white")
        label.append(f"  {session.source.value[:3]}", style=f"dim {source_color}")

        node = parent.add(label, data=f"session:{session.id}")
        self._session_nodes[session.id] = node
        return node

    def on_tree_node_selected(self, event: Tree.NodeSelected[str]) -> None:
        """Handle node selection."""
        if event.node.data and event.node.data.startswith("session:"):
            session_id = event.node.data.replace("session:", "")
            self.post_message(self.SessionSelected(session_id))

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[str]) -> None:
        """Handle node highlight (cursor movement)."""
        if event.node.data and event.node.data.startswith("session:"):
            session_id = event.node.data.replace("session:", "")
            self.post_message(self.SessionHighlighted(session_id))

    def select_session(self, session_id: str) -> None:
        """Programmatically select a session.

        Args:
            session_id: ID of the session to select.
        """
        if session_id in self._session_nodes:
            node = self._session_nodes[session_id]
            # Expand parent nodes
            parent = node.parent
            while parent is not None:
                parent.expand()
                parent = parent.parent
            self.select_node(node)

    def filter_sessions(self, query: str) -> None:
        """Filter visible sessions by query.

        Args:
            query: Filter query (matches title, project, or ID).
        """
        query = query.lower().strip()

        if not query:
            # Clear filter - show all
            self._visible_session_ids = set()
            for project_node in self._project_nodes.values():
                project_node.allow_expand = True
            for date_dict in self._date_nodes.values():
                for date_node in date_dict.values():
                    date_node.allow_expand = True
            return

        # Filter logic - find matching sessions
        self._visible_session_ids = set()
        for session in self._sessions:
            title = (session.title or "").lower()
            project = (session.project_name or "").lower()
            if query in title or query in project or query in session.id.lower():
                self._visible_session_ids.add(session.id)

        # Update visibility by expanding/collapsing
        for session_id, node in self._session_nodes.items():
            if session_id in self._visible_session_ids:
                # Expand parents to show matching session
                parent = node.parent
                while parent is not None:
                    parent.expand()
                    parent = parent.parent

    @property
    def session_count(self) -> int:
        """Return the number of loaded sessions."""
        return len(self._sessions)

    @property
    def visible_count(self) -> int:
        """Return the number of visible (matching filter) sessions."""
        if self._visible_session_ids:
            return len(self._visible_session_ids)
        return len(self._sessions)

    @property
    def total_tokens(self) -> int:
        """Return total tokens across all sessions."""
        return sum(s.stats.input_tokens + s.stats.output_tokens for s in self._sessions)
