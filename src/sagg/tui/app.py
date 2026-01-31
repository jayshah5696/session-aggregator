"""Main Textual application for session-aggregator TUI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Static

from sagg.tui.widgets import ChatView, DetailView, MessageTable, SessionTree

if TYPE_CHECKING:
    from sagg.models import Message, UnifiedSession


def format_tokens(tokens: int) -> str:
    """Format token count for display."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    elif tokens >= 1_000:
        return f"{tokens / 1_000:.1f}k"
    return str(tokens)


class HelpScreen(ModalScreen[None]):
    """Modal screen showing keyboard shortcuts."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("?", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        help_text = """[bold]Session Aggregator TUI[/bold]

[bold #58a6ff]Navigation[/bold #58a6ff]
  [#58a6ff]j/k[/]  or  [#58a6ff]Up/Down[/]   Move cursor
  [#58a6ff]g[/]                    Go to top
  [#58a6ff]G[/]                    Go to bottom
  [#58a6ff]Enter[/]                Select / Expand
  [#58a6ff]Tab[/]                  Next panel
  [#58a6ff]Shift+Tab[/]            Previous panel
  [#58a6ff]1/2/3[/]                Focus panel by number

[bold #58a6ff]Actions[/bold #58a6ff]
  [#58a6ff]/[/]                    Filter current view
  [#58a6ff]e[/]                    Export session
  [#58a6ff]r[/]                    Refresh sessions
  [#58a6ff]?[/]                    Show this help
  [#58a6ff]q[/]                    Quit

[bold #58a6ff]Panels[/bold #58a6ff]
  [#7ee787]1[/] Session Tree     Browse sessions by project/date
  [#7ee787]2[/] Message Table    View message list
  [#7ee787]3[/] Detail View      Full message content

[dim]Press any key to close[/dim]"""

        with Container(id="help-modal"):
            yield Static(help_text, id="help-content")

    def on_key(self, event) -> None:
        self.dismiss()


class FilterScreen(ModalScreen[str]):
    """Modal screen for entering filter query."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, current_filter: str = "") -> None:
        super().__init__()
        self._current_filter = current_filter

    def compose(self) -> ComposeResult:
        with Container(id="filter-container"):
            yield Static("Filter: ", id="filter-label")
            yield Input(
                value=self._current_filter,
                placeholder="Type to filter...",
                id="filter-input",
            )

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss("")


class ExportScreen(ModalScreen[str | None]):
    """Modal screen for export options."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("j", "json", "JSON"),
        Binding("a", "agenttrace", "AgentTrace"),
    ]

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self._session_id = session_id

    def compose(self) -> ComposeResult:
        export_text = f"""[bold]Export Session[/bold]

Session: [cyan]{self._session_id[:12]}...[/cyan]

[bold #58a6ff]Format[/bold #58a6ff]
  [#58a6ff]j[/]  JSON format
  [#58a6ff]a[/]  AgentTrace format

[dim]Press Escape to cancel[/dim]"""

        with Container(id="export-modal"):
            yield Static(export_text, id="export-content")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_json(self) -> None:
        self.dismiss("json")

    def action_agenttrace(self) -> None:
        self.dismiss("agenttrace")


class SaggApp(App[None]):
    """Session Aggregator TUI Application.

    A three-panel interface for browsing, viewing, and exporting
    AI coding sessions from various tools (OpenCode, Claude, Codex, Cursor).

    Layout:
    - Left: Session tree with search
    - Right: Scrollable chat view showing all messages
    """

    TITLE = "Session Aggregator"
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        # Navigation
        Binding("q", "quit", "Quit", priority=True),
        Binding("?", "help", "Help"),
        Binding("tab", "focus_next", "Next", show=False),
        Binding("shift+tab", "focus_previous", "Prev", show=False),
        Binding("1", "focus_sessions", "Sessions", show=False),
        Binding("2", "focus_chat", "Chat", show=False),
        # Actions
        Binding("slash", "focus_search", "Search"),
        Binding("e", "export", "Export"),
        Binding("r", "refresh", "Refresh"),
        # Vim-style navigation
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "cursor_top", "Top", show=False),
        Binding("G", "cursor_bottom", "Bottom", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._current_session: UnifiedSession | None = None
        self._current_message: Message | None = None
        self._sessions: list[UnifiedSession] = []
        self._filter_query: str = ""

    def compose(self) -> ComposeResult:
        """Compose the application layout.

        Two-panel layout:
        - Left: Session tree with search
        - Right: Scrollable chat view showing all messages
        """
        with Horizontal(id="main-container"):
            # Left panel - Session tree with search
            with Vertical(id="left-panel"):
                with Horizontal(id="search-bar"):
                    yield Static("", id="search-label")
                    yield Input(placeholder="Search...", id="search-input")
                yield SessionTree("", id="session-tree")
                yield Static("", id="stats-panel")

            # Right panel - Scrollable chat view with search
            with Vertical(id="right-panel"):
                with Horizontal(id="chat-header"):
                    yield Static("Conversation", id="chat-title")
                    yield Input(placeholder="Search in chat...", id="chat-search")
                yield ChatView(id="chat-view")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize the application."""
        self._load_sessions()
        self.query_one("#session-tree", SessionTree).focus()

    @work(exclusive=True, thread=True)
    def _load_sessions(self) -> None:
        """Load sessions from the store (in worker thread)."""
        from sagg.storage import SessionStore

        try:
            store = SessionStore()
            sessions = store.list_sessions(limit=500)
            store.close()
            self.call_from_thread(self._on_sessions_loaded, sessions)
        except Exception as e:
            self.call_from_thread(self.notify, f"Error loading sessions: {e}", severity="error")

    def _on_sessions_loaded(self, sessions: list[UnifiedSession]) -> None:
        """Handle loaded sessions (on main thread)."""
        self._sessions = sessions
        tree = self.query_one("#session-tree", SessionTree)
        tree.load_sessions(sessions)
        self._update_stats()

        if sessions:
            self.notify(f"Loaded {len(sessions)} sessions", severity="information")

    def _update_stats(self) -> None:
        """Update the stats panel."""
        tree = self.query_one("#session-tree", SessionTree)
        stats_panel = self.query_one("#stats-panel", Static)

        total_tokens = tree.total_tokens
        session_count = tree.session_count

        stats_text = Text()
        stats_text.append("Total: ", style="dim")
        stats_text.append(f"{session_count}", style="#7ee787")
        stats_text.append(" sessions  ", style="dim")
        stats_text.append(format_tokens(total_tokens), style="#58a6ff")
        stats_text.append(" tokens", style="dim")

        stats_panel.update(stats_text)

    # --- Session Tree Events ---

    def on_session_tree_session_selected(self, event: SessionTree.SessionSelected) -> None:
        """Handle session selection - load full conversation."""
        self._load_session_content(event.session_id)

    def on_session_tree_session_highlighted(self, event: SessionTree.SessionHighlighted) -> None:
        """Handle session highlight - also load conversation for preview."""
        self._load_session_content(event.session_id)

    @work(exclusive=True, thread=True)
    def _load_session_content(self, session_id: str) -> None:
        """Load full session content (in worker thread)."""
        from sagg.storage import SessionStore

        try:
            store = SessionStore()
            session = store.get_session(session_id)
            store.close()
            if session:
                self.call_from_thread(self._on_session_loaded, session)
        except Exception as e:
            self.call_from_thread(self.notify, f"Error loading session: {e}", severity="error")

    def _on_session_loaded(self, session: UnifiedSession) -> None:
        """Handle loaded session content (on main thread)."""
        self._current_session = session

        # Update chat view with full conversation
        chat = self.query_one("#chat-view", ChatView)
        chat.load_session(session)

        # Update title
        title = self.query_one("#chat-title", Static)
        msg_count = session.stats.message_count
        title_text = Text()
        title_text.append("Conversation", style="bold")
        title_text.append(f" ({msg_count} messages)", style="dim")
        title.update(title_text)

    # --- Actions ---

    def action_help(self) -> None:
        """Show help screen."""
        self.push_screen(HelpScreen())

    def action_focus_search(self) -> None:
        """Focus the search input."""
        self.query_one("#search-input", Input).focus()

    def action_export(self) -> None:
        """Export current session."""
        if not self._current_session:
            self.notify("No session selected", severity="warning")
            return

        def on_export(format_type: str | None) -> None:
            if format_type and self._current_session:
                self._do_export(self._current_session, format_type)

        self.push_screen(ExportScreen(self._current_session.id), on_export)

    @work(thread=True)
    def _do_export(self, session: UnifiedSession, format_type: str) -> None:
        """Perform export in worker thread."""
        from pathlib import Path
        import json

        try:
            # Export to ~/Downloads or current dir
            downloads = Path.home() / "Downloads"
            if not downloads.exists():
                downloads = Path.cwd()

            filename = f"session_{session.id[:8]}_{format_type}.json"
            filepath = downloads / filename

            if format_type == "agenttrace":
                from sagg.export import AgentTraceExporter

                exporter = AgentTraceExporter()
                content = exporter.export_to_json(session)
            else:
                content = session.model_dump_json(indent=2)

            filepath.write_text(content)
            self.call_from_thread(self.notify, f"Exported to {filepath}", severity="information")
        except Exception as e:
            self.call_from_thread(self.notify, f"Export failed: {e}", severity="error")

    def action_refresh(self) -> None:
        """Refresh session list."""
        self.notify("Refreshing sessions...", severity="information")
        self._load_sessions()

    def action_focus_sessions(self) -> None:
        """Focus the session tree."""
        self.query_one("#session-tree", SessionTree).focus()

    def action_focus_chat(self) -> None:
        """Focus the chat view."""
        self.query_one("#chat-view", ChatView).focus()

    # --- Search bar handling ---

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes (live filtering)."""
        if event.input.id == "search-input":
            # Filter sessions in tree
            query = event.value.lower().strip()
            tree = self.query_one("#session-tree", SessionTree)
            tree.filter_sessions(query)
        elif event.input.id == "chat-search":
            # Search within conversation
            query = event.value.strip()
            chat = self.query_one("#chat-view", ChatView)
            match_count = chat.search(query)

            # Update title with match count
            title = self.query_one("#chat-title", Static)
            if query and match_count > 0:
                title_text = Text()
                title_text.append("Conversation", style="bold")
                title_text.append(f" ({match_count} matches)", style="bold yellow")
                title.update(title_text)
            elif query and match_count == 0:
                title_text = Text()
                title_text.append("Conversation", style="bold")
                title_text.append(" (no matches)", style="dim")
                title.update(title_text)
            elif self._current_session:
                msg_count = self._current_session.stats.message_count
                title_text = Text()
                title_text.append("Conversation", style="bold")
                title_text.append(f" ({msg_count} messages)", style="dim")
                title.update(title_text)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search input submission."""
        if event.input.id == "search-input":
            # Focus the session tree after search
            self.query_one("#session-tree", SessionTree).focus()
        elif event.input.id == "chat-search":
            # Focus the chat view after search
            self.query_one("#chat-view", ChatView).focus()

    # --- Vim-style navigation ---

    def action_cursor_down(self) -> None:
        """Move cursor down (j key)."""
        focused = self.focused
        if focused is not None and hasattr(focused, "action_cursor_down"):
            getattr(focused, "action_cursor_down")()

    def action_cursor_up(self) -> None:
        """Move cursor up (k key)."""
        focused = self.focused
        if focused is not None and hasattr(focused, "action_cursor_up"):
            getattr(focused, "action_cursor_up")()

    def action_cursor_top(self) -> None:
        """Move cursor to top (g key)."""
        focused = self.focused
        if focused is not None and hasattr(focused, "scroll_home"):
            getattr(focused, "scroll_home")()

    def action_cursor_bottom(self) -> None:
        """Move cursor to bottom (G key)."""
        focused = self.focused
        if focused is not None and hasattr(focused, "scroll_end"):
            getattr(focused, "scroll_end")()


def run_tui() -> None:
    """Run the TUI application."""
    app = SaggApp()
    app.run()


if __name__ == "__main__":
    run_tui()
