"""AgentTrace exporter for session-aggregator.

This module implements the AgentTrace schema exporter, which converts
UnifiedSession data to the AgentTrace format for attribution tracking.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from sagg.models import (
    FileChangePart,
    ToolCallPart,
    UnifiedSession,
)


# AgentTrace Schema Version
AGENTTRACE_VERSION = "0.1.0"

# Tool names that indicate file modifications
FILE_MODIFICATION_TOOLS = frozenset(
    {
        # OpenCode / Claude tools
        "Edit",
        "Write",
        "edit",
        "write",
        # Codex tools
        "write_file",
        "edit_file",
        "apply_diff",
        # Cursor tools
        "file_edit",
        "file_write",
        # Generic
        "create_file",
        "modify_file",
        "patch_file",
    }
)


class AgentTraceRange(BaseModel):
    """Line range within a file that was modified."""

    start_line: int
    end_line: int


class AgentTraceContributor(BaseModel):
    """Contributor information for a conversation."""

    type: Literal["ai", "human"] = "ai"
    model_id: str | None = None


class AgentTraceConversation(BaseModel):
    """A conversation that contributed to a file."""

    url: str
    contributor: AgentTraceContributor
    ranges: list[AgentTraceRange] = Field(default_factory=list)


class AgentTraceFile(BaseModel):
    """A file with attribution to conversations."""

    path: str
    conversations: list[AgentTraceConversation] = Field(default_factory=list)


class AgentTraceTool(BaseModel):
    """Tool that generated the trace."""

    name: str
    version: str = "1.0.0"


class AgentTraceVcs(BaseModel):
    """Version control information."""

    type: Literal["git"] = "git"
    revision: str | None = None


class AgentTraceMetadata(BaseModel):
    """Additional metadata for the trace."""

    source_session_id: str
    project_path: str | None = None
    duration_ms: int | None = None
    token_usage: dict[str, int] | None = None


class AgentTraceRecord(BaseModel):
    """The root AgentTrace record.

    This is the canonical AgentTrace format for tracking AI contributions
    to source code files.
    """

    version: str = AGENTTRACE_VERSION
    id: str
    timestamp: str  # RFC 3339 format
    vcs: AgentTraceVcs | None = None
    tool: AgentTraceTool
    files: list[AgentTraceFile] = Field(default_factory=list)
    metadata: AgentTraceMetadata


class AgentTraceExporter:
    """Exporter for converting UnifiedSession to AgentTrace format.

    The AgentTraceExporter converts session data to the AgentTrace schema,
    which is designed for tracking AI contributions to source code for
    attribution and provenance purposes.

    Example:
        >>> exporter = AgentTraceExporter()
        >>> record = exporter.export_session(session)
        >>> json_str = exporter.export_to_json(session)
        >>> exporter.export_to_file(session, Path("trace.json"))
    """

    def __init__(self, tool_name: str = "opencode", tool_version: str = "1.0.0") -> None:
        """Initialize the exporter.

        Args:
            tool_name: Name of the tool that generated sessions.
            tool_version: Version of the tool.
        """
        self.tool_name = tool_name
        self.tool_version = tool_version

    def export_session(self, session: UnifiedSession) -> AgentTraceRecord:
        """Convert a UnifiedSession to an AgentTraceRecord.

        Args:
            session: The unified session to export.

        Returns:
            An AgentTraceRecord representing the session's file contributions.
        """
        # Extract files from session
        files = self._extract_files(session)

        # Build VCS info from git context
        vcs: AgentTraceVcs | None = None
        if session.git and session.git.commit:
            vcs = AgentTraceVcs(revision=session.git.commit)

        # Build token usage dict
        token_usage: dict[str, int] | None = None
        if session.stats.input_tokens > 0 or session.stats.output_tokens > 0:
            token_usage = {
                "input": session.stats.input_tokens,
                "output": session.stats.output_tokens,
            }

        # Build metadata
        metadata = AgentTraceMetadata(
            source_session_id=session.source_id,
            project_path=session.project_path,
            duration_ms=session.duration_ms,
            token_usage=token_usage,
        )

        # Create the record
        return AgentTraceRecord(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            vcs=vcs,
            tool=AgentTraceTool(name=self.tool_name, version=self.tool_version),
            files=files,
            metadata=metadata,
        )

    def export_to_json(self, session: UnifiedSession, *, indent: int | None = 2) -> str:
        """Export a session to JSON string.

        Args:
            session: The unified session to export.
            indent: JSON indentation level. None for compact output.

        Returns:
            JSON string representation of the AgentTrace record.
        """
        record = self.export_session(session)
        return record.model_dump_json(indent=indent)

    def export_to_file(self, session: UnifiedSession, path: Path) -> None:
        """Export a session to a JSON file.

        Args:
            session: The unified session to export.
            path: Path to write the JSON file.
        """
        json_content = self.export_to_json(session)
        path.write_text(json_content, encoding="utf-8")

    def _extract_files(self, session: UnifiedSession) -> list[AgentTraceFile]:
        """Extract file attribution data from a session.

        This method scans the session for file modifications, either from
        explicit FileChangePart entries or from tool calls to file
        modification tools (Edit, Write, etc.).

        Args:
            session: The session to extract files from.

        Returns:
            List of AgentTraceFile objects with conversation attribution.
        """
        # Map of file path -> set of (model_id, session_url) tuples
        file_contributions: dict[str, set[tuple[str | None, str]]] = {}
        session_url = f"local://session/{session.source_id}"

        for turn in session.turns:
            for message in turn.messages:
                model_id = message.model

                for part in message.parts:
                    file_path: str | None = None

                    # Check for FileChangePart
                    if isinstance(part, FileChangePart):
                        file_path = part.path

                    # Check for tool calls to file modification tools
                    elif isinstance(part, ToolCallPart):
                        if part.tool_name in FILE_MODIFICATION_TOOLS:
                            file_path = self._extract_path_from_tool_call(part)

                    if file_path:
                        # Normalize path (remove leading ./)
                        file_path = self._normalize_path(file_path)

                        if file_path not in file_contributions:
                            file_contributions[file_path] = set()
                        file_contributions[file_path].add((model_id, session_url))

        # Convert to AgentTraceFile objects
        files: list[AgentTraceFile] = []
        for file_path, contributions in sorted(file_contributions.items()):
            conversations: list[AgentTraceConversation] = []

            for model_id, url in contributions:
                contributor = AgentTraceContributor(
                    type="ai",
                    model_id=model_id,
                )
                # For v1, we skip line-level ranges
                conversation = AgentTraceConversation(
                    url=url,
                    contributor=contributor,
                    ranges=[],  # Empty for file-level attribution
                )
                conversations.append(conversation)

            files.append(AgentTraceFile(path=file_path, conversations=conversations))

        return files

    def _extract_path_from_tool_call(self, tool_call: ToolCallPart) -> str | None:
        """Extract file path from a tool call input.

        Args:
            tool_call: The tool call part to extract from.

        Returns:
            The file path if found, None otherwise.
        """
        input_data = tool_call.input
        if input_data is None:
            return None

        # Handle dict input (most common)
        if isinstance(input_data, dict):
            # Try common parameter names
            for key in ("filePath", "path", "file_path", "file", "filename"):
                if key in input_data and isinstance(input_data[key], str):
                    return input_data[key]

        # Handle string input (might be the path directly or JSON)
        if isinstance(input_data, str):
            # Try to parse as JSON
            try:
                parsed = json.loads(input_data)
                if isinstance(parsed, dict):
                    for key in ("filePath", "path", "file_path", "file", "filename"):
                        if key in parsed and isinstance(parsed[key], str):
                            return parsed[key]
            except (json.JSONDecodeError, TypeError):
                # If it looks like a path, use it directly
                if "/" in input_data or input_data.endswith((".py", ".ts", ".js", ".rs")):
                    return input_data

        return None

    def _normalize_path(self, path: str) -> str:
        """Normalize a file path for consistent storage.

        Args:
            path: The path to normalize.

        Returns:
            Normalized path string.
        """
        # Remove leading ./
        if path.startswith("./"):
            path = path[2:]

        # Remove leading /
        # (We want relative paths for portability)
        if path.startswith("/"):
            # Try to make it relative by finding common project indicators
            parts = path.split("/")
            # Look for common project root indicators
            for i, part in enumerate(parts):
                if part in ("src", "lib", "pkg", "app", "tests", "test"):
                    return "/".join(parts[i:])
            # Fallback: just use the last 3 components
            if len(parts) > 3:
                return "/".join(parts[-3:])

        return path
