"""Cursor session adapter.

Cursor stores session data in a SQLite database (state.vscdb) with
conversation data stored as JSON in a key-value table.

Data Format Versions:
- Version 1: Messages stored inline in `conversation` array within composerData
- Versions 3-13: Messages stored separately in `bubbleId:composerId:bubbleId` keys,
  with `fullConversationHeadersOnly` providing the ordered list of bubble IDs
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sagg.adapters.base import SessionAdapter, SessionRef
from sagg.models import (
    Message,
    Part,
    SessionStats,
    SourceTool,
    TextPart,
    Turn,
    UnifiedSession,
    extract_project_name,
    generate_session_id,
)

if TYPE_CHECKING:
    pass


class CursorAdapter(SessionAdapter):
    """Adapter for Cursor session data.

    Cursor stores conversations in a SQLite database with a key-value table.
    Keys follow patterns like `composerData:<id>` for full conversation data.
    """

    def __init__(self, path: Path | None = None) -> None:
        """Initialize the Cursor adapter.

        Args:
            path: Optional path to the state.vscdb file. If not provided,
                  the default platform-specific path will be used.
        """
        self._path = path

    @property
    def name(self) -> str:
        """Adapter identifier."""
        return "cursor"

    @property
    def display_name(self) -> str:
        """Human-readable name."""
        return "Cursor"

    def get_default_path(self) -> Path:
        """Get default path for this platform.

        Returns:
            Platform-specific path to the Cursor state database.
        """
        if sys.platform == "darwin":
            return Path.home() / "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
        elif sys.platform == "win32":
            # Use APPDATA environment variable for Windows
            import os

            appdata = os.environ.get("APPDATA", "")
            if appdata:
                return Path(appdata) / "Cursor/User/globalStorage/state.vscdb"
            return Path.home() / "AppData/Roaming/Cursor/User/globalStorage/state.vscdb"
        else:
            # Linux and other Unix-like systems
            return Path.home() / ".config/Cursor/User/globalStorage/state.vscdb"

    def _get_db_path(self) -> Path:
        """Get the database path to use."""
        return self._path if self._path is not None else self.get_default_path()

    def is_available(self) -> bool:
        """Check if Cursor database exists on this system."""
        return self._get_db_path().exists()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection to the SQLite database.

        Yields:
            SQLite connection with row factory set.
        """
        db_path = self._get_db_path()
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def list_sessions(self, since: datetime | None = None) -> list[SessionRef]:
        """List all session references from Cursor.

        Args:
            since: If provided, only return sessions updated after this time.

        Returns:
            List of session references.
        """
        if not self.is_available():
            return []

        sessions: list[SessionRef] = []

        with self._connect() as conn:
            cursor = conn.cursor()

            # Query all composerData:* keys from the key-value table
            cursor.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'")

            for row in cursor.fetchall():
                key = row["key"]
                value = row["value"]

                # Skip entries with no value
                if value is None:
                    continue

                # Extract composer ID from key (composerData:<id>)
                composer_id = key.replace("composerData:", "", 1)

                try:
                    data = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    continue

                # Parse timestamps (stored as milliseconds)
                created_at = self._parse_timestamp(data.get("createdAt"))
                updated_at = self._parse_timestamp(data.get("lastUpdatedAt")) or created_at

                if created_at is None:
                    # Skip sessions without timestamps
                    continue

                # updated_at is guaranteed to be non-None since created_at is checked above
                # and updated_at falls back to created_at
                session_updated_at = updated_at if updated_at is not None else created_at

                # Filter by since if provided
                if since is not None and session_updated_at < since:
                    continue

                sessions.append(
                    SessionRef(
                        id=composer_id,
                        path=self._get_db_path(),
                        created_at=created_at,
                        updated_at=session_updated_at,
                    )
                )

        # Sort by created_at descending (most recent first)
        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions

    def parse_session(self, ref: SessionRef) -> UnifiedSession:
        """Parse a Cursor session into unified format.

        Args:
            ref: Session reference from list_sessions.

        Returns:
            Unified session object.

        Raises:
            ValueError: If the session data cannot be parsed.
        """
        with self._connect() as conn:
            cursor = conn.cursor()

            # Query the specific composerData entry
            cursor.execute(
                "SELECT value FROM cursorDiskKV WHERE key = ?",
                (f"composerData:{ref.id}",),
            )
            row = cursor.fetchone()

            if row is None:
                raise ValueError(f"Session not found: {ref.id}")

            data = json.loads(row["value"])

            # Check data format version to determine where messages are stored
            # Version 1: inline `conversation` array
            # Versions 3+: separate bubbleId entries with fullConversationHeadersOnly
            bubbles = self._load_messages(cursor, ref.id, data)

        return self._convert_to_unified(ref, data, bubbles)

    def _load_messages(
        self,
        cursor: sqlite3.Cursor,
        composer_id: str,
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Load messages from the appropriate storage location.

        Handles both inline conversation format (v1) and separate bubble
        entries (v3+).

        Args:
            cursor: SQLite cursor.
            composer_id: The composer/session ID.
            data: The composerData dictionary.

        Returns:
            List of message dictionaries in conversation order.
        """
        # Check for inline conversation array (Version 1 format)
        conversation = data.get("conversation")
        if conversation and isinstance(conversation, list) and len(conversation) > 0:
            # Messages are stored inline - use them directly
            return conversation

        # Check for fullConversationHeadersOnly (Version 3+ format)
        headers = data.get("fullConversationHeadersOnly", [])
        if headers:
            # Load bubbles from separate entries, ordered by headers
            return self._load_bubbles_ordered(cursor, composer_id, headers)

        # Fallback: try loading all bubbles (legacy behavior)
        return self._load_bubbles(cursor, composer_id)

    def _load_bubbles_ordered(
        self,
        cursor: sqlite3.Cursor,
        composer_id: str,
        headers: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Load bubble entries in the order specified by headers.

        Uses fullConversationHeadersOnly to maintain correct conversation order.

        Args:
            cursor: SQLite cursor.
            composer_id: The composer/session ID.
            headers: List of header dicts with bubbleId and type.

        Returns:
            List of bubble dictionaries in conversation order.
        """
        # Build a map of bubble_id -> bubble data
        prefix = f"bubbleId:{composer_id}:"
        cursor.execute(
            "SELECT key, value FROM cursorDiskKV WHERE key LIKE ?",
            (f"{prefix}%",),
        )

        bubble_map: dict[str, dict[str, Any]] = {}
        for row in cursor.fetchall():
            try:
                bubble = json.loads(row["value"])
                bubble_id = row["key"].replace(prefix, "")
                bubble["_bubble_id"] = bubble_id
                bubble_map[bubble_id] = bubble
            except (json.JSONDecodeError, TypeError):
                continue

        # Return bubbles in header order
        ordered_bubbles: list[dict[str, Any]] = []
        for header in headers:
            bubble_id = header.get("bubbleId", "")
            if bubble_id in bubble_map:
                ordered_bubbles.append(bubble_map[bubble_id])
            else:
                # Create a minimal bubble from header if not found in DB
                # (may happen if bubble was deleted or not yet persisted)
                ordered_bubbles.append(
                    {
                        "_bubble_id": bubble_id,
                        "bubbleId": bubble_id,
                        "type": header.get("type"),
                        "text": "",
                    }
                )

        return ordered_bubbles

    def _load_bubbles(self, cursor: sqlite3.Cursor, composer_id: str) -> list[dict[str, Any]]:
        """Load all bubble (message) entries for a composer session.

        Legacy fallback method when fullConversationHeadersOnly is not available.
        Cursor stores messages separately in bubbleId:composerId:bubbleId format.

        Args:
            cursor: SQLite cursor.
            composer_id: The composer/session ID.

        Returns:
            List of bubble dictionaries sorted by type (user first).
        """
        prefix = f"bubbleId:{composer_id}:"
        cursor.execute(
            "SELECT key, value FROM cursorDiskKV WHERE key LIKE ?",
            (f"{prefix}%",),
        )

        bubbles: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            try:
                bubble = json.loads(row["value"])
                # Extract bubble ID from key
                bubble["_bubble_id"] = row["key"].replace(prefix, "")
                bubbles.append(bubble)
            except (json.JSONDecodeError, TypeError):
                continue

        # Sort by type (1=user first, then 2=assistant) to maintain conversation order
        # This is a heuristic since we don't have reliable timestamps
        bubbles.sort(key=lambda b: (b.get("type", 0), b.get("_bubble_id", "")))

        return bubbles

    def _extract_text(self, bubble: dict[str, Any]) -> str:
        """Extract plain text from a bubble/message.

        Handles multiple text storage formats:
        - Direct 'text' field (plain string)
        - 'richText' as JSON with Lexical editor format

        Args:
            bubble: Bubble/message dictionary.

        Returns:
            Plain text content, or empty string if none found.
        """
        # Try direct text field first
        text = bubble.get("text", "")
        if text and isinstance(text, str) and text.strip():
            return text

        # Try richText - may be JSON or plain string
        rich_text = bubble.get("richText", "")
        if not rich_text:
            return ""

        if isinstance(rich_text, str):
            # Check if it's JSON (Lexical editor format)
            if rich_text.startswith("{"):
                try:
                    rt_data = json.loads(rich_text)
                    # Extract text from Lexical editor JSON structure
                    return self._extract_lexical_text(rt_data)
                except (json.JSONDecodeError, TypeError):
                    return rich_text
            return rich_text

        return ""

    def _extract_lexical_text(self, data: dict[str, Any]) -> str:
        """Extract plain text from Lexical editor JSON structure.

        Args:
            data: Parsed Lexical editor JSON.

        Returns:
            Plain text extracted from the structure.
        """
        texts: list[str] = []

        def walk(node: dict[str, Any] | list[Any]) -> None:
            if isinstance(node, dict):
                # Check for text content
                if node.get("type") == "text":
                    text = node.get("text", "")
                    if text:
                        texts.append(text)
                # Recurse into children
                children = node.get("children", [])
                if children:
                    walk(children)
                # Also check root
                root = node.get("root")
                if root:
                    walk(root)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(data)
        return " ".join(texts)

    def _parse_timestamp(self, ts: int | float | None) -> datetime | None:
        """Convert millisecond timestamp to datetime.

        Args:
            ts: Timestamp in milliseconds since epoch.

        Returns:
            datetime object or None if timestamp is invalid.
        """
        if ts is None:
            return None

        try:
            # Cursor stores timestamps in milliseconds (timezone-aware)
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None

    def _convert_to_unified(
        self,
        ref: SessionRef,
        data: dict[str, Any],
        bubbles: list[dict[str, Any]],
    ) -> UnifiedSession:
        """Convert Cursor session data to unified format.

        Args:
            ref: Session reference.
            data: Parsed JSON data from composerData.
            bubbles: List of bubble (message) dictionaries.

        Returns:
            Unified session object.
        """
        turns: list[Turn] = []
        messages: list[Message] = []
        turn_index = 0
        current_turn_start: datetime | None = None
        files_modified: set[str] = set()
        project_path: str | None = None

        # Track token usage across all bubbles
        total_input_tokens = 0
        total_output_tokens = 0

        # Process bubbles (messages from both inline and separate storage)
        for bubble in bubbles:
            bubble_id = bubble.get("bubbleId", bubble.get("_bubble_id", ""))
            bubble_type = bubble.get("type")
            text = self._extract_text(bubble)

            # Accumulate token counts from bubbles
            token_count = bubble.get("tokenCount", {})
            if isinstance(token_count, dict):
                total_input_tokens += token_count.get("inputTokens", 0)
                total_output_tokens += token_count.get("outputTokens", 0)

            # Skip empty messages
            if not text.strip():
                continue

            # Use session timestamp as default (bubbles don't have reliable timestamps)
            timestamp = ref.created_at

            # Map type: 1 = user, 2 = assistant
            role: Literal["user", "assistant"]
            if bubble_type == 1:
                role = "user"
            elif bubble_type == 2:
                role = "assistant"
            else:
                # Skip unknown types
                continue

            parts: list[Part] = []
            if text:
                parts.append(TextPart(content=text))

            message = Message(
                id=bubble_id,
                role=role,
                timestamp=timestamp,
                parts=parts,
            )

            # Start a new turn on user messages
            if role == "user":
                # Save previous turn if it has messages
                if messages:
                    turn_end = messages[-1].timestamp
                    turns.append(
                        Turn(
                            id=f"{ref.id}-turn-{turn_index}",
                            index=turn_index,
                            started_at=current_turn_start or ref.created_at,
                            ended_at=turn_end,
                            messages=messages,
                        )
                    )
                    turn_index += 1
                    messages = []

                current_turn_start = timestamp

            messages.append(message)

            # Extract project path from bubble's file selections
            if project_path is None:
                project_path = self._extract_project_path(bubble)

            # Collect files from bubble context
            bubble_context = bubble.get("context", {})
            self._collect_files(bubble_context, files_modified)

        # Add the last turn
        if messages:
            turn_end = messages[-1].timestamp
            turns.append(
                Turn(
                    id=f"{ref.id}-turn-{turn_index}",
                    index=turn_index,
                    started_at=current_turn_start or ref.created_at,
                    ended_at=turn_end,
                    messages=messages,
                )
            )

        # Also check composerData context for files and project path
        context = data.get("context", {})
        self._collect_files(context, files_modified)
        if project_path is None:
            folder_selections = context.get("folderSelections", [])
            if folder_selections:
                first_folder = folder_selections[0]
                if isinstance(first_folder, dict):
                    project_path = first_folder.get("path")
                elif isinstance(first_folder, str):
                    project_path = first_folder

        # Generate title from first user message if not set
        title = data.get("name")
        if not title and turns:
            title = self._extract_title(turns)

        # Use session-level token count if bubble-level counts are zero
        # (Version 1 format stores tokens at session level)
        session_token_count = data.get("tokenCount", {})
        if total_input_tokens == 0 and total_output_tokens == 0:
            if isinstance(session_token_count, dict):
                total_input_tokens = session_token_count.get("inputTokens", 0)
                total_output_tokens = session_token_count.get("outputTokens", 0)
            elif isinstance(session_token_count, int):
                # Some versions store just a number
                total_output_tokens = session_token_count

        # Calculate stats
        message_count = sum(len(turn.messages) for turn in turns)
        stats = SessionStats(
            turn_count=len(turns),
            message_count=message_count,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            files_modified=sorted(files_modified),
        )

        # Calculate duration
        duration_ms = None
        if ref.updated_at and ref.created_at:
            delta = ref.updated_at - ref.created_at
            duration_ms = int(delta.total_seconds() * 1000)

        return UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.CURSOR,
            source_id=data.get("composerId", ref.id),
            source_path=str(ref.path),
            title=title,
            project_path=project_path,
            project_name=extract_project_name(project_path) if project_path else None,
            created_at=ref.created_at,
            updated_at=ref.updated_at,
            duration_ms=duration_ms,
            stats=stats,
            turns=turns,
        )

    def _extract_project_path(self, bubble: dict[str, Any]) -> str | None:
        """Extract project path from a bubble's file selections.

        Args:
            bubble: Bubble dictionary with context.

        Returns:
            Project path derived from first file selection, or None.
        """
        context = bubble.get("context", {})
        file_selections = context.get("fileSelections", [])

        for file_sel in file_selections:
            if not isinstance(file_sel, dict):
                continue

            # Try to get path from uri object
            uri = file_sel.get("uri", {})
            if isinstance(uri, dict):
                path = uri.get("path", "")
                if path:
                    # Extract project root (go up from file to find common parent)
                    # Look for common project indicators
                    from pathlib import Path

                    p = Path(path)
                    # Walk up to find a reasonable project root
                    for parent in p.parents:
                        if parent.name in ("Documents", "Users", "home", ""):
                            break
                        # Check for git or common project files
                        if (parent / ".git").exists() or (parent / "package.json").exists():
                            return str(parent)
                        # Use GitHub folder as project root indicator
                        if parent.parent and parent.parent.name == "GitHub":
                            return str(parent)
                    # Fallback: use parent of parent of file
                    if len(p.parents) >= 2:
                        return str(p.parents[1])

        return None

    def _collect_files(self, context: dict[str, Any], files: set[str]) -> None:
        """Collect file paths from context into a set.

        Args:
            context: Context dictionary with fileSelections.
            files: Set to add file paths to.
        """
        file_selections = context.get("fileSelections", [])
        for file_sel in file_selections:
            if isinstance(file_sel, dict):
                # Try uri.path first
                uri = file_sel.get("uri", {})
                if isinstance(uri, dict):
                    path = uri.get("path", "")
                    if path:
                        files.add(path)
                        continue
                # Fallback to direct path
                path = file_sel.get("path", "")
                if path:
                    files.add(path)
            elif isinstance(file_sel, str):
                files.add(file_sel)

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
                            # Skip @ mentions at the start
                            if text.startswith("@"):
                                # Find the actual message after mentions
                                lines = text.split("\n")
                                for line in lines:
                                    if not line.strip().startswith("@"):
                                        text = line.strip()
                                        break
                            # Truncate to 60 chars for title
                            if len(text) > 60:
                                return text[:57] + "..."
                            return text if text else None
        return None
