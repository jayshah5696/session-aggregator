"""Pi Coding Agent session adapter.

Parses sessions from Pi Coding Agent's JSONL format stored in ~/.pi/agent/sessions/.

Structure details derived from:
- https://medium.com/@shivam.agarwal.in/agentic-ai-pi-anatomy-of-a-minimal-coding-agent-powering-openclaw-5ecd4dd6b440
- https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/session.md

Key observations:
- Sessions are stored in `~/.pi/agent/sessions/`.
- Paths are encoded as `--<path>--` (replacing / with -).
- Files are JSONL.
- Messages form a tree structure (id/parentId), but we flatten them chronologically.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sagg.adapters.base import SessionAdapter, SessionRef
from sagg.models import (
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

logger = logging.getLogger(__name__)


def decode_pi_path(encoded: str) -> str:
    """Decode a Pi encoded project path.

    Pi seems to encode paths similar to Claude but with potential variations.
    Example: '--Users-foo-code-myapp' -> '/Users/foo/code/myapp'
    """
    if not encoded:
        return ""

    # Remove potential double dash prefix/suffix if present
    # The snippet showed --<path>-- so we handle that
    clean = encoded
    if clean.startswith("--"):
        clean = clean[2:]
    elif clean.startswith("-"):
        clean = clean[1:]

    if clean.endswith("--"):
        clean = clean[:-2]

    # Replace dashes with slashes
    decoded = clean.replace("-", "/")

    # Ensure it starts with /
    if not decoded.startswith("/"):
        decoded = "/" + decoded

    return decoded


class PiAdapter(SessionAdapter):
    """Adapter for Pi Coding Agent session files."""

    @property
    def name(self) -> str:
        """Adapter identifier."""
        return "pi"

    @property
    def display_name(self) -> str:
        """Human-readable name."""
        return "Pi Coding Agent"

    def get_default_path(self) -> Path:
        """Get default path for Pi sessions."""
        return Path.home() / ".pi" / "agent" / "sessions"

    def is_available(self) -> bool:
        """Check if Pi sessions directory exists."""
        return self.get_default_path().exists()

    def list_sessions(self, since: datetime | None = None) -> list[SessionRef]:
        """List all Pi session files.

        Args:
            since: Optional datetime to filter sessions updated after this time.

        Returns:
            List of SessionRef objects for each session file found.
        """
        sessions: list[SessionRef] = []
        base_path = self.get_default_path()

        if not base_path.exists():
            return sessions

        # Recursively search for JSONL files
        for path in base_path.rglob("*.jsonl"):
            if not path.is_file():
                continue

            # Get file timestamps (timezone-aware)
            try:
                stat = path.stat()
                created_at = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc)
                updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            except OSError:
                continue

            # Filter by since if provided
            if since is not None and updated_at <= since:
                continue

            # Session ID is the filename without extension or parent dir name if filename is generic
            session_id = path.stem

            # If filename is a timestamp (e.g. 2023-10-27T...), use it as ID,
            # or combine with parent dir name for uniqueness
            if path.parent.name.startswith("--") and session_id.replace("-", "").replace(":", "").isdigit():
                 # Using parent name + timestamp as ID might be too long, sticking to filename as ID
                 # But ensure uniqueness if multiple projects have same timestamp
                 pass

            sessions.append(
                SessionRef(
                    id=session_id,
                    path=path,
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )

        return sessions

    def parse_session(self, ref: SessionRef) -> UnifiedSession:
        """Parse a Pi session file into UnifiedSession format.

        Args:
            ref: SessionRef pointing to the session file.

        Returns:
            UnifiedSession with parsed content.
        """
        entries = self._read_jsonl(ref.path)

        # Build turns from entries, handling tree structure if needed
        turns = self._build_turns(entries)

        # Calculate stats
        stats = self._calculate_stats(turns)

        # Aggregate model usage
        models = self._aggregate_model_usage(turns)

        # Determine project path from parent directory
        project_path = None
        parent_name = ref.path.parent.name
        if parent_name.startswith("--") or parent_name.startswith("-"):
             project_path = decode_pi_path(parent_name)

        # Extract title from first user message
        title = self._extract_title(turns)

        # Duration
        duration_ms: int | None = None
        if turns:
            first_msg = turns[0].started_at
            last_msg = turns[-1].ended_at or turns[-1].started_at
            duration_ms = int((last_msg - first_msg).total_seconds() * 1000)

        return UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.PI,
            source_id=ref.id,
            source_path=str(ref.path),
            title=title,
            project_path=project_path,
            project_name=extract_project_name(project_path) if project_path else None,
            created_at=ref.created_at,
            updated_at=ref.updated_at,
            duration_ms=duration_ms,
            stats=stats,
            models=models,
            turns=turns,
        )

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        """Read and parse a JSONL file."""
        entries: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError as e:
            logger.warning("Failed to read %s: %s", path, e)
            return []
        return entries

    def _build_turns(self, entries: list[dict[str, Any]]) -> list[Turn]:
        """Build turns from JSONL entries.

        If entries form a tree (id/parentId), this attempts to flatten it
        by taking the longest path or just chronological order if simpler.
        """
        # Sort by timestamp if available
        sorted_entries = sorted(entries, key=lambda x: x.get("timestamp", ""))

        turns: list[Turn] = []
        current_turn_messages: list[Message] = []
        current_turn_id: str | None = None
        current_turn_start: datetime | None = None

        for entry in sorted_entries:
            # Skip entries that don't look like messages (e.g. metadata)
            if "role" not in entry and "message" not in entry:
                # Try to infer role/content if missing
                if "content" in entry:
                    # Assume user if not specified
                    entry["role"] = "user"
                else:
                    continue

            timestamp = self._parse_timestamp(entry.get("timestamp", ""))
            message = self._parse_message(entry, timestamp)
            if message is None:
                continue

            # User messages start new turns
            if message.role == "user":
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

                current_turn_messages = [message]
                current_turn_id = entry.get("id")
                current_turn_start = timestamp
            else:
                current_turn_messages.append(message)

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
        """Parse a single entry into a Message."""
        # Check if entry wraps a message object (like Claude) or is flat
        data = entry.get("message", entry)

        role = data.get("role", "user")
        if role not in ("user", "assistant", "system", "tool"):
            role = "user"  # Default fallback

        # Content parsing
        content = data.get("content", "")
        parts = []

        if isinstance(content, str):
            if content:
                parts.append(TextPart(content=content))
        elif isinstance(content, list):
            # Handle list of blocks if structured
            for block in content:
                if isinstance(block, str):
                    parts.append(TextPart(content=block))
                elif isinstance(block, dict):
                    if "text" in block:
                        parts.append(TextPart(content=block["text"]))
                    elif "tool" in block or "tool_use" in block.get("type", ""):
                         # Attempt to parse tool call
                         parts.append(ToolCallPart(
                             tool_name=block.get("name", "unknown"),
                             tool_id=block.get("id", ""),
                             input=block.get("input")
                         ))

        # Handle tool calls if separate field
        if "tool_calls" in data:
            for tc in data["tool_calls"]:
                parts.append(ToolCallPart(
                    tool_name=tc.get("function", {}).get("name", "unknown"),
                    tool_id=tc.get("id", ""),
                    input=tc.get("function", {}).get("arguments")
                ))

        if not parts:
            # If no content found, skip empty message unless it's a tool call
            if not any(isinstance(p, ToolCallPart) for p in parts):
                 return None

        # Model info
        model = data.get("model")

        # Usage info
        usage = None
        if "usage" in data:
            usage_data = data["usage"]
            usage = TokenUsage(
                input_tokens=usage_data.get("input_tokens", 0) or usage_data.get("prompt_tokens", 0),
                output_tokens=usage_data.get("output_tokens", 0) or usage_data.get("completion_tokens", 0),
            )

        return Message(
            id=entry.get("id", generate_session_id()),
            role=role,
            timestamp=timestamp,
            model=model,
            parts=parts,
            usage=usage,
        )

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse ISO timestamp or return current time."""
        if not timestamp_str:
            return datetime.now(timezone.utc)

        try:
            if timestamp_str.endswith("Z"):
                timestamp_str = timestamp_str[:-1] + "+00:00"
            return datetime.fromisoformat(timestamp_str)
        except ValueError:
            return datetime.now(timezone.utc)

    def _extract_title(self, turns: list[Turn]) -> str | None:
        """Extract title from first user message."""
        for turn in turns:
            for message in turn.messages:
                if message.role == "user":
                    for part in message.parts:
                        if isinstance(part, TextPart) and part.content:
                            title = part.content[:100]
                            if len(part.content) > 100:
                                title += "..."
                            return title
        return None

    def _calculate_stats(self, turns: list[Turn]) -> SessionStats:
        """Calculate session stats."""
        message_count = 0
        input_tokens = 0
        output_tokens = 0
        tool_call_count = 0

        for turn in turns:
            message_count += len(turn.messages)
            for message in turn.messages:
                if message.usage:
                    input_tokens += message.usage.input_tokens
                    output_tokens += message.usage.output_tokens

                for part in message.parts:
                    if isinstance(part, ToolCallPart):
                        tool_call_count += 1

        return SessionStats(
            turn_count=len(turns),
            message_count=message_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_call_count=tool_call_count,
        )

    def _aggregate_model_usage(self, turns: list[Turn]) -> list[ModelUsage]:
        """Aggregate model usage."""
        usage_by_model: dict[str, ModelUsage] = {}

        for turn in turns:
            for message in turn.messages:
                if message.model:
                    model_id = message.model
                    if model_id not in usage_by_model:
                        provider = "pi"
                        if "/" in model_id:
                            provider = model_id.split("/")[0]

                        usage_by_model[model_id] = ModelUsage(
                            model_id=model_id,
                            provider=provider,
                        )

                    if message.usage:
                        usage_by_model[model_id].message_count += 1
                        usage_by_model[model_id].input_tokens += message.usage.input_tokens
                        usage_by_model[model_id].output_tokens += message.usage.output_tokens

        return list(usage_by_model.values())
