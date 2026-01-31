"""OpenCode session adapter.

This module provides an adapter for reading session data from OpenCode,
an AI-powered coding assistant.

OpenCode storage structure (~/.local/share/opencode/storage/):
    project/<hash>.json          - Project metadata
    session/<project-hash>/ses_*.json   - Session files
    message/<session-id>/msg_*.json     - Messages
    part/<message-id>/prt_*.json        - Parts
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


def _ms_to_datetime(ms: int) -> datetime:
    """Convert milliseconds since epoch to timezone-aware datetime (UTC)."""
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def _load_json(path: Path) -> dict[str, Any] | None:
    """Load JSON from a file, returning None on error."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load %s: %s", path, e)
        return None


class OpenCodeAdapter(SessionAdapter):
    """Adapter for OpenCode session data."""

    def __init__(self, base_path: Path | None = None) -> None:
        """Initialize the OpenCode adapter.

        Args:
            base_path: Optional custom path to OpenCode storage.
                      Defaults to ~/.local/share/opencode/storage.
        """
        self._base_path = base_path or self.get_default_path()

    @property
    def name(self) -> str:
        """Adapter identifier."""
        return "opencode"

    @property
    def display_name(self) -> str:
        """Human-readable name."""
        return "OpenCode"

    def get_default_path(self) -> Path:
        """Get default path for OpenCode storage."""
        return Path.home() / ".local" / "share" / "opencode" / "storage"

    def is_available(self) -> bool:
        """Check if OpenCode storage exists on this system."""
        return self._base_path.exists() and self._base_path.is_dir()

    def list_sessions(self, since: datetime | None = None) -> list[SessionRef]:
        """List all session references.

        Args:
            since: Optional datetime to filter sessions updated after this time.

        Returns:
            List of SessionRef objects for available sessions.
        """
        sessions: list[SessionRef] = []
        session_base = self._base_path / "session"

        if not session_base.exists():
            return sessions

        # Iterate over project hash directories
        for project_dir in session_base.iterdir():
            if not project_dir.is_dir():
                continue

            # Find all session files in this project directory
            for session_file in project_dir.glob("ses_*.json"):
                session_data = _load_json(session_file)
                if session_data is None:
                    continue

                time_data = session_data.get("time", {})
                created_ms = time_data.get("created")
                updated_ms = time_data.get("updated")

                if created_ms is None or updated_ms is None:
                    logger.warning("Session %s missing time data", session_file)
                    continue

                created_at = _ms_to_datetime(created_ms)
                updated_at = _ms_to_datetime(updated_ms)

                # Filter by since if provided
                if since is not None and updated_at <= since:
                    continue

                session_id = session_data.get("id", session_file.stem)
                sessions.append(
                    SessionRef(
                        id=session_id,
                        path=session_file,
                        created_at=created_at,
                        updated_at=updated_at,
                    )
                )

        # Sort by created_at descending (newest first)
        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions

    def parse_session(self, ref: SessionRef) -> UnifiedSession:
        """Parse a session into unified format.

        Args:
            ref: Session reference from list_sessions().

        Returns:
            UnifiedSession containing parsed session data.

        Raises:
            ValueError: If session data is invalid or missing.
        """
        session_data = _load_json(ref.path)
        if session_data is None:
            raise ValueError(f"Failed to load session: {ref.path}")

        session_id = session_data.get("id", ref.id)
        project_path = session_data.get("directory")
        title = session_data.get("title")

        # Load messages for this session
        messages = self._load_messages(session_id)

        # Convert messages to turns
        turns = self._build_turns(messages)

        # Aggregate stats
        stats = self._compute_stats(turns, session_data)

        # Aggregate model usage
        models = self._aggregate_model_usage(messages)

        # Calculate duration
        duration_ms = None
        time_data = session_data.get("time", {})
        if "created" in time_data and "updated" in time_data:
            duration_ms = time_data["updated"] - time_data["created"]

        return UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.OPENCODE,
            source_id=session_id,
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

    def _load_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Load all messages for a session.

        Args:
            session_id: The OpenCode session ID (e.g., ses_...).

        Returns:
            List of message dictionaries sorted by creation time.
        """
        message_dir = self._base_path / "message" / session_id
        if not message_dir.exists():
            return []

        messages: list[dict[str, Any]] = []
        for msg_file in message_dir.glob("msg_*.json"):
            msg_data = _load_json(msg_file)
            if msg_data is None:
                continue

            # Load parts for this message
            msg_id = msg_data.get("id", msg_file.stem)
            parts = self._load_parts(msg_id)
            msg_data["_parts"] = parts

            messages.append(msg_data)

        # Sort by creation time
        messages.sort(key=lambda m: m.get("time", {}).get("created", 0))
        return messages

    def _load_parts(self, message_id: str) -> list[dict[str, Any]]:
        """Load all parts for a message.

        Args:
            message_id: The OpenCode message ID (e.g., msg_...).

        Returns:
            List of part dictionaries.
        """
        parts_dir = self._base_path / "part" / message_id
        if not parts_dir.exists():
            return []

        parts: list[dict[str, Any]] = []
        for part_file in parts_dir.glob("prt_*.json"):
            part_data = _load_json(part_file)
            if part_data is not None:
                parts.append(part_data)

        return parts

    def _build_turns(self, messages: list[dict[str, Any]]) -> list[Turn]:
        """Build conversation turns from messages.

        A turn starts with a user message and includes all subsequent
        assistant messages until the next user message.

        Args:
            messages: List of message dictionaries.

        Returns:
            List of Turn objects.
        """
        turns: list[Turn] = []
        current_turn_messages: list[Message] = []
        turn_index = 0

        for msg_data in messages:
            role = msg_data.get("role", "user")
            unified_msg = self._convert_message(msg_data)

            # Start a new turn on user message (if we have accumulated messages)
            if role == "user" and current_turn_messages:
                turn = self._finalize_turn(current_turn_messages, turn_index)
                turns.append(turn)
                turn_index += 1
                current_turn_messages = []

            current_turn_messages.append(unified_msg)

        # Finalize last turn
        if current_turn_messages:
            turn = self._finalize_turn(current_turn_messages, turn_index)
            turns.append(turn)

        return turns

    def _finalize_turn(self, messages: list[Message], index: int) -> Turn:
        """Create a Turn from accumulated messages.

        Args:
            messages: List of messages in this turn.
            index: Turn index (0-based).

        Returns:
            Turn object.
        """
        started_at = messages[0].timestamp
        ended_at = messages[-1].timestamp if len(messages) > 1 else None

        return Turn(
            id=f"turn_{index}",
            index=index,
            started_at=started_at,
            ended_at=ended_at,
            messages=messages,
        )

    def _convert_message(self, msg_data: dict[str, Any]) -> Message:
        """Convert an OpenCode message to unified format.

        Args:
            msg_data: OpenCode message dictionary.

        Returns:
            Unified Message object.
        """
        msg_id = msg_data.get("id", "unknown")
        role = msg_data.get("role", "user")
        time_data = msg_data.get("time", {})
        created_ms = time_data.get("created", 0)
        timestamp = _ms_to_datetime(created_ms)

        # Extract model info - OpenCode stores these at root level, not nested
        provider_id = msg_data.get("providerID", "")
        model_id = msg_data.get("modelID", "")
        model = f"{provider_id}/{model_id}" if provider_id and model_id else None

        # Extract token usage from the tokens field
        usage = None
        tokens_data = msg_data.get("tokens")
        if tokens_data is not None:
            cache_data = tokens_data.get("cache", {})
            usage = TokenUsage(
                input_tokens=tokens_data.get("input", 0),
                output_tokens=tokens_data.get("output", 0),
                cached_tokens=cache_data.get("read"),
            )

        # Convert parts
        parts = self._convert_parts(msg_data.get("_parts", []))

        return Message(
            id=msg_id,
            role=role,
            timestamp=timestamp,
            model=model,
            parts=parts,
            usage=usage,
        )

    def _convert_parts(self, raw_parts: list[dict[str, Any]]) -> list[Part]:
        """Convert OpenCode parts to unified format.

        Args:
            raw_parts: List of OpenCode part dictionaries.

        Returns:
            List of unified Part objects.
        """
        parts: list[Part] = []

        for part in raw_parts:
            part_type = part.get("type")

            if part_type == "text":
                text_content = part.get("text", "")
                if text_content:
                    parts.append(TextPart(content=text_content))

            elif part_type == "tool":
                tool_name = part.get("tool", "unknown")
                call_id = part.get("callID", part.get("id", "unknown"))
                state = part.get("state", {})
                tool_input = state.get("input")
                tool_output = state.get("output")
                status = state.get("status", "unknown")

                # Add tool call part
                parts.append(
                    ToolCallPart(
                        tool_name=tool_name,
                        tool_id=call_id,
                        input=tool_input,
                    )
                )

                # Add tool result part if output exists
                if tool_output is not None:
                    is_error = status == "error"
                    output_str = (
                        tool_output if isinstance(tool_output, str) else json.dumps(tool_output)
                    )
                    parts.append(
                        ToolResultPart(
                            tool_id=call_id,
                            output=output_str,
                            is_error=is_error,
                        )
                    )

        return parts

    def _compute_stats(self, turns: list[Turn], session_data: dict[str, Any]) -> SessionStats:
        """Compute session statistics.

        Args:
            turns: List of turns in the session.
            session_data: Raw session data dictionary.

        Returns:
            SessionStats object.
        """
        message_count = sum(len(turn.messages) for turn in turns)
        tool_call_count = 0
        input_tokens = 0
        output_tokens = 0
        files_modified: list[str] = []

        for turn in turns:
            for message in turn.messages:
                # Sum token usage from messages
                if message.usage is not None:
                    input_tokens += message.usage.input_tokens
                    output_tokens += message.usage.output_tokens

                for part in message.parts:
                    if isinstance(part, ToolCallPart):
                        tool_call_count += 1

        # Extract file stats from session summary if available
        summary = session_data.get("summary", {})
        file_count = summary.get("files", 0)
        if file_count > 0:
            # OpenCode doesn't provide file paths in summary,
            # we could parse tool outputs but keep it simple for now
            pass

        return SessionStats(
            turn_count=len(turns),
            message_count=message_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_call_count=tool_call_count,
            files_modified=files_modified,
        )

    def _aggregate_model_usage(self, messages: list[dict[str, Any]]) -> list[ModelUsage]:
        """Aggregate model usage statistics from messages.

        Args:
            messages: List of message dictionaries.

        Returns:
            List of ModelUsage objects, one per model used.
        """
        usage_by_model: dict[str, ModelUsage] = {}

        for msg in messages:
            # OpenCode stores model info at root level, not nested
            provider_id = msg.get("providerID")
            model_id = msg.get("modelID")

            if not provider_id or not model_id:
                continue

            full_model_id = f"{provider_id}/{model_id}"

            if full_model_id not in usage_by_model:
                usage_by_model[full_model_id] = ModelUsage(
                    model_id=full_model_id,
                    provider=provider_id,
                    message_count=0,
                    input_tokens=0,
                    output_tokens=0,
                )

            usage_by_model[full_model_id].message_count += 1

            # Extract token counts from the tokens field
            tokens_data = msg.get("tokens")
            if tokens_data is not None:
                usage_by_model[full_model_id].input_tokens += tokens_data.get("input", 0)
                usage_by_model[full_model_id].output_tokens += tokens_data.get("output", 0)

        return list(usage_by_model.values())
