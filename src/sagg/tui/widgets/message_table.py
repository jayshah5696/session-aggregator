"""Message table widget with virtual scrolling for displaying session messages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.message import Message as TextualMessage
from textual.widgets import DataTable

if TYPE_CHECKING:
    from sagg.models import Message, Part, TextPart, ToolCallPart, ToolResultPart, Turn


def extract_content_preview(parts: list[Part], max_length: int = 60) -> str:
    """Extract a text preview from message parts.

    Args:
        parts: List of message parts.
        max_length: Maximum preview length.

    Returns:
        Truncated text preview.
    """
    from sagg.models import TextPart, ToolCallPart, ToolResultPart

    texts = []
    for part in parts:
        if isinstance(part, TextPart):
            texts.append(part.content)
        elif isinstance(part, ToolCallPart):
            texts.append(f"[{part.tool_name}]")
        elif isinstance(part, ToolResultPart):
            output = part.output[:50] if part.output else ""
            texts.append(f"-> {output}")

    combined = " ".join(texts).replace("\n", " ").strip()
    if len(combined) > max_length:
        return combined[: max_length - 3] + "..."
    return combined


def format_tokens(tokens: int | None) -> str:
    """Format token count for display."""
    if tokens is None:
        return "-"
    if tokens >= 1000:
        return f"{tokens / 1000:.1f}k"
    return str(tokens)


class MessageTable(DataTable):
    """DataTable widget for displaying session messages.

    Features:
    - Virtual scrolling for performance with large message counts
    - Color-coded roles (user, assistant, tool)
    - Token counts per message
    - Content preview with truncation
    """

    class MessageSelected(TextualMessage):
        """Emitted when a message is selected."""

        def __init__(self, message_index: int, message: Message) -> None:
            self.message_index = message_index
            self.message = message
            super().__init__()

    class MessageHighlighted(TextualMessage):
        """Emitted when a message row is highlighted."""

        def __init__(self, message_index: int, message: Message) -> None:
            self.message_index = message_index
            self.message = message
            super().__init__()

    def __init__(
        self,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes, cursor_type="row")
        self._messages: list[Message] = []
        self._filtered_indices: list[int] = []
        self._filter_query: str = ""

    def on_mount(self) -> None:
        """Set up the table columns."""
        self.add_column("#", key="index", width=4)
        self.add_column("Role", key="role", width=10)
        self.add_column("Content", key="content")
        self.add_column("Tokens", key="tokens", width=8)

    def load_messages(self, turns: list[Turn]) -> None:
        """Load messages from turns into the table.

        Args:
            turns: List of turns containing messages.
        """
        self._messages = []
        self._filtered_indices = []

        # Flatten turns to messages
        for turn in turns:
            for message in turn.messages:
                self._messages.append(message)

        self._rebuild_table()

    def _rebuild_table(self) -> None:
        """Rebuild the table with current messages and filter."""
        self.clear()

        messages_to_show = (
            [self._messages[i] for i in self._filtered_indices]
            if self._filter_query
            else self._messages
        )

        for idx, message in enumerate(messages_to_show):
            actual_idx = self._filtered_indices[idx] if self._filter_query else idx
            self._add_message_row(actual_idx, message)

    def _add_message_row(self, index: int, message: Message) -> None:
        """Add a message row to the table.

        Args:
            index: Message index (0-based).
            message: Message to add.
        """
        # Role with color
        role_styles = {
            "user": "bold #58a6ff",
            "assistant": "bold #7ee787",
            "tool": "bold #d29922",
            "system": "bold #8b949e",
        }
        role_style = role_styles.get(message.role, "white")
        role_text = Text(message.role, style=role_style)

        # Content preview
        content = extract_content_preview(message.parts)
        content_text = Text(content, style="#c9d1d9")

        # Tokens
        tokens = 0
        if message.usage:
            tokens = message.usage.input_tokens + message.usage.output_tokens
        tokens_text = Text(format_tokens(tokens) if tokens else "-", style="dim")

        # Index
        index_text = Text(str(index + 1), style="dim #8b949e")

        self.add_row(
            index_text,
            role_text,
            content_text,
            tokens_text,
            key=str(index),
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection."""
        if event.row_key is not None:
            try:
                index = int(str(event.row_key.value))
                if 0 <= index < len(self._messages):
                    self.post_message(self.MessageSelected(index, self._messages[index]))
            except (ValueError, TypeError):
                pass

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle row highlight (cursor movement)."""
        if event.row_key is not None:
            try:
                index = int(str(event.row_key.value))
                if 0 <= index < len(self._messages):
                    self.post_message(self.MessageHighlighted(index, self._messages[index]))
            except (ValueError, TypeError):
                pass

    def filter_messages(self, query: str) -> None:
        """Filter messages by content.

        Args:
            query: Filter query string.
        """
        from sagg.models import TextPart, ToolCallPart

        self._filter_query = query.lower().strip()
        self._filtered_indices = []

        if not self._filter_query:
            self._rebuild_table()
            return

        for idx, message in enumerate(self._messages):
            # Check role
            if self._filter_query in message.role.lower():
                self._filtered_indices.append(idx)
                continue

            # Check content
            for part in message.parts:
                if isinstance(part, TextPart):
                    if self._filter_query in part.content.lower():
                        self._filtered_indices.append(idx)
                        break
                elif isinstance(part, ToolCallPart):
                    if self._filter_query in part.tool_name.lower():
                        self._filtered_indices.append(idx)
                        break

        self._rebuild_table()

    def get_message(self, index: int) -> Message | None:
        """Get a message by index.

        Args:
            index: Message index.

        Returns:
            Message if found, None otherwise.
        """
        if 0 <= index < len(self._messages):
            return self._messages[index]
        return None

    @property
    def message_count(self) -> int:
        """Return the number of loaded messages."""
        return len(self._messages)

    @property
    def visible_count(self) -> int:
        """Return the number of visible (filtered) messages."""
        if self._filter_query:
            return len(self._filtered_indices)
        return len(self._messages)

    def select_first(self) -> None:
        """Select the first row."""
        if self.row_count > 0:
            self.move_cursor(row=0)

    def select_last(self) -> None:
        """Select the last row."""
        if self.row_count > 0:
            self.move_cursor(row=self.row_count - 1)
