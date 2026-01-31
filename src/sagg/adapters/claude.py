"""Claude Code session adapter.

Parses sessions from Claude Code's JSONL format stored in ~/.claude/projects/.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sagg.adapters.base import SessionAdapter, SessionRef
from sagg.models import (
    GitContext,
    Message,
    ModelUsage,
    Part,
    SessionStats,
    SourceTool,
    TextPart,
    TokenUsage,
    ToolCallPart,
    ToolResultPart,
    Turn,
    UnifiedSession,
    extract_project_name,
    generate_session_id,
)


def decode_project_path(encoded: str) -> str:
    """Decode a Claude Code encoded project path.

    Claude Code encodes paths by replacing '/' with '-'.
    Example: '-Users-foo-code-myapp' -> '/Users/foo/code/myapp'

    Args:
        encoded: The encoded path string (e.g., '-Users-foo-code-myapp')

    Returns:
        The decoded filesystem path (e.g., '/Users/foo/code/myapp')
    """
    if not encoded:
        return ""

    # Replace leading dash with / and all other dashes with /
    # The encoded path starts with - which represents the root /
    if encoded.startswith("-"):
        return "/" + encoded[1:].replace("-", "/")

    return encoded.replace("-", "/")


class ClaudeCodeAdapter(SessionAdapter):
    """Adapter for Claude Code session files."""

    @property
    def name(self) -> str:
        """Adapter identifier."""
        return "claude"

    @property
    def display_name(self) -> str:
        """Human-readable name."""
        return "Claude Code"

    def get_default_path(self) -> Path:
        """Get default path for Claude Code sessions."""
        return Path.home() / ".claude" / "projects"

    def is_available(self) -> bool:
        """Check if Claude Code sessions directory exists."""
        return self.get_default_path().exists()

    def list_sessions(self, since: datetime | None = None) -> list[SessionRef]:
        """List all Claude Code session files.

        Args:
            since: Optional datetime to filter sessions updated after this time.

        Returns:
            List of SessionRef objects for each session file found.
        """
        sessions: list[SessionRef] = []
        projects_path = self.get_default_path()

        if not projects_path.exists():
            return sessions

        # Iterate through project directories
        for project_dir in projects_path.iterdir():
            if not project_dir.is_dir():
                continue

            # Find all JSONL files, excluding agent-*.jsonl subagent files
            for jsonl_file in project_dir.glob("*.jsonl"):
                if jsonl_file.name.startswith("agent-"):
                    continue

                # Get file timestamps (timezone-aware)
                stat = jsonl_file.stat()
                created_at = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc)
                updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

                # Filter by since if provided
                if since is not None and updated_at <= since:
                    continue

                # Session ID is the filename without extension
                session_id = jsonl_file.stem

                sessions.append(
                    SessionRef(
                        id=session_id,
                        path=jsonl_file,
                        created_at=created_at,
                        updated_at=updated_at,
                    )
                )

        return sessions

    def parse_session(self, ref: SessionRef) -> UnifiedSession:
        """Parse a Claude Code JSONL session file into UnifiedSession format.

        Args:
            ref: SessionRef pointing to the session file.

        Returns:
            UnifiedSession with parsed content.
        """
        entries = self._read_jsonl(ref.path)

        # Extract metadata from first entry with relevant fields
        project_path: str | None = None
        git_branch: str | None = None
        version: str | None = None

        for entry in entries:
            if "cwd" in entry and project_path is None:
                project_path = entry["cwd"]
            if "gitBranch" in entry and git_branch is None:
                git_branch = entry["gitBranch"]
            if "version" in entry and version is None:
                version = entry["version"]
            if project_path and git_branch:
                break

        # If no cwd found in entries, decode from directory name
        if project_path is None:
            encoded_path = ref.path.parent.name
            project_path = decode_project_path(encoded_path)

        # Build turns from entries
        turns = self._build_turns(entries)

        # Calculate stats
        stats = self._calculate_stats(turns)

        # Aggregate model usage
        models = self._aggregate_model_usage(turns)

        # Build git context
        git_context = GitContext(branch=git_branch) if git_branch else None

        # Calculate duration
        duration_ms: int | None = None
        if turns:
            first_msg = turns[0].started_at
            last_msg = turns[-1].ended_at or turns[-1].started_at
            duration_ms = int((last_msg - first_msg).total_seconds() * 1000)

        return UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.CLAUDE,
            source_id=ref.id,
            source_path=str(ref.path),
            title=self._extract_title(turns),
            project_path=project_path,
            project_name=extract_project_name(project_path) if project_path else None,
            git=git_context,
            created_at=ref.created_at,
            updated_at=ref.updated_at,
            duration_ms=duration_ms,
            stats=stats,
            models=models,
            turns=turns,
        )

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        """Read and parse a JSONL file.

        Args:
            path: Path to the JSONL file.

        Returns:
            List of parsed JSON objects.
        """
        entries: list[dict[str, Any]] = []

        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    # Skip malformed lines
                    continue

        return entries

    def _build_turns(self, entries: list[dict[str, Any]]) -> list[Turn]:
        """Build turns from JSONL entries.

        Groups entries by parentUuid to form conversation turns.

        Args:
            entries: List of parsed JSONL entries.

        Returns:
            List of Turn objects.
        """
        # Filter entries that have a message field
        message_entries = [e for e in entries if "message" in e]

        if not message_entries:
            return []

        # Group by parentUuid - entries with same parent form a turn
        # Entries without parentUuid start new turns (user messages)
        turns: list[Turn] = []
        current_turn_messages: list[Message] = []
        current_turn_id: str | None = None
        current_turn_start: datetime | None = None

        for entry in message_entries:
            parent_uuid = entry.get("parentUuid")
            entry_uuid = entry.get("uuid", "")
            timestamp = self._parse_timestamp(entry.get("timestamp", ""))

            message = self._parse_message(entry, timestamp)
            if message is None:
                continue

            # User messages start new turns
            if message.role == "user":
                # Save previous turn if exists
                if current_turn_messages:
                    turn_end = current_turn_messages[-1].timestamp
                    turns.append(
                        Turn(
                            id=current_turn_id or generate_session_id(),
                            index=len(turns),
                            started_at=current_turn_start or turn_end,
                            ended_at=turn_end,
                            messages=current_turn_messages,
                        )
                    )

                # Start new turn
                current_turn_messages = [message]
                current_turn_id = entry_uuid
                current_turn_start = timestamp
            else:
                # Add to current turn
                current_turn_messages.append(message)

        # Don't forget the last turn
        if current_turn_messages:
            turn_end = current_turn_messages[-1].timestamp
            turns.append(
                Turn(
                    id=current_turn_id or generate_session_id(),
                    index=len(turns),
                    started_at=current_turn_start or turn_end,
                    ended_at=turn_end,
                    messages=current_turn_messages,
                )
            )

        return turns

    def _parse_message(self, entry: dict[str, Any], timestamp: datetime) -> Message | None:
        """Parse a single JSONL entry into a Message.

        Args:
            entry: The JSONL entry dict.
            timestamp: Parsed timestamp for the message.

        Returns:
            Message object or None if entry cannot be parsed.
        """
        msg_data = entry.get("message")
        if not msg_data:
            return None

        role = msg_data.get("role", "user")
        # Map Claude roles to our unified roles
        if role not in ("user", "assistant", "system", "tool"):
            if entry.get("type") == "tool_result":
                role = "tool"
            else:
                role = "user"

        # Parse content blocks
        content = msg_data.get("content", [])
        parts = self._parse_content_blocks(content)

        # Extract model (only present on assistant messages)
        model = msg_data.get("model")

        # Parse usage
        usage = None
        usage_data = msg_data.get("usage")
        if usage_data:
            usage = TokenUsage(
                input_tokens=usage_data.get("input_tokens", 0),
                output_tokens=usage_data.get("output_tokens", 0),
                cached_tokens=usage_data.get("cache_read_input_tokens"),
            )

        return Message(
            id=entry.get("uuid", generate_session_id()),
            role=role,
            timestamp=timestamp,
            model=model,
            parts=parts,
            usage=usage,
        )

    def _parse_content_blocks(self, content: list[dict[str, Any]] | str) -> list[Part]:
        """Parse Claude content blocks into unified Part objects.

        Args:
            content: Either a list of content block dicts or a plain string.

        Returns:
            List of Part objects.
        """
        parts: list[Part] = []

        # Handle string content
        if isinstance(content, str):
            if content:
                parts.append(TextPart(content=content))
            return parts

        # Handle list of content blocks
        for block in content:
            if not isinstance(block, dict):
                continue

            block_type = block.get("type", "")

            if block_type == "text":
                text = block.get("text", "")
                if text:
                    parts.append(TextPart(content=text))

            elif block_type == "tool_use":
                parts.append(
                    ToolCallPart(
                        tool_name=block.get("name", "unknown"),
                        tool_id=block.get("id", ""),
                        input=block.get("input"),
                    )
                )

            elif block_type == "tool_result":
                result_content = block.get("content", "")
                # Content can be a string or list of content blocks
                if isinstance(result_content, list):
                    # Extract text from nested content blocks
                    texts = []
                    for item in result_content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            texts.append(item.get("text", ""))
                    result_content = "\n".join(texts)

                parts.append(
                    ToolResultPart(
                        tool_id=block.get("tool_use_id", ""),
                        output=str(result_content),
                        is_error=block.get("is_error", False),
                    )
                )

        return parts

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse an ISO format timestamp.

        Args:
            timestamp_str: ISO format timestamp string.

        Returns:
            Parsed datetime object, or current time if parsing fails.
        """
        if not timestamp_str:
            return datetime.now()

        try:
            # Handle ISO format with Z suffix
            if timestamp_str.endswith("Z"):
                timestamp_str = timestamp_str[:-1] + "+00:00"
            return datetime.fromisoformat(timestamp_str)
        except ValueError:
            return datetime.now()

    def _extract_title(self, turns: list[Turn]) -> str | None:
        """Extract a title from the first user message.

        Args:
            turns: List of turns.

        Returns:
            First 100 chars of the first user message, or None.
        """
        for turn in turns:
            for message in turn.messages:
                if message.role == "user":
                    for part in message.parts:
                        if isinstance(part, TextPart) and part.content:
                            # Truncate to reasonable title length
                            title = part.content[:100]
                            if len(part.content) > 100:
                                title += "..."
                            return title
        return None

    def _calculate_stats(self, turns: list[Turn]) -> SessionStats:
        """Calculate aggregate statistics for the session.

        Args:
            turns: List of turns.

        Returns:
            SessionStats with aggregated counts.
        """
        message_count = 0
        input_tokens = 0
        output_tokens = 0
        tool_call_count = 0
        files_modified: set[str] = set()

        for turn in turns:
            message_count += len(turn.messages)
            for message in turn.messages:
                if message.usage:
                    input_tokens += message.usage.input_tokens
                    output_tokens += message.usage.output_tokens

                for part in message.parts:
                    if isinstance(part, ToolCallPart):
                        tool_call_count += 1
                        # Track file modifications from Edit/Write tools
                        if part.tool_name in ("Edit", "Write", "edit", "write"):
                            if isinstance(part.input, dict):
                                file_path = part.input.get("filePath") or part.input.get(
                                    "file_path"
                                )
                                if file_path:
                                    files_modified.add(file_path)

        return SessionStats(
            turn_count=len(turns),
            message_count=message_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_call_count=tool_call_count,
            files_modified=sorted(files_modified),
        )

    def _aggregate_model_usage(self, turns: list[Turn]) -> list[ModelUsage]:
        """Aggregate token usage by model.

        Args:
            turns: List of turns.

        Returns:
            List of ModelUsage objects.
        """
        usage_by_model: dict[str, ModelUsage] = {}

        for turn in turns:
            for message in turn.messages:
                if message.model and message.usage:
                    model_id = message.model

                    if model_id not in usage_by_model:
                        # Extract provider from model ID if possible
                        provider = "anthropic"  # Default for Claude
                        if "/" in model_id:
                            provider = model_id.split("/")[0]

                        usage_by_model[model_id] = ModelUsage(
                            model_id=model_id,
                            provider=provider,
                            message_count=0,
                            input_tokens=0,
                            output_tokens=0,
                        )

                    usage = usage_by_model[model_id]
                    usage.message_count += 1
                    usage.input_tokens += message.usage.input_tokens
                    usage.output_tokens += message.usage.output_tokens

        return list(usage_by_model.values())
