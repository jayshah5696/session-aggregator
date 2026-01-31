"""Ampcode session adapter.

This module provides an adapter for reading session data from Ampcode (Amp),
Sourcegraph's AI coding agent.

Unlike other tools that store sessions locally, Amp uses a cloud-first architecture:
- Sessions are stored on ampcode.com servers
- Access via `amp --execute --stream-json` CLI or the `amp-sdk` Python package
- No local session files to read directly

This adapter reads captured JSONL files from a local cache directory.
Users can capture sessions by running:
    amp --execute "prompt" --stream-json > ~/.sagg/cache/ampcode/session.jsonl

Ampcode storage locations:
    ~/.local/share/amp/secrets.json    - CLI credentials
    ~/.config/amp/settings.json        - Configuration
    ~/Library/Application Support/Code/User/globalStorage/sourcegraph.amp/  - VS Code cache (macOS)
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
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

# Default cache directory for captured Amp sessions
DEFAULT_CACHE_DIR = Path.home() / ".sagg" / "cache" / "ampcode"

# Amp credentials location
AMP_SECRETS_PATH = Path.home() / ".local" / "share" / "amp" / "secrets.json"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load JSONL from a file, returning empty list on error."""
    if not path.exists():
        return []
    try:
        lines = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(json.loads(line))
        return lines
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load %s: %s", path, e)
        return []


def _get_file_mtime(path: Path) -> datetime:
    """Get file modification time as timezone-aware datetime."""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


class AmpcodeAdapter(SessionAdapter):
    """Adapter for Ampcode session data.

    This adapter reads captured JSONL files from a local cache directory.
    Since Amp stores sessions in the cloud, users must capture sessions
    by redirecting `amp --execute --stream-json` output to files.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        """Initialize the Ampcode adapter.

        Args:
            base_path: Optional custom path to Ampcode cache directory.
                      Defaults to ~/.sagg/cache/ampcode/.
        """
        self._base_path = base_path or self.get_default_path()

    @property
    def name(self) -> str:
        """Adapter identifier."""
        return "ampcode"

    @property
    def display_name(self) -> str:
        """Human-readable name."""
        return "Ampcode"

    def get_default_path(self) -> Path:
        """Get default path for Ampcode cache."""
        return DEFAULT_CACHE_DIR

    def is_available(self) -> bool:
        """Check if Ampcode is available on this system.

        Returns True if:
        - The amp CLI is installed, OR
        - The Amp secrets file exists, OR
        - The cache directory exists with session files
        """
        # Check for amp CLI
        if shutil.which("amp") is not None:
            return True

        # Check for Amp credentials
        if AMP_SECRETS_PATH.exists():
            return True

        # Check for cached sessions
        if self._base_path.exists() and any(self._base_path.glob("*.jsonl")):
            return True

        return False

    def list_sessions(self, since: datetime | None = None) -> list[SessionRef]:
        """List all session references from the cache directory.

        Args:
            since: Optional datetime to filter sessions updated after this time.

        Returns:
            List of SessionRef objects for available sessions.
            Returns empty list if no cache exists.
        """
        sessions: list[SessionRef] = []

        if not self._base_path.exists():
            logger.debug(
                "Ampcode cache directory does not exist: %s. "
                "Capture sessions using: amp --execute 'prompt' --stream-json > %s/session.jsonl",
                self._base_path,
                self._base_path,
            )
            return sessions

        # Find all JSONL files in the cache directory
        for session_file in self._base_path.glob("*.jsonl"):
            try:
                # Parse the file to extract session metadata
                messages = _load_jsonl(session_file)
                if not messages:
                    continue

                # Extract session ID from init message or filename
                session_id = self._extract_session_id(messages, session_file)

                # Use file modification time as the primary timestamp
                updated_at = _get_file_mtime(session_file)

                # Try to get created_at from init message, fallback to mtime
                created_at = self._extract_created_at(messages) or updated_at

                # Filter by since if provided
                if since is not None and updated_at <= since:
                    continue

                sessions.append(
                    SessionRef(
                        id=session_id,
                        path=session_file,
                        created_at=created_at,
                        updated_at=updated_at,
                    )
                )
            except OSError as e:
                logger.warning("Failed to process session file %s: %s", session_file, e)
                continue

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
        messages = _load_jsonl(ref.path)
        if not messages:
            raise ValueError(f"Failed to load session: {ref.path}")

        # Parse stream JSON messages
        init_data = self._find_init_message(messages)
        result_data = self._find_result_message(messages)

        # Extract metadata
        session_id = self._extract_session_id(messages, ref.path)
        cwd = init_data.get("cwd") if init_data else None

        # Build turns from messages
        turns = self._build_turns(messages)

        # Compute stats
        stats = self._compute_stats(turns, result_data)

        # Aggregate model usage (Amp doesn't provide per-message model info)
        models = self._aggregate_model_usage(messages, result_data)

        # Calculate duration from result message
        duration_ms = result_data.get("duration_ms") if result_data else None

        # Generate title from first user message
        title = self._generate_title(turns)

        return UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.AMPCODE,
            source_id=session_id,
            source_path=str(ref.path),
            title=title,
            project_path=cwd,
            project_name=extract_project_name(cwd) if cwd else None,
            created_at=ref.created_at,
            updated_at=ref.updated_at,
            duration_ms=duration_ms,
            stats=stats,
            models=models,
            turns=turns,
        )

    def _extract_session_id(self, messages: list[dict[str, Any]], path: Path) -> str:
        """Extract session ID from messages or generate from filename.

        Amp session IDs have format: T-{uuid}
        """
        # Try to find session_id in any message
        for msg in messages:
            session_id = msg.get("session_id")
            if session_id:
                return session_id

        # Fallback to filename
        return path.stem

    def _extract_created_at(self, messages: list[dict[str, Any]]) -> datetime | None:
        """Try to extract creation timestamp from messages.

        Amp stream JSON doesn't include timestamps per message,
        so we return None and let the caller use file mtime.
        """
        # Amp doesn't provide per-message timestamps
        return None

    def _find_init_message(self, messages: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Find the system init message."""
        for msg in messages:
            if msg.get("type") == "system" and msg.get("subtype") == "init":
                return msg
        return None

    def _find_result_message(self, messages: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Find the result message (success or error)."""
        for msg in messages:
            if msg.get("type") == "result":
                return msg
        return None

    def _build_turns(self, messages: list[dict[str, Any]]) -> list[Turn]:
        """Build conversation turns from stream JSON messages.

        A turn starts with a user message and includes all subsequent
        assistant messages until the next user message.
        """
        turns: list[Turn] = []
        current_turn_messages: list[Message] = []
        turn_index = 0

        # Track message order for generating timestamps
        msg_counter = 0

        for msg in messages:
            msg_type = msg.get("type")

            # Skip system and result messages for turn building
            if msg_type in ("system", "result"):
                continue

            if msg_type == "user":
                # Start a new turn if we have accumulated messages
                if current_turn_messages:
                    turn = self._finalize_turn(current_turn_messages, turn_index)
                    turns.append(turn)
                    turn_index += 1
                    current_turn_messages = []

                unified_msg = self._convert_user_message(msg, msg_counter)
                current_turn_messages.append(unified_msg)
                msg_counter += 1

            elif msg_type == "assistant":
                unified_msg = self._convert_assistant_message(msg, msg_counter)
                current_turn_messages.append(unified_msg)
                msg_counter += 1

        # Finalize last turn
        if current_turn_messages:
            turn = self._finalize_turn(current_turn_messages, turn_index)
            turns.append(turn)

        return turns

    def _finalize_turn(self, messages: list[Message], index: int) -> Turn:
        """Create a Turn from accumulated messages."""
        started_at = messages[0].timestamp
        ended_at = messages[-1].timestamp if len(messages) > 1 else None

        return Turn(
            id=f"turn_{index}",
            index=index,
            started_at=started_at,
            ended_at=ended_at,
            messages=messages,
        )

    def _convert_user_message(self, msg: dict[str, Any], order: int) -> Message:
        """Convert an Amp user message to unified format.

        User messages contain tool results in Amp's format.
        """
        msg_id = f"msg_{order}"
        # Use current time since Amp doesn't provide per-message timestamps
        timestamp = datetime.now(tz=UTC)

        parts: list[Part] = []

        # Parse message content (tool results)
        message_data = msg.get("message", {})
        content = message_data.get("content", [])

        for item in content:
            if isinstance(item, dict):
                # Tool result format: {"type": "tool_result", "tool_use_id": ..., "content": ...}
                if item.get("type") == "tool_result":
                    tool_id = item.get("tool_use_id", "unknown")
                    result_content = item.get("content", "")
                    is_error = item.get("is_error", False)

                    # Handle content that might be a list of text blocks
                    if isinstance(result_content, list):
                        result_content = "\n".join(
                            c.get("text", str(c)) if isinstance(c, dict) else str(c)
                            for c in result_content
                        )

                    parts.append(
                        ToolResultPart(
                            tool_id=tool_id,
                            output=str(result_content),
                            is_error=is_error,
                        )
                    )
            elif isinstance(item, str):
                parts.append(TextPart(content=item))

        return Message(
            id=msg_id,
            role="user",
            timestamp=timestamp,
            model=None,
            parts=parts,
            usage=None,
        )

    def _convert_assistant_message(self, msg: dict[str, Any], order: int) -> Message:
        """Convert an Amp assistant message to unified format."""
        msg_id = f"msg_{order}"
        timestamp = datetime.now(tz=UTC)

        parts: list[Part] = []
        usage = None

        message_data = msg.get("message", {})
        content = message_data.get("content", [])

        # Parse content blocks
        for block in content:
            if not isinstance(block, dict):
                continue

            block_type = block.get("type")

            if block_type == "text":
                text = block.get("text", "")
                if text:
                    parts.append(TextPart(content=text))

            elif block_type == "tool_use":
                tool_name = block.get("name", "unknown")
                tool_id = block.get("id", "unknown")
                tool_input = block.get("input", {})

                parts.append(
                    ToolCallPart(
                        tool_name=tool_name,
                        tool_id=tool_id,
                        input=tool_input,
                    )
                )

            elif block_type == "thinking":
                thinking = block.get("thinking", "")
                if thinking:
                    parts.append(TextPart(content=f"[thinking] {thinking}"))

        # Extract usage info
        usage_data = message_data.get("usage")
        if usage_data:
            usage = TokenUsage(
                input_tokens=usage_data.get("input_tokens", 0),
                output_tokens=usage_data.get("output_tokens", 0),
                cached_tokens=usage_data.get("cache_read_input_tokens"),
            )

        return Message(
            id=msg_id,
            role="assistant",
            timestamp=timestamp,
            model=None,  # Amp doesn't include model info per message
            parts=parts,
            usage=usage,
        )

    def _compute_stats(self, turns: list[Turn], result_data: dict[str, Any] | None) -> SessionStats:
        """Compute session statistics."""
        message_count = sum(len(turn.messages) for turn in turns)
        tool_call_count = 0
        input_tokens = 0
        output_tokens = 0

        for turn in turns:
            for message in turn.messages:
                if message.usage is not None:
                    input_tokens += message.usage.input_tokens
                    output_tokens += message.usage.output_tokens

                for part in message.parts:
                    if isinstance(part, ToolCallPart):
                        tool_call_count += 1

        # Supplement with result usage if available
        if result_data:
            result_usage = result_data.get("usage", {})
            if result_usage:
                # Use result totals if per-message totals are missing
                if input_tokens == 0:
                    input_tokens = result_usage.get("input_tokens", 0)
                if output_tokens == 0:
                    output_tokens = result_usage.get("output_tokens", 0)

        return SessionStats(
            turn_count=len(turns),
            message_count=message_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_call_count=tool_call_count,
            files_modified=[],  # Would need to parse tool outputs to extract
        )

    def _aggregate_model_usage(
        self, messages: list[dict[str, Any]], result_data: dict[str, Any] | None
    ) -> list[ModelUsage]:
        """Aggregate model usage statistics.

        Amp doesn't include model info per message, so we aggregate from result.
        """
        usage_by_model: dict[str, ModelUsage] = {}

        # Count assistant messages and aggregate usage
        message_count = 0
        total_input = 0
        total_output = 0

        for msg in messages:
            if msg.get("type") == "assistant":
                message_count += 1
                message_data = msg.get("message", {})
                usage_data = message_data.get("usage", {})
                if usage_data:
                    total_input += usage_data.get("input_tokens", 0)
                    total_output += usage_data.get("output_tokens", 0)

        # Use result usage as authoritative source
        if result_data:
            result_usage = result_data.get("usage", {})
            if result_usage:
                total_input = result_usage.get("input_tokens", total_input)
                total_output = result_usage.get("output_tokens", total_output)

        if message_count > 0:
            # Amp uses Anthropic models by default
            model_id = "anthropic/claude-sonnet-4"
            usage_by_model[model_id] = ModelUsage(
                model_id=model_id,
                provider="anthropic",
                message_count=message_count,
                input_tokens=total_input,
                output_tokens=total_output,
            )

        return list(usage_by_model.values())

    def _generate_title(self, turns: list[Turn]) -> str | None:
        """Generate a title from the first user message."""
        for turn in turns:
            for message in turn.messages:
                if message.role == "user":
                    for part in message.parts:
                        if isinstance(part, TextPart):
                            # Truncate to first 100 chars
                            title = part.content[:100]
                            if len(part.content) > 100:
                                title += "..."
                            return title
        return None
