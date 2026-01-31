"""Adapter registry for managing session adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagg.adapters.base import SessionAdapter


class AdapterRegistry:
    """Registry for managing session adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, SessionAdapter] = {}

    def register(self, adapter: SessionAdapter) -> None:
        """Register an adapter with the registry."""
        self._adapters[adapter.name] = adapter

    def get_adapter(self, name: str) -> SessionAdapter:
        """Get an adapter by name.

        Args:
            name: The adapter identifier.

        Returns:
            The registered adapter.

        Raises:
            KeyError: If no adapter with the given name is registered.
        """
        if name not in self._adapters:
            available = ", ".join(self._adapters.keys()) or "none"
            raise KeyError(f"Adapter '{name}' not found. Available adapters: {available}")
        return self._adapters[name]

    def list_adapters(self) -> list[SessionAdapter]:
        """List all registered adapters.

        Returns:
            List of all registered adapters.
        """
        return list(self._adapters.values())

    def get_available_adapters(self) -> list[SessionAdapter]:
        """List all adapters that are available on this system.

        Returns:
            List of adapters where is_available() returns True.
        """
        return [adapter for adapter in self._adapters.values() if adapter.is_available()]


# Global registry instance
registry = AdapterRegistry()
