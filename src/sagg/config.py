"""Configuration management for sagg.

This module provides configuration loading and management for the Session Aggregator.
Configuration is loaded from ~/.sagg/config.toml with sensible defaults.

Example config file:
    [sources.opencode]
    enabled = true
    path = "~/.local/share/opencode/storage"

    [sources.claude]
    enabled = true
    path = "~/.claude/projects"

    [viewer]
    port = 3000
    open_browser = true

    [export]
    default_format = "agenttrace"
    output_dir = "~/.sagg/exports"
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# Use tomllib for Python 3.11+, tomli for earlier versions
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


class SourceConfig(BaseModel):
    """Configuration for a session source adapter."""

    enabled: bool = True
    path: str = ""


class ViewerConfig(BaseModel):
    """Configuration for the web viewer."""

    port: int = Field(default=3000, ge=1, le=65535)
    open_browser: bool = True


class ExportConfig(BaseModel):
    """Configuration for export settings."""

    default_format: str = "agenttrace"
    output_dir: str = "~/.sagg/exports"


class Config(BaseModel):
    """Main configuration model for sagg."""

    sources: dict[str, SourceConfig] = Field(default_factory=dict)
    viewer: ViewerConfig = Field(default_factory=ViewerConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)

    def get_source_path(self, source_name: str) -> Path | None:
        """Get the expanded path for a source.

        Args:
            source_name: The name of the source (e.g., 'opencode', 'claude').

        Returns:
            Expanded Path object, or None if source not found.
        """
        if source_name not in self.sources:
            return None

        path_str = self.sources[source_name].path
        if not path_str:
            return None

        return Path(path_str).expanduser()

    def is_source_enabled(self, source_name: str) -> bool:
        """Check if a source is enabled.

        Args:
            source_name: The name of the source.

        Returns:
            True if source exists and is enabled, False otherwise.
        """
        if source_name not in self.sources:
            return False
        return self.sources[source_name].enabled


def get_default_config() -> Config:
    """Get the default configuration with all sources configured.

    Returns:
        Config object with default values for all sources.
    """
    default_sources = {
        "opencode": SourceConfig(
            enabled=True,
            path="~/.local/share/opencode/storage",
        ),
        "claude": SourceConfig(
            enabled=True,
            path="~/.claude/projects",
        ),
        "codex": SourceConfig(
            enabled=True,
            path="~/.codex/sessions",
        ),
        "cursor": SourceConfig(
            enabled=True,
            path="~/Library/Application Support/Cursor/User/globalStorage/state.vscdb",
        ),
        "ampcode": SourceConfig(
            enabled=True,
            path="~/.sagg/cache/ampcode",
        ),
    }

    return Config(
        sources=default_sources,
        viewer=ViewerConfig(),
        export=ExportConfig(),
    )


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from a TOML file.

    If the file doesn't exist, returns the default configuration.
    Partial configurations are merged with defaults.

    Args:
        config_path: Path to the config file. Defaults to ~/.sagg/config.toml.

    Returns:
        Config object with loaded or default values.
    """
    if config_path is None:
        config_path = Path.home() / ".sagg" / "config.toml"

    # Start with defaults
    default_config = get_default_config()

    if not config_path.exists():
        return default_config

    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        # Return defaults if file can't be read or parsed
        return default_config

    # Merge with defaults
    return _merge_config(default_config, data)


def _merge_config(default: Config, data: dict[str, Any]) -> Config:
    """Merge loaded config data with defaults.

    Args:
        default: Default configuration.
        data: Loaded TOML data.

    Returns:
        Merged Config object.
    """
    # Start with default sources
    sources = dict(default.sources)

    # Override with loaded sources
    if "sources" in data:
        for source_name, source_data in data["sources"].items():
            if isinstance(source_data, dict):
                # Merge with existing default if present
                if source_name in sources:
                    existing = sources[source_name]
                    sources[source_name] = SourceConfig(
                        enabled=source_data.get("enabled", existing.enabled),
                        path=source_data.get("path", existing.path),
                    )
                else:
                    sources[source_name] = SourceConfig(**source_data)

    # Merge viewer config
    viewer_data = data.get("viewer", {})
    viewer = ViewerConfig(
        port=viewer_data.get("port", default.viewer.port),
        open_browser=viewer_data.get("open_browser", default.viewer.open_browser),
    )

    # Merge export config
    export_data = data.get("export", {})
    export = ExportConfig(
        default_format=export_data.get("default_format", default.export.default_format),
        output_dir=export_data.get("output_dir", default.export.output_dir),
    )

    return Config(
        sources=sources,
        viewer=viewer,
        export=export,
    )


# Global config cache
_config_cache: Config | None = None


def get_config() -> Config:
    """Get the global configuration instance.

    Loads from ~/.sagg/config.toml on first call, then returns cached instance.

    Returns:
        The global Config instance.
    """
    global _config_cache
    if _config_cache is None:
        _config_cache = load_config()
    return _config_cache


def _clear_config_cache() -> None:
    """Clear the config cache. Used for testing."""
    global _config_cache
    _config_cache = None
