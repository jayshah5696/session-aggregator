"""Codex CLI session adapter.

Parses OpenAI Codex CLI sessions from ~/.codex/sessions/ into unified format.
Codex CLI uses JSONL files stored in date-based directories (YYYY/MM/DD/).

Two session formats are supported:
1. Legacy format (pre-0.63.0): Direct JSON lines with 'type: message', 'role', 'content'
2. Modern format (0.63.0+): Wrapped in 'type/payload' with 'session_meta', 'response_item',
   'event_msg', 'turn_context' event types
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sagg.adapters.base import SessionAdapter, SessionRef
from sagg.models import (
    FileChangePart,
    Message,
    ModelUsage,
    SessionStats,
    SourceTool,
    TextPart,
    TokenUsage,
    ToolCallPart,
    Turn,
    UnifiedSession,
    extract_project_name,
    generate_session_id,
)


class CodexAdapter(SessionAdapter):
    """Adapter for OpenAI Codex CLI sessions.

    Codex CLI stores sessions as JSONL files in date-based directories.
    Supports both legacy format (direct messages) and modern format
    (wrapped in type/payload structure).
    """

    @property
    def name(self) -> str:
        """Adapter identifier."""
        return "codex"

    @property
    def display_name(self) -> str:
        """Human-readable name."""
        return "OpenAI Codex CLI"

    def get_default_path(self) -> Path:
        """Get default path for Codex sessions."""
        return Path.home() / ".codex" / "sessions"

    def is_available(self) -> bool:
        """Check if Codex sessions directory exists."""
        return self.get_default_path().exists()

    def list_sessions(self, since: datetime | None = None) -> list[SessionRef]:
        """List all Codex session files.

        Args:
            since: Optional datetime to filter sessions modified after this time.

        Returns:
            List of SessionRef objects for each session file.
        """
        sessions_path = self.get_default_path()
        if not sessions_path.exists():
            return []

        refs: list[SessionRef] = []

        # Codex stores sessions in nested date directories: YYYY/MM/DD/*.jsonl
        for session_file in sessions_path.glob("**/*.jsonl"):
            stat = session_file.stat()
            created_at = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc)
            updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

            if since is not None and updated_at <= since:
                continue

            refs.append(
                SessionRef(
                    id=session_file.stem,
                    path=session_file,
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )

        return sorted(refs, key=lambda r: r.created_at)

    def parse_session(self, ref: SessionRef) -> UnifiedSession:
        """Parse a Codex session into unified format.

        Args:
            ref: Reference to the session file.

        Returns:
            UnifiedSession with parsed content.
        """
        events = self._read_events(ref.path)

        # Extract metadata from session_meta event
        source_id = ref.id
        session_start: datetime | None = None
        project_path: str | None = None
        model_provider: str | None = None

        for event in events:
            # Modern format: session_meta with payload
            if event.get("type") == "session_meta":
                payload = event.get("payload", {})
                source_id = payload.get("id", ref.id)
                session_start = self._parse_timestamp(event)
                # Extract project path from cwd
                project_path = payload.get("cwd")
                # Extract model provider
                model_provider = payload.get("model_provider")
                break
            # Legacy format: first line has 'id' directly
            if "id" in event and "timestamp" in event and "type" not in event:
                source_id = event.get("id", ref.id)
                session_start = self._parse_timestamp(event)
                break

        # Group events into turns
        turns = self._group_into_turns(events)

        # Calculate stats
        stats = self._calculate_stats(turns)

        # Determine timestamps
        created_at = session_start or ref.created_at
        updated_at = ref.updated_at

        # Try to get more precise timestamps from events
        if turns:
            if turns[0].started_at:
                created_at = turns[0].started_at
            if turns[-1].ended_at:
                updated_at = turns[-1].ended_at

        duration_ms = None
        if created_at and updated_at:
            duration_ms = int((updated_at - created_at).total_seconds() * 1000)

        # Generate title from first user message if available
        title = self._extract_title(turns)

        # Build model usage if provider is known
        models = self._build_model_usage(turns, model_provider)

        return UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.CODEX,
            source_id=source_id,
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

    def _read_events(self, path: Path) -> list[dict[str, Any]]:
        """Read all events from a JSONL session file.

        Args:
            path: Path to the session file.

        Returns:
            List of event dictionaries.
        """
        events: list[dict[str, Any]] = []

        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    # Skip malformed lines
                    continue

        return events

    def _group_into_turns(self, events: list[dict[str, Any]]) -> list[Turn]:
        """Group events into conversation turns.

        Handles both legacy and modern Codex formats:
        - Legacy: Direct message objects with 'type: message', 'role', 'content'
        - Modern: Wrapped in 'type/payload' with 'response_item', 'event_msg' types

        A turn is created for each user message + subsequent assistant responses.

        Args:
            events: List of event dictionaries.

        Returns:
            List of Turn objects.
        """
        # First, extract all messages from the events
        messages: list[Message] = []
        message_counter = 0
        token_usage: TokenUsage | None = None

        for event in events:
            event_type = event.get("type", "")
            timestamp = self._parse_timestamp(event)

            # Modern format: response_item with payload containing message or function_call
            if event_type == "response_item":
                payload = event.get("payload", {})
                payload_type = payload.get("type", "")

                if payload_type == "message":
                    msg = self._payload_to_message(payload, message_counter, timestamp)
                    if msg:
                        messages.append(msg)
                        message_counter += 1

                elif payload_type == "function_call":
                    msg = self._extract_function_call(event, message_counter, timestamp)
                    if msg:
                        messages.append(msg)
                        message_counter += 1

                elif payload_type == "reasoning":
                    # Reasoning block in response_item
                    summary = payload.get("summary", [])
                    text_parts = []
                    for s in summary:
                        if isinstance(s, dict) and s.get("type") == "summary_text":
                            text_parts.append(s.get("text", ""))
                    if text_parts:
                        messages.append(
                            Message(
                                id=f"msg_{message_counter}",
                                role="assistant",
                                timestamp=timestamp or datetime.now(tz=timezone.utc),
                                parts=[TextPart(content=f"[Reasoning] {' '.join(text_parts)}")],
                            )
                        )
                        message_counter += 1

            # Modern format: event_msg for user messages and other events
            elif event_type == "event_msg":
                payload = event.get("payload", {})
                msg_type = payload.get("type", "")

                if msg_type == "user_message":
                    # User typed a message
                    text = payload.get("message", "")
                    if text:
                        messages.append(
                            Message(
                                id=f"msg_{message_counter}",
                                role="user",
                                timestamp=timestamp or datetime.now(tz=timezone.utc),
                                parts=[TextPart(content=text)],
                            )
                        )
                        message_counter += 1

                elif msg_type == "token_count":
                    # Extract token usage
                    info = payload.get("info") or {}
                    usage = info.get("last_token_usage") or info.get("total_token_usage") or {}
                    if usage:
                        token_usage = TokenUsage(
                            input_tokens=usage.get("input_tokens", 0),
                            output_tokens=usage.get("output_tokens", 0),
                            cached_tokens=usage.get("cached_input_tokens"),
                        )

                elif msg_type == "agent_reasoning":
                    # Reasoning output
                    text = payload.get("text", "")
                    if text:
                        messages.append(
                            Message(
                                id=f"msg_{message_counter}",
                                role="assistant",
                                timestamp=timestamp or datetime.now(tz=timezone.utc),
                                parts=[TextPart(content=f"[Reasoning] {text}")],
                            )
                        )
                        message_counter += 1

            # Legacy format: direct message with 'type: message'
            elif event_type == "message":
                msg = self._payload_to_message(event, message_counter, timestamp)
                if msg:
                    messages.append(msg)
                    message_counter += 1

        # Apply token usage to last assistant message if available
        if token_usage and messages:
            for msg in reversed(messages):
                if msg.role == "assistant":
                    msg.usage = token_usage
                    break

        # Group messages into turns (user message + assistant responses)
        return self._messages_to_turns(messages)

    def _payload_to_message(
        self, payload: dict[str, Any], counter: int, timestamp: datetime | None
    ) -> Message | None:
        """Convert a message payload to a Message object.

        Args:
            payload: Message payload dict with 'type', 'role', 'content'.
            counter: Message counter for ID generation.
            timestamp: Optional timestamp for the message.

        Returns:
            Message object or None if not a valid message.
        """
        if payload.get("type") != "message":
            return None

        role = payload.get("role", "")
        if role not in ("user", "assistant", "developer", "system"):
            return None

        # Normalize 'developer' role to 'system'
        if role == "developer":
            role = "system"

        content = payload.get("content", [])
        if isinstance(content, str):
            content = [{"type": "input_text", "text": content}]

        parts: list[TextPart | ToolCallPart] = []
        for item in content:
            if isinstance(item, dict):
                item_type = item.get("type", "")
                if item_type in ("input_text", "text"):
                    text = item.get("text", "")
                    if text:
                        parts.append(TextPart(content=text))
                elif item_type == "tool_call":
                    parts.append(
                        ToolCallPart(
                            tool_name=item.get("name", "unknown"),
                            tool_id=item.get("id", f"tool_{counter}"),
                            input=item.get("arguments"),
                        )
                    )

        if not parts:
            return None

        msg_id = payload.get("id") or f"msg_{counter}"
        return Message(
            id=msg_id,
            role=role,
            timestamp=timestamp or datetime.now(tz=timezone.utc),
            parts=parts,  # type: ignore[arg-type]
        )

    def _messages_to_turns(self, messages: list[Message]) -> list[Turn]:
        """Group messages into turns.

        A turn starts with a user message and includes all subsequent
        non-user messages until the next user message.

        Args:
            messages: List of Message objects.

        Returns:
            List of Turn objects.
        """
        if not messages:
            return []

        turns: list[Turn] = []
        current_turn_messages: list[Message] = []
        turn_index = 0

        for msg in messages:
            if msg.role == "user" and current_turn_messages:
                # Start a new turn - save the current one first
                turns.append(
                    Turn(
                        id=f"turn_{turn_index}",
                        index=turn_index,
                        started_at=current_turn_messages[0].timestamp,
                        ended_at=current_turn_messages[-1].timestamp,
                        messages=current_turn_messages,
                    )
                )
                turn_index += 1
                current_turn_messages = []

            current_turn_messages.append(msg)

        # Don't forget the last turn
        if current_turn_messages:
            turns.append(
                Turn(
                    id=f"turn_{turn_index}",
                    index=turn_index,
                    started_at=current_turn_messages[0].timestamp,
                    ended_at=current_turn_messages[-1].timestamp,
                    messages=current_turn_messages,
                )
            )

        return turns

    def _extract_function_call(
        self, event: dict[str, Any], counter: int, timestamp: datetime | None
    ) -> Message | None:
        """Extract function call from response_item payload.

        Modern Codex format includes function_call events with name/arguments.

        Args:
            event: Event with type='response_item' and payload containing function_call.
            counter: Message counter for ID generation.
            timestamp: Optional timestamp.

        Returns:
            Message with ToolCallPart or None.
        """
        payload = event.get("payload", {})
        if payload.get("type") != "function_call":
            return None

        name = payload.get("name", "unknown")
        call_id = payload.get("call_id", f"call_{counter}")
        arguments = payload.get("arguments", "")

        # Try to parse arguments as JSON
        try:
            args_dict = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError:
            args_dict = {"raw": arguments}

        return Message(
            id=f"msg_{counter}",
            role="assistant",
            timestamp=timestamp or datetime.now(tz=timezone.utc),
            parts=[
                ToolCallPart(
                    tool_name=name,
                    tool_id=call_id,
                    input=args_dict,
                )
            ],
        )

    def _parse_timestamp(self, event: dict[str, Any]) -> datetime | None:
        """Parse timestamp from event if available.

        Args:
            event: Event dictionary.

        Returns:
            Parsed datetime or None.
        """
        ts = event.get("timestamp") or event.get("created_at")
        if ts is None:
            return None

        if isinstance(ts, (int, float)):
            # Unix timestamp
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        elif isinstance(ts, str):
            # ISO format
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    def _calculate_stats(self, turns: list[Turn]) -> SessionStats:
        """Calculate aggregated statistics from turns.

        Args:
            turns: List of Turn objects.

        Returns:
            SessionStats with aggregated data.
        """
        stats = SessionStats()
        stats.turn_count = len(turns)
        files_modified: set[str] = set()

        for turn in turns:
            for message in turn.messages:
                stats.message_count += 1

                if message.usage:
                    stats.input_tokens += message.usage.input_tokens
                    stats.output_tokens += message.usage.output_tokens

                for part in message.parts:
                    if isinstance(part, ToolCallPart):
                        stats.tool_call_count += 1
                    elif isinstance(part, FileChangePart):
                        if part.path:
                            files_modified.add(part.path)

        stats.files_modified = sorted(files_modified)
        return stats

    def _extract_title(self, turns: list[Turn]) -> str | None:
        """Extract a title from the first user message.

        Args:
            turns: List of Turn objects.

        Returns:
            A title string (first 60 chars of first user message) or None.
        """
        for turn in turns:
            for message in turn.messages:
                if message.role == "user":
                    for part in message.parts:
                        if isinstance(part, TextPart):
                            text = part.content.strip()
                            # Skip system context messages
                            if text.startswith("<environment_context>") or text.startswith(
                                "<user_instructions>"
                            ):
                                continue
                            # Truncate to 60 chars for title
                            if len(text) > 60:
                                return text[:57] + "..."
                            return text if text else None
        return None

    def _build_model_usage(self, turns: list[Turn], model_provider: str | None) -> list[ModelUsage]:
        """Build model usage statistics.

        Codex uses a consistent model within a session, so we aggregate all
        token usage under a single model entry.

        Args:
            turns: List of Turn objects.
            model_provider: Model provider from session_meta (e.g., "openai").

        Returns:
            List of ModelUsage objects.
        """
        if not model_provider:
            return []

        # Default model based on provider
        model_id = f"{model_provider}/codex"

        total_input = 0
        total_output = 0
        message_count = 0

        for turn in turns:
            for message in turn.messages:
                if message.role == "assistant":
                    message_count += 1
                    if message.usage:
                        total_input += message.usage.input_tokens
                        total_output += message.usage.output_tokens

        if message_count == 0:
            return []

        return [
            ModelUsage(
                model_id=model_id,
                provider=model_provider,
                message_count=message_count,
                input_tokens=total_input,
                output_tokens=total_output,
            )
        ]
