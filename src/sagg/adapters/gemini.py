"""Gemini CLI session adapter.

Parses Gemini CLI sessions stored in ~/.gemini/tmp/<project_hash>/chats/session-*.json.
Sessions are JSON files written by Gemini CLI's chat recording service.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
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

SESSION_FILE_PREFIX = "session-"


def _get_gemini_home() -> Path:
    """Return Gemini CLI home base, respecting GEMINI_CLI_HOME override."""
    env_home = os.environ.get("GEMINI_CLI_HOME")
    if env_home:
        return Path(env_home).expanduser()
    return Path.home()


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO timestamp string into a timezone-aware datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_json(path: Path) -> dict[str, Any] | None:
    """Load JSON from a file, returning None on error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read Gemini session %s: %s", path, exc)
        return None


def _has_user_or_assistant(messages: list[dict[str, Any]]) -> bool:
    """Return True if messages include user or assistant content."""
    return any(msg.get("type") in {"user", "gemini"} for msg in messages)


def _part_to_string(value: Any) -> str:
    """Convert Gemini PartListUnion-like content to string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_part_to_string(item) for item in value)
    if isinstance(value, dict):
        if "videoMetadata" in value:
            return "[Video Metadata]"
        if "thought" in value:
            return f"[Thought: {value.get('thought', '')}]"
        if "codeExecutionResult" in value:
            return "[Code Execution Result]"
        if "executableCode" in value:
            return "[Executable Code]"
        if "fileData" in value:
            return "[File Data]"
        if "functionCall" in value:
            name = value.get("functionCall", {}).get("name", "unknown")
            return f"[Function Call: {name}]"
        if "functionResponse" in value:
            name = value.get("functionResponse", {}).get("name", "unknown")
            return f"[Function Response: {name}]"
        if "inlineData" in value:
            mime = value.get("inlineData", {}).get("mimeType", "inline_data")
            return f"<{mime}>"
        text = value.get("text")
        if isinstance(text, str):
            return text
    return ""


def _safe_json(value: Any) -> str:
    """Safely stringify structured data for display."""
    try:
        return json.dumps(value, ensure_ascii=True)
    except TypeError:
        return str(value)


class GeminiCliAdapter(SessionAdapter):
    """Adapter for Gemini CLI session files."""

    def __init__(self, base_path: Path | None = None) -> None:
        """Initialize the adapter.

        Args:
            base_path: Optional base path to Gemini CLI temp dir.
                      Defaults to ~/.gemini/tmp (respecting GEMINI_CLI_HOME).
        """
        self._base_path = base_path or self.get_default_path()

    @property
    def name(self) -> str:
        """Adapter identifier."""
        return "gemini"

    @property
    def display_name(self) -> str:
        """Human-readable name."""
        return "Google Gemini CLI"

    def get_default_path(self) -> Path:
        """Get default path for Gemini CLI sessions."""
        return _get_gemini_home() / ".gemini" / "tmp"

    def is_available(self) -> bool:
        """Check if Gemini CLI data is available on this system."""
        # Check for gemini CLI binary
        if shutil.which("gemini") is not None:
            return True

        # Check for global settings or session data
        gemini_dir = self._base_path.parent
        if (gemini_dir / "settings.json").exists():
            return True

        # Check for session files
        if self._base_path.exists() and any(self._iter_session_files()):
            return True

        return False

    def list_sessions(self, since: datetime | None = None) -> list[SessionRef]:
        """List all Gemini CLI session files.

        Args:
            since: Optional datetime to filter sessions updated after this time.

        Returns:
            List of SessionRef objects for available sessions.
        """
        if not self._base_path.exists():
            return []

        sessions: dict[str, SessionRef] = {}

        for session_file in self._iter_session_files():
            data = _load_json(session_file)
            if not data:
                continue

            messages = data.get("messages")
            if not isinstance(messages, list) or not _has_user_or_assistant(messages):
                continue

            session_id = data.get("sessionId") or session_file.stem
            created_at = _parse_timestamp(data.get("startTime"))
            updated_at = _parse_timestamp(data.get("lastUpdated"))

            stat = session_file.stat()
            if created_at is None:
                created_at = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc)
            if updated_at is None:
                updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

            if since is not None and updated_at <= since:
                continue

            ref = SessionRef(
                id=session_id,
                path=session_file,
                created_at=created_at,
                updated_at=updated_at,
            )

            existing = sessions.get(session_id)
            if existing is None or ref.updated_at > existing.updated_at:
                sessions[session_id] = ref

        return sorted(sessions.values(), key=lambda r: r.created_at)

    def parse_session(self, ref: SessionRef) -> UnifiedSession:
        """Parse a Gemini CLI session into unified format."""
        data = _load_json(ref.path)
        if not data:
            raise ValueError(f"Failed to load Gemini session: {ref.path}")

        messages = data.get("messages")
        if not isinstance(messages, list):
            raise ValueError(f"Invalid Gemini session: {ref.path}")

        turns = self._build_turns(messages)
        stats = self._calculate_stats(turns)
        models = self._build_model_usage(turns)

        session_id = data.get("sessionId", ref.id)
        created_at = _parse_timestamp(data.get("startTime")) or ref.created_at
        updated_at = _parse_timestamp(data.get("lastUpdated")) or ref.updated_at

        duration_ms = None
        if created_at and updated_at:
            duration_ms = int((updated_at - created_at).total_seconds() * 1000)

        project_path = self._extract_project_path(data)
        title = self._extract_title(data, turns)

        return UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.GEMINI,
            source_id=session_id,
            source_path=str(ref.path),
            title=title,
            project_path=project_path,
            project_name=extract_project_name(project_path) if project_path else None,
            created_at=created_at,
            updated_at=updated_at,
            duration_ms=duration_ms,
            stats=stats,
            models=models,
            turns=turns,
        )

    def _iter_session_files(self) -> list[Path]:
        """Iterate over session files in the Gemini temp directory."""
        if not self._base_path.exists():
            return []
        pattern = f"*/chats/{SESSION_FILE_PREFIX}*.json"
        return list(self._base_path.glob(pattern))

    def _extract_project_path(self, data: dict[str, Any]) -> str | None:
        """Extract a project path from recorded directories."""
        directories = data.get("directories")
        if isinstance(directories, list):
            for item in directories:
                if isinstance(item, str) and item.strip():
                    return item
        return None

    def _build_turns(self, messages: list[dict[str, Any]]) -> list[Turn]:
        """Build conversation turns from Gemini message records."""
        turns: list[Turn] = []
        current_messages: list[Message] = []
        turn_index = 0

        for idx, record in enumerate(messages):
            message = self._convert_message(record, idx)
            if message is None:
                continue

            if message.role == "user":
                if current_messages:
                    turns.append(self._finalize_turn(current_messages, turn_index))
                    turn_index += 1
                    current_messages = []
                current_messages.append(message)
            else:
                if not current_messages:
                    current_messages = [message]
                else:
                    current_messages.append(message)

        if current_messages:
            turns.append(self._finalize_turn(current_messages, turn_index))

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

    def _convert_message(self, record: dict[str, Any], index: int) -> Message | None:
        """Convert a Gemini message record to unified Message."""
        msg_type = record.get("type")
        role_map = {
            "user": "user",
            "gemini": "assistant",
            "info": "system",
            "warning": "system",
            "error": "system",
        }
        role = role_map.get(msg_type)
        if role is None:
            return None

        timestamp = _parse_timestamp(record.get("timestamp")) or datetime.now(timezone.utc)
        msg_id = record.get("id") or f"msg_{index}"

        content = record.get("content")
        display_content = record.get("displayContent")
        text = _part_to_string(content)
        if not text and display_content is not None:
            text = _part_to_string(display_content)

        parts: list[Part] = []
        if text:
            parts.append(TextPart(content=text))

        if msg_type == "gemini":
            parts.extend(self._tool_parts(record.get("toolCalls")))

        usage = self._parse_usage(record.get("tokens"))
        model = record.get("model") if msg_type == "gemini" else None

        return Message(
            id=msg_id,
            role=role,
            timestamp=timestamp,
            model=model,
            parts=parts,
            usage=usage,
        )

    def _tool_parts(self, tool_calls: Any) -> list[Part]:
        """Convert Gemini tool calls to unified parts."""
        if not isinstance(tool_calls, list):
            return []

        parts: list[Part] = []

        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            tool_id = str(call.get("id", ""))
            tool_name = call.get("name", "unknown")
            parts.append(
                ToolCallPart(
                    tool_name=tool_name,
                    tool_id=tool_id,
                    input=call.get("args"),
                )
            )

            result_text = _part_to_string(call.get("result"))
            if not result_text and call.get("resultDisplay") is not None:
                result_text = _safe_json(call.get("resultDisplay"))

            if result_text:
                status = call.get("status")
                is_error = status in {"error", "cancelled"}
                parts.append(
                    ToolResultPart(
                        tool_id=tool_id,
                        output=result_text,
                        is_error=is_error,
                    )
                )

        return parts

    def _parse_usage(self, tokens: Any) -> TokenUsage | None:
        """Parse Gemini token usage metadata."""
        if not isinstance(tokens, dict):
            return None
        return TokenUsage(
            input_tokens=int(tokens.get("input", 0) or 0),
            output_tokens=int(tokens.get("output", 0) or 0),
            cached_tokens=int(tokens.get("cached", 0) or 0)
            if tokens.get("cached") is not None
            else None,
        )

    def _calculate_stats(self, turns: list[Turn]) -> SessionStats:
        """Calculate aggregated statistics from turns."""
        stats = SessionStats()
        stats.turn_count = len(turns)

        for turn in turns:
            for message in turn.messages:
                stats.message_count += 1

                if message.usage:
                    stats.input_tokens += message.usage.input_tokens
                    stats.output_tokens += message.usage.output_tokens

                for part in message.parts:
                    if isinstance(part, ToolCallPart):
                        stats.tool_call_count += 1

        return stats

    def _extract_title(self, data: dict[str, Any], turns: list[Turn]) -> str | None:
        """Extract a title from summary or first user message."""
        summary = data.get("summary")
        if isinstance(summary, str):
            summary = summary.strip()
            if summary:
                return summary

        for turn in turns:
            for message in turn.messages:
                if message.role != "user":
                    continue
                for part in message.parts:
                    if isinstance(part, TextPart):
                        text = part.content.strip()
                        if not text:
                            continue
                        if text.startswith("/") or text.startswith("?"):
                            continue
                        return text[:57] + "..." if len(text) > 60 else text
        return None

    def _build_model_usage(self, turns: list[Turn]) -> list[ModelUsage]:
        """Aggregate model usage from assistant messages."""
        usage: dict[str, ModelUsage] = {}

        for turn in turns:
            for message in turn.messages:
                if message.role != "assistant":
                    continue
                model = message.model
                if not model:
                    continue

                provider = "google"
                model_id = model
                if "/" in model:
                    provider, _ = model.split("/", 1)
                else:
                    model_id = f"{provider}/{model}"

                if model_id not in usage:
                    usage[model_id] = ModelUsage(
                        model_id=model_id,
                        provider=provider,
                        message_count=0,
                        input_tokens=0,
                        output_tokens=0,
                    )

                entry = usage[model_id]
                entry.message_count += 1
                if message.usage:
                    entry.input_tokens += message.usage.input_tokens
                    entry.output_tokens += message.usage.output_tokens

        return list(usage.values())
