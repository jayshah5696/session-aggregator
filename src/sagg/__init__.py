"""
sagg - Session Aggregator

Unified AI Coding Session Aggregator - collect, search, and export sessions
from multiple AI coding tools (OpenCode, Claude Code, Codex, Cursor).
"""

__version__ = "0.1.0"

from sagg.models import (
    FileChangePart,
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
)
from sagg.storage import SessionStore
from sagg.adapters import SessionAdapter, SessionRef, registry

__all__ = [
    "__version__",
    # Models
    "UnifiedSession",
    "Turn",
    "Message",
    "Part",
    "TextPart",
    "ToolCallPart",
    "ToolResultPart",
    "FileChangePart",
    "SourceTool",
    "TokenUsage",
    "ModelUsage",
    "SessionStats",
    "GitContext",
    # Storage
    "SessionStore",
    # Adapters
    "SessionAdapter",
    "SessionRef",
    "registry",
]
