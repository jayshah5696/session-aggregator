"""Unified session models for session-aggregator.

This module defines the canonical data models for representing coding sessions
from various AI tools (OpenCode, Claude, Codex, Cursor, Gemini CLI, Ampcode,
Antigravity) in a unified format.
"""

import time
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class SourceTool(str, Enum):
    """Supported source tools for session data."""

    OPENCODE = "opencode"
    CLAUDE = "claude"
    CODEX = "codex"
    CURSOR = "cursor"
    GEMINI = "gemini"
    ANTIGRAVITY = "antigravity"
    AMPCODE = "ampcode"


class TokenUsage(BaseModel):
    """Token usage for a single message or request."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int | None = None


class ModelUsage(BaseModel):
    """Aggregated usage statistics for a specific model within a session."""

    model_id: str  # models.dev format: provider/model
    provider: str
    message_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class TextPart(BaseModel):
    """A text content part within a message."""

    type: Literal["text"] = "text"
    content: str


class ToolCallPart(BaseModel):
    """A tool invocation part within a message."""

    type: Literal["tool_call"] = "tool_call"
    tool_name: str
    tool_id: str
    input: dict | list | str | None = None


class ToolResultPart(BaseModel):
    """A tool result part within a message."""

    type: Literal["tool_result"] = "tool_result"
    tool_id: str
    output: str
    is_error: bool = False


class FileChangePart(BaseModel):
    """A file change part representing a modification to a file."""

    type: Literal["file_change"] = "file_change"
    path: str
    diff: str | None = None


Part = TextPart | ToolCallPart | ToolResultPart | FileChangePart


class Message(BaseModel):
    """A single message within a conversation turn."""

    id: str
    role: Literal["user", "assistant", "system", "tool"]
    timestamp: datetime
    model: str | None = None
    parts: list[Part] = Field(default_factory=list)
    usage: TokenUsage | None = None


class Turn(BaseModel):
    """A conversation turn consisting of one or more messages.

    A turn typically represents a user request and the assistant's response,
    including any tool calls made during that response.
    """

    id: str
    index: int
    started_at: datetime
    ended_at: datetime | None = None
    messages: list[Message] = Field(default_factory=list)


class GitContext(BaseModel):
    """Git repository context for a session."""

    branch: str | None = None
    commit: str | None = None
    remote: str | None = None


class SessionStats(BaseModel):
    """Aggregated statistics for a session."""

    turn_count: int = 0
    message_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_call_count: int = 0
    files_modified: list[str] = Field(default_factory=list)


class UnifiedSession(BaseModel):
    """The canonical representation of a coding session.

    This model provides a unified structure for sessions from various AI coding
    tools, enabling consistent storage, querying, and analysis across different
    source tools.
    """

    # Identity
    id: str  # UUID v7
    source: SourceTool
    source_id: str
    source_path: str

    # Metadata
    title: str | None = None
    project_path: str | None = None
    project_name: str | None = None

    # Git context
    git: GitContext | None = None

    # Timing
    created_at: datetime
    updated_at: datetime
    duration_ms: int | None = None

    # Stats
    stats: SessionStats = Field(default_factory=SessionStats)

    # Models used
    models: list[ModelUsage] = Field(default_factory=list)

    # Content
    turns: list[Turn] = Field(default_factory=list)

    def to_jsonl(self) -> str:
        """Serialize turns to JSONL format for storage.

        Returns:
            JSONL string with one message per line.
        """
        lines = []
        for turn in self.turns:
            for message in turn.messages:
                lines.append(message.model_dump_json())
        return "\n".join(lines)

    @classmethod
    def messages_from_jsonl(cls, content: str) -> list[Message]:
        """Deserialize messages from JSONL content.

        Args:
            content: JSONL string with one message per line.

        Returns:
            List of Message objects.
        """
        messages = []
        for line in content.strip().split("\n"):
            if line:
                messages.append(Message.model_validate_json(line))
        return messages

    def extract_text_content(self) -> str:
        """Extract all text content for full-text search indexing.

        Returns:
            Concatenated text from all TextPart objects in the session.
        """
        texts = []
        for turn in self.turns:
            for message in turn.messages:
                for part in message.parts:
                    if isinstance(part, TextPart):
                        texts.append(part.content)
        return "\n".join(texts)

    def get_tool_counts(self) -> dict[str, int]:
        """Get tool call counts by tool name.

        Returns:
            Dictionary mapping tool names to their call counts.
        """
        counts: dict[str, int] = {}
        for turn in self.turns:
            for message in turn.messages:
                for part in message.parts:
                    if isinstance(part, ToolCallPart):
                        counts[part.tool_name] = counts.get(part.tool_name, 0) + 1
        return counts


def generate_session_id() -> str:
    """Generate a UUID v7 (time-sortable) for session identification.

    UUID v7 embeds a Unix timestamp in the first 48 bits, making IDs
    naturally sortable by creation time while maintaining uniqueness.

    Returns:
        A UUID v7 string in standard hyphenated format.
    """
    # Get current timestamp in milliseconds
    timestamp_ms = int(time.time() * 1000)

    # UUID v7 structure:
    # - 48 bits: Unix timestamp in milliseconds
    # - 4 bits: version (7)
    # - 12 bits: random
    # - 2 bits: variant (10)
    # - 62 bits: random

    # Generate random bytes for the random portions
    random_bytes = uuid.uuid4().bytes

    # Build the UUID v7
    # First 6 bytes: timestamp (48 bits)
    uuid_bytes = bytearray(16)
    uuid_bytes[0] = (timestamp_ms >> 40) & 0xFF
    uuid_bytes[1] = (timestamp_ms >> 32) & 0xFF
    uuid_bytes[2] = (timestamp_ms >> 24) & 0xFF
    uuid_bytes[3] = (timestamp_ms >> 16) & 0xFF
    uuid_bytes[4] = (timestamp_ms >> 8) & 0xFF
    uuid_bytes[5] = timestamp_ms & 0xFF

    # Bytes 6-7: version (4 bits) + random (12 bits)
    uuid_bytes[6] = 0x70 | (random_bytes[6] & 0x0F)  # version 7
    uuid_bytes[7] = random_bytes[7]

    # Bytes 8-15: variant (2 bits) + random (62 bits)
    uuid_bytes[8] = 0x80 | (random_bytes[8] & 0x3F)  # variant 10
    uuid_bytes[9:16] = random_bytes[9:16]

    # Convert to UUID and return as string
    return str(uuid.UUID(bytes=bytes(uuid_bytes)))


def extract_project_name(path: str) -> str:
    """Extract the project name from a filesystem path.

    The project name is typically the last component of the path,
    representing the root directory of a project.

    Args:
        path: A filesystem path to a project directory.

    Returns:
        The project name (last path component), or "unknown" if
        the path is empty or invalid.

    Examples:
        >>> extract_project_name("/Users/dev/projects/my-app")
        'my-app'
        >>> extract_project_name("/home/user/code/")
        'code'
        >>> extract_project_name("")
        'unknown'
    """
    if not path:
        return "unknown"

    project_path = Path(path)
    name = project_path.name

    # Handle trailing slashes or empty names
    if not name:
        # Try parent if path ends with separator
        name = project_path.parent.name

    return name if name else "unknown"
