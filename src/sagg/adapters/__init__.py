"""Session adapters for different AI coding tools."""

from sagg.adapters.ampcode import AmpcodeAdapter
from sagg.adapters.base import SessionAdapter, SessionRef
from sagg.adapters.claude import ClaudeCodeAdapter
from sagg.adapters.codex import CodexAdapter
from sagg.adapters.cursor import CursorAdapter
from sagg.adapters.opencode import OpenCodeAdapter
from sagg.adapters.registry import AdapterRegistry, registry

# Register all adapters
registry.register(OpenCodeAdapter())
registry.register(ClaudeCodeAdapter())
registry.register(CodexAdapter())
registry.register(CursorAdapter())
registry.register(AmpcodeAdapter())

__all__ = [
    "AdapterRegistry",
    "AmpcodeAdapter",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "CursorAdapter",
    "OpenCodeAdapter",
    "SessionAdapter",
    "SessionRef",
    "registry",
]
