"""Base adapter interface for session sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagg.models import UnifiedSession


@dataclass
class SessionRef:
    """Reference to a session file without loading full content."""

    id: str
    path: Path
    created_at: datetime
    updated_at: datetime


class SessionAdapter(ABC):
    """Base class for all session adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Adapter identifier (e.g., 'opencode', 'claude')."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name."""
        ...

    @abstractmethod
    def get_default_path(self) -> Path:
        """Get default path for this platform."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if source is available on this system."""
        ...

    @abstractmethod
    def list_sessions(self, since: datetime | None = None) -> list[SessionRef]:
        """List all session references."""
        ...

    @abstractmethod
    def parse_session(self, ref: SessionRef) -> UnifiedSession:
        """Parse a session into unified format."""
        ...

    def has_changed(self, ref: SessionRef, last_import: datetime) -> bool:
        """Check if session has been modified since last import."""
        return ref.updated_at > last_import
