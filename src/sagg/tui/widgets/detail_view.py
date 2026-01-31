"""Detail view widget for displaying full message content with syntax highlighting."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from rich.console import RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual.widgets import Static

if TYPE_CHECKING:
    from sagg.models import (
        FileChangePart,
        Message,
        ToolCallPart,
        ToolResultPart,
        UnifiedSession,
    )


class DetailView(Static):
    """Widget for displaying detailed message content.

    Features:
    - Full message content display
    - Syntax highlighting for code blocks
    - Tool call visualization with input/output
    - Markdown rendering
    - Scrollable content
    """

    def __init__(
        self,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._current_message: Message | None = None

    def show_message(self, message: Message) -> None:
        """Display a message in the detail view.

        Args:
            message: Message to display.
        """
        from sagg.models import FileChangePart, TextPart, ToolCallPart, ToolResultPart

        self._current_message = message

        # Build rich content
        content_parts: list[RenderableType] = []

        # Header with role and metadata
        header = self._build_header(message)
        content_parts.append(header)
        content_parts.append(Text(""))

        # Process each part
        for part in message.parts:
            if isinstance(part, TextPart):
                rendered = self._render_text_part(part.content)
                content_parts.append(rendered)
            elif isinstance(part, ToolCallPart):
                rendered = self._render_tool_call(part)
                content_parts.append(rendered)
            elif isinstance(part, ToolResultPart):
                rendered = self._render_tool_result(part)
                content_parts.append(rendered)
            elif isinstance(part, FileChangePart):
                rendered = self._render_file_change(part)
                content_parts.append(rendered)

        # Combine all parts
        from rich.console import Group

        self.update(Group(*content_parts))

    def _build_header(self, message: Message) -> Panel:
        """Build the message header panel.

        Args:
            message: Message to build header for.

        Returns:
            Rich Panel with header content.
        """
        role_styles = {
            "user": "#58a6ff",
            "assistant": "#7ee787",
            "tool": "#d29922",
            "system": "#8b949e",
        }
        role_color = role_styles.get(message.role, "#c9d1d9")

        header_text = Text()
        header_text.append(message.role.upper(), style=f"bold {role_color}")

        if message.model:
            header_text.append("  ", style="dim")
            header_text.append(message.model, style="dim italic")

        if message.usage:
            tokens = message.usage.input_tokens + message.usage.output_tokens
            if tokens:
                header_text.append("  ", style="dim")
                header_text.append(f"{tokens:,} tokens", style="dim cyan")

        header_text.append("  ", style="dim")
        header_text.append(message.timestamp.strftime("%H:%M:%S"), style="dim")

        return Panel(
            header_text,
            border_style="dim",
            padding=(0, 1),
            height=3,
        )

    def _render_text_part(self, content: str) -> RenderableType:
        """Render text content with code block detection.

        Args:
            content: Text content to render.

        Returns:
            Rich renderable.
        """
        # Check if content contains code blocks
        code_block_pattern = r"```(\w+)?\n(.*?)```"
        matches = list(re.finditer(code_block_pattern, content, re.DOTALL))

        if not matches:
            # No code blocks, try to render as markdown
            try:
                return Markdown(content)
            except Exception:
                return Text(content, style="#c9d1d9")

        # Mix of text and code blocks
        from rich.console import Group

        parts: list[RenderableType] = []
        last_end = 0

        for match in matches:
            # Text before code block
            if match.start() > last_end:
                before_text = content[last_end : match.start()]
                if before_text.strip():
                    try:
                        parts.append(Markdown(before_text))
                    except Exception:
                        parts.append(Text(before_text, style="#c9d1d9"))

            # Code block
            language = match.group(1) or "text"
            code = match.group(2)
            parts.append(
                Syntax(
                    code,
                    language,
                    theme="github-dark",
                    line_numbers=True,
                    word_wrap=True,
                    background_color="#161b22",
                )
            )
            last_end = match.end()

        # Text after last code block
        if last_end < len(content):
            after_text = content[last_end:]
            if after_text.strip():
                try:
                    parts.append(Markdown(after_text))
                except Exception:
                    parts.append(Text(after_text, style="#c9d1d9"))

        return Group(*parts)

    def _render_tool_call(self, part: "ToolCallPart") -> Panel:
        """Render a tool call part.

        Args:
            part: Tool call part to render.

        Returns:
            Rich Panel with tool call details.
        """
        from sagg.models import ToolCallPart

        title_text = Text()
        title_text.append(" ", style="#d29922")
        title_text.append(part.tool_name, style="bold #d29922")

        content_parts: list[RenderableType] = []

        # Tool ID
        id_text = Text()
        id_text.append("ID: ", style="dim")
        id_text.append(
            part.tool_id[:16] + "..." if len(part.tool_id) > 16 else part.tool_id, style="dim cyan"
        )
        content_parts.append(id_text)

        # Input
        if part.input is not None:
            content_parts.append(Text(""))
            content_parts.append(Text("Input:", style="bold dim"))

            if isinstance(part.input, (dict, list)):
                try:
                    json_str = json.dumps(part.input, indent=2, ensure_ascii=False)
                    # Truncate if too long
                    if len(json_str) > 2000:
                        json_str = json_str[:2000] + "\n... (truncated)"
                    content_parts.append(
                        Syntax(
                            json_str,
                            "json",
                            theme="github-dark",
                            word_wrap=True,
                            background_color="#161b22",
                        )
                    )
                except Exception:
                    content_parts.append(Text(str(part.input)[:2000], style="#c9d1d9"))
            elif isinstance(part.input, str):
                input_text = part.input if len(part.input) <= 2000 else part.input[:2000] + "..."
                content_parts.append(Text(input_text, style="#c9d1d9"))

        from rich.console import Group

        return Panel(
            Group(*content_parts),
            title=title_text,
            title_align="left",
            border_style="#d29922",
            padding=(0, 1),
        )

    def _render_tool_result(self, part: "ToolResultPart") -> Panel:
        """Render a tool result part.

        Args:
            part: Tool result part to render.

        Returns:
            Rich Panel with tool result details.
        """
        from sagg.models import ToolResultPart

        # Determine style based on error status
        if part.is_error:
            border_style = "#f85149"
            status_text = " error"
            status_style = "#f85149"
        else:
            border_style = "#7ee787"
            status_text = " success"
            status_style = "#7ee787"

        title_text = Text()
        title_text.append(status_text, style=f"bold {status_style}")
        title_text.append(f"  {part.tool_id[:16]}...", style="dim")

        # Output content
        output = part.output
        if len(output) > 3000:
            output = output[:3000] + "\n... (truncated)"

        # Try to detect if output is code-like
        content: RenderableType
        if output.strip().startswith("{") or output.strip().startswith("["):
            try:
                # Try to parse as JSON
                json.loads(output)
                content = Syntax(
                    output,
                    "json",
                    theme="github-dark",
                    word_wrap=True,
                    background_color="#161b22",
                )
            except json.JSONDecodeError:
                content = Text(output, style="#c9d1d9")
        elif "\n" in output and any(
            kw in output for kw in ["def ", "class ", "import ", "function ", "const "]
        ):
            # Likely code
            content = Syntax(
                output,
                "python",
                theme="github-dark",
                word_wrap=True,
                background_color="#161b22",
            )
        else:
            content = Text(output, style="#c9d1d9")

        return Panel(
            content,
            title=title_text,
            title_align="left",
            border_style=border_style,
            padding=(0, 1),
        )

    def _render_file_change(self, part: "FileChangePart") -> Panel:
        """Render a file change part.

        Args:
            part: File change part to render.

        Returns:
            Rich Panel with file change details.
        """
        from sagg.models import FileChangePart

        title_text = Text()
        title_text.append(" ", style="#58a6ff")
        title_text.append(part.path, style="bold #58a6ff")

        content: RenderableType
        if part.diff:
            content = Syntax(
                part.diff,
                "diff",
                theme="github-dark",
                word_wrap=True,
                background_color="#161b22",
            )
        else:
            content = Text("[No diff available]", style="dim italic")

        return Panel(
            content,
            title=title_text,
            title_align="left",
            border_style="#58a6ff",
            padding=(0, 1),
        )

    def clear_content(self) -> None:
        """Clear the detail view."""
        self._current_message = None
        placeholder = Text(
            "Select a message to view details",
            style="dim italic",
            justify="center",
        )
        self.update(placeholder)

    def show_session_info(self, session: "UnifiedSession") -> None:
        """Display session summary information.

        Args:
            session: Session to display summary for.
        """
        from sagg.models import UnifiedSession

        from rich.console import Group
        from rich.table import Table

        parts: list[RenderableType] = []

        # Title
        title_text = Text()
        title_text.append(session.title or "Untitled Session", style="bold #c9d1d9")
        parts.append(Panel(title_text, border_style="dim", padding=(0, 1)))
        parts.append(Text(""))

        # Info table
        info_table = Table(show_header=False, box=None, padding=(0, 2))
        info_table.add_column("Key", style="dim")
        info_table.add_column("Value", style="#c9d1d9")

        info_table.add_row("ID", session.id)
        info_table.add_row("Source", session.source.value)
        info_table.add_row("Project", session.project_name or "-")
        info_table.add_row("Created", session.created_at.strftime("%Y-%m-%d %H:%M"))

        if session.git:
            info_table.add_row("Branch", session.git.branch or "-")

        parts.append(info_table)
        parts.append(Text(""))

        # Stats
        stats = session.stats
        stats_text = Text()
        stats_text.append("Turns: ", style="dim")
        stats_text.append(str(stats.turn_count), style="#7ee787")
        stats_text.append("  Messages: ", style="dim")
        stats_text.append(str(stats.message_count), style="#7ee787")
        stats_text.append("  Tools: ", style="dim")
        stats_text.append(str(stats.tool_call_count), style="#d29922")
        parts.append(stats_text)

        # Tokens
        tokens_text = Text()
        tokens_text.append("Input: ", style="dim")
        tokens_text.append(f"{stats.input_tokens:,}", style="#58a6ff")
        tokens_text.append("  Output: ", style="dim")
        tokens_text.append(f"{stats.output_tokens:,}", style="#58a6ff")
        parts.append(tokens_text)

        # Models
        if session.models:
            parts.append(Text(""))
            parts.append(Text("Models:", style="bold dim"))
            for model in session.models:
                model_text = Text()
                model_text.append("  ", style="dim")
                model_text.append(model.model_id, style="#c9d1d9")
                model_text.append(f" ({model.message_count} msgs)", style="dim")
                parts.append(model_text)

        self.update(Group(*parts))

    @property
    def current_message(self) -> Message | None:
        """Return the currently displayed message."""
        return self._current_message
