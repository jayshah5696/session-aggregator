"""Chat view widget - scrollable conversation display."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

if TYPE_CHECKING:
    from sagg.models import (
        FileChangePart,
        Message,
        Part,
        TextPart,
        ToolCallPart,
        ToolResultPart,
        Turn,
        UnifiedSession,
    )


class ChatView(VerticalScroll):
    """Scrollable chat view displaying all messages in a conversation.

    Features:
    - Full conversation in one scrollable view
    - Color-coded message bubbles by role
    - Syntax highlighting for code blocks
    - Tool call visualization
    - Collapsible tool outputs
    """

    def __init__(
        self,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._session: UnifiedSession | None = None
        self._search_query: str = ""
        self._match_count: int = 0

    def load_session(self, session: UnifiedSession) -> None:
        """Load and display all messages from a session.

        Args:
            session: Session to display.
        """
        from sagg.models import TextPart, ToolCallPart, ToolResultPart, FileChangePart

        self._session = session

        # Clear existing content
        self.remove_children()

        # Add session header
        header = self._build_session_header(session)
        self.mount(Static(header, classes="chat-header"))

        # Add all messages
        msg_index = 0
        for turn in session.turns:
            for message in turn.messages:
                msg_widget = self._build_message_widget(message, msg_index)
                self.mount(msg_widget)
                msg_index += 1

        # Scroll to top
        self.scroll_home(animate=False)

    def _build_session_header(self, session: UnifiedSession) -> RenderableType:
        """Build the session header."""
        parts: list[RenderableType] = []

        # Title
        title = Text()
        title.append(session.title or "Untitled Session", style="bold")
        parts.append(title)

        # Metadata line
        meta = Text()
        meta.append(session.source.value, style="dim magenta")
        meta.append(" · ", style="dim")
        meta.append(session.project_name or "unknown", style="dim green")
        meta.append(" · ", style="dim")
        meta.append(session.created_at.strftime("%Y-%m-%d %H:%M"), style="dim")
        parts.append(meta)

        # Stats line
        stats = session.stats
        stats_text = Text()
        stats_text.append(f"{stats.message_count} messages", style="dim")
        stats_text.append(" · ", style="dim")
        total_tokens = stats.input_tokens + stats.output_tokens
        if total_tokens >= 1_000_000:
            stats_text.append(f"{total_tokens / 1_000_000:.1f}M tokens", style="dim cyan")
        elif total_tokens >= 1_000:
            stats_text.append(f"{total_tokens / 1_000:.1f}k tokens", style="dim cyan")
        else:
            stats_text.append(f"{total_tokens} tokens", style="dim cyan")
        parts.append(stats_text)

        return Group(*parts)

    def _build_message_widget(self, message: Message, index: int) -> Static:
        """Build a widget for a single message.

        Args:
            message: Message to render.
            index: Message index.

        Returns:
            Static widget containing the message.
        """
        from sagg.models import TextPart, ToolCallPart, ToolResultPart, FileChangePart

        content = self._render_message(message)

        # Determine CSS class based on role
        role_class = f"chat-message chat-{message.role}"

        return Static(content, classes=role_class)

    def _render_message(self, message: Message) -> RenderableType:
        """Render a complete message with all parts.

        Args:
            message: Message to render.

        Returns:
            Rich renderable.
        """
        from sagg.models import TextPart, ToolCallPart, ToolResultPart, FileChangePart

        parts: list[RenderableType] = []

        # Role header
        role_styles = {
            "user": ("bold #58a6ff", "USER"),
            "assistant": ("bold #7ee787", "ASSISTANT"),
            "tool": ("bold #d29922", "TOOL"),
            "system": ("bold #8b949e", "SYSTEM"),
        }
        style, label = role_styles.get(message.role, ("white", message.role.upper()))

        header = Text()
        header.append(label, style=style)
        header.append("  ", style="dim")
        header.append(message.timestamp.strftime("%H:%M:%S"), style="dim")

        if message.usage:
            tokens = message.usage.input_tokens + message.usage.output_tokens
            if tokens:
                header.append("  ", style="dim")
                if tokens >= 1000:
                    header.append(f"{tokens / 1000:.1f}k", style="dim cyan")
                else:
                    header.append(str(tokens), style="dim cyan")

        parts.append(header)
        parts.append(Text(""))

        # Process message parts
        for part in message.parts:
            if isinstance(part, TextPart):
                rendered = self._render_text(part.content)
                parts.append(rendered)
            elif isinstance(part, ToolCallPart):
                rendered = self._render_tool_call(part)
                parts.append(rendered)
            elif isinstance(part, ToolResultPart):
                rendered = self._render_tool_result(part)
                parts.append(rendered)
            elif isinstance(part, FileChangePart):
                rendered = self._render_file_change(part)
                parts.append(rendered)

        return Group(*parts)

    def _render_text(self, content: str) -> RenderableType:
        """Render text content with code block detection."""
        # Check for code blocks
        code_pattern = r"```(\w+)?\n(.*?)```"
        matches = list(re.finditer(code_pattern, content, re.DOTALL))

        if not matches:
            # Simple text or markdown
            if len(content) < 500 and "\n" not in content:
                return Text(content, style="#c9d1d9")
            try:
                return Markdown(content)
            except Exception:
                return Text(content, style="#c9d1d9")

        # Mixed content with code blocks
        parts: list[RenderableType] = []
        last_end = 0

        for match in matches:
            # Text before code
            if match.start() > last_end:
                before = content[last_end : match.start()].strip()
                if before:
                    try:
                        parts.append(Markdown(before))
                    except Exception:
                        parts.append(Text(before, style="#c9d1d9"))

            # Code block
            lang = match.group(1) or "text"
            code = match.group(2)
            parts.append(
                Syntax(
                    code,
                    lang,
                    theme="github-dark",
                    line_numbers=len(code.split("\n")) > 5,
                    word_wrap=True,
                    background_color="#161b22",
                )
            )
            last_end = match.end()

        # Text after last code block
        if last_end < len(content):
            after = content[last_end:].strip()
            if after:
                try:
                    parts.append(Markdown(after))
                except Exception:
                    parts.append(Text(after, style="#c9d1d9"))

        return Group(*parts)

    def _render_tool_call(self, part: ToolCallPart) -> Panel:
        """Render a tool call."""
        title = Text()
        title.append("→ ", style="#d29922")
        title.append(part.tool_name, style="bold #d29922")

        content_parts: list[RenderableType] = []

        if part.input is not None:
            if isinstance(part.input, (dict, list)):
                try:
                    json_str = json.dumps(part.input, indent=2, ensure_ascii=False)
                    if len(json_str) > 1000:
                        json_str = json_str[:1000] + "\n..."
                    content_parts.append(
                        Syntax(json_str, "json", theme="github-dark", word_wrap=True)
                    )
                except Exception:
                    content_parts.append(Text(str(part.input)[:500], style="dim"))
            else:
                text = str(part.input)
                if len(text) > 500:
                    text = text[:500] + "..."
                content_parts.append(Text(text, style="dim"))

        return Panel(
            Group(*content_parts) if content_parts else Text("[no input]", style="dim"),
            title=title,
            title_align="left",
            border_style="#d29922 dim",
            padding=(0, 1),
        )

    def _render_tool_result(self, part: ToolResultPart) -> Panel:
        """Render a tool result."""
        if part.is_error:
            title = Text("← error", style="bold #f85149")
            border = "#f85149 dim"
        else:
            title = Text("← result", style="bold #7ee787")
            border = "#7ee787 dim"

        output = part.output
        if len(output) > 2000:
            output = output[:2000] + "\n... (truncated)"

        # Detect content type
        content: RenderableType
        if output.strip().startswith(("{", "[")):
            try:
                json.loads(output)
                content = Syntax(output, "json", theme="github-dark", word_wrap=True)
            except json.JSONDecodeError:
                content = Text(output, style="#c9d1d9" if not part.is_error else "#f85149")
        else:
            content = Text(output, style="#c9d1d9" if not part.is_error else "#f85149")

        return Panel(
            content,
            title=title,
            title_align="left",
            border_style=border,
            padding=(0, 1),
        )

    def _render_file_change(self, part: FileChangePart) -> Panel:
        """Render a file change."""
        title = Text()
        title.append("📄 ", style="#58a6ff")
        title.append(part.path, style="bold #58a6ff")

        if part.diff:
            content = Syntax(part.diff, "diff", theme="github-dark", word_wrap=True)
        else:
            content = Text("[no diff]", style="dim italic")

        return Panel(
            content,
            title=title,
            title_align="left",
            border_style="#58a6ff dim",
            padding=(0, 1),
        )

    def clear_content(self) -> None:
        """Clear the chat view."""
        self._session = None
        self._search_query = ""
        self._match_count = 0
        self.remove_children()
        placeholder = Static(
            Text("Select a session to view conversation", style="dim italic"),
            classes="chat-placeholder",
        )
        self.mount(placeholder)

    def search(self, query: str) -> int:
        """Search for text in the conversation and highlight matches.

        Args:
            query: Search query string.

        Returns:
            Number of matches found.
        """
        self._search_query = query.lower().strip()

        if not self._session or not self._search_query:
            # Clear search - reload without highlights
            if self._session:
                self.load_session(self._session)
            self._match_count = 0
            return 0

        # Count matches and reload with highlighting
        self._match_count = self._count_matches()
        self._reload_with_highlights()
        return self._match_count

    def _count_matches(self) -> int:
        """Count matches in the current session."""
        from sagg.models import TextPart, ToolCallPart, ToolResultPart

        if not self._session or not self._search_query:
            return 0

        count = 0
        for turn in self._session.turns:
            for message in turn.messages:
                for part in message.parts:
                    if isinstance(part, TextPart):
                        count += part.content.lower().count(self._search_query)
                    elif isinstance(part, ToolCallPart):
                        count += part.tool_name.lower().count(self._search_query)
                        if part.input:
                            count += str(part.input).lower().count(self._search_query)
                    elif isinstance(part, ToolResultPart):
                        count += part.output.lower().count(self._search_query)
        return count

    def _reload_with_highlights(self) -> None:
        """Reload the session with search highlights."""
        if not self._session:
            return

        # Clear existing content
        self.remove_children()

        # Add session header
        header = self._build_session_header(self._session)
        self.mount(Static(header, classes="chat-header"))

        # Add all messages with highlighting
        msg_index = 0
        first_match_widget = None
        for turn in self._session.turns:
            for message in turn.messages:
                msg_widget = self._build_message_widget_highlighted(message, msg_index)
                self.mount(msg_widget)
                # Track first match for scrolling
                if first_match_widget is None and self._message_has_match(message):
                    first_match_widget = msg_widget
                msg_index += 1

        # Scroll to first match
        if first_match_widget:
            first_match_widget.scroll_visible()

    def _message_has_match(self, message: Message) -> bool:
        """Check if message contains search query."""
        from sagg.models import TextPart, ToolCallPart, ToolResultPart

        if not self._search_query:
            return False

        for part in message.parts:
            if isinstance(part, TextPart):
                if self._search_query in part.content.lower():
                    return True
            elif isinstance(part, ToolCallPart):
                if self._search_query in part.tool_name.lower():
                    return True
                if part.input and self._search_query in str(part.input).lower():
                    return True
            elif isinstance(part, ToolResultPart):
                if self._search_query in part.output.lower():
                    return True
        return False

    def _build_message_widget_highlighted(self, message: Message, index: int) -> Static:
        """Build a widget for a message with search highlighting."""
        from sagg.models import TextPart, ToolCallPart, ToolResultPart, FileChangePart

        content = self._render_message_highlighted(message)
        role_class = f"chat-message chat-{message.role}"

        # Add highlight class if message contains match
        if self._message_has_match(message):
            role_class += " chat-match"

        return Static(content, classes=role_class)

    def _render_message_highlighted(self, message: Message) -> RenderableType:
        """Render a message with search terms highlighted."""
        from sagg.models import TextPart, ToolCallPart, ToolResultPart, FileChangePart

        parts: list[RenderableType] = []

        # Role header (same as before)
        role_styles = {
            "user": ("bold #58a6ff", "USER"),
            "assistant": ("bold #7ee787", "ASSISTANT"),
            "tool": ("bold #d29922", "TOOL"),
            "system": ("bold #8b949e", "SYSTEM"),
        }
        style, label = role_styles.get(message.role, ("white", message.role.upper()))

        header = Text()
        header.append(label, style=style)
        header.append("  ", style="dim")
        header.append(message.timestamp.strftime("%H:%M:%S"), style="dim")

        if message.usage:
            tokens = message.usage.input_tokens + message.usage.output_tokens
            if tokens:
                header.append("  ", style="dim")
                if tokens >= 1000:
                    header.append(f"{tokens / 1000:.1f}k", style="dim cyan")
                else:
                    header.append(str(tokens), style="dim cyan")

        parts.append(header)
        parts.append(Text(""))

        # Process message parts with highlighting
        for part in message.parts:
            if isinstance(part, TextPart):
                rendered = self._render_text_highlighted(part.content)
                parts.append(rendered)
            elif isinstance(part, ToolCallPart):
                rendered = self._render_tool_call(part)
                parts.append(rendered)
            elif isinstance(part, ToolResultPart):
                rendered = self._render_tool_result(part)
                parts.append(rendered)
            elif isinstance(part, FileChangePart):
                rendered = self._render_file_change(part)
                parts.append(rendered)

        return Group(*parts)

    def _render_text_highlighted(self, content: str) -> RenderableType:
        """Render text with search terms highlighted."""
        if not self._search_query:
            return self._render_text(content)

        # Simple highlight - wrap matches in bold yellow
        text = Text()
        content_lower = content.lower()
        last_end = 0

        # Find all occurrences
        start = 0
        while True:
            pos = content_lower.find(self._search_query, start)
            if pos == -1:
                break

            # Add text before match
            if pos > last_end:
                text.append(content[last_end:pos], style="#c9d1d9")

            # Add highlighted match
            match_text = content[pos : pos + len(self._search_query)]
            text.append(match_text, style="bold black on yellow")

            last_end = pos + len(self._search_query)
            start = last_end

        # Add remaining text
        if last_end < len(content):
            text.append(content[last_end:], style="#c9d1d9")

        return text if text else Text(content, style="#c9d1d9")

    @property
    def match_count(self) -> int:
        """Return the number of search matches."""
        return self._match_count

    @property
    def current_session(self) -> UnifiedSession | None:
        """Return the currently displayed session."""
        return self._session
