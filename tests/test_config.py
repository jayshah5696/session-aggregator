"""Tests for configuration module."""

import tempfile
import shutil
from pathlib import Path

import pytest

from sagg.config import (
    Config,
    SourceConfig,
    ViewerConfig,
    ExportConfig,
    load_config,
    get_default_config,
)


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


class TestDefaultConfig:
    """Tests for default configuration when no file exists."""

    def test_default_config_returns_valid_config(self):
        """Default config should return a valid Config object."""
        config = get_default_config()
        assert isinstance(config, Config)

    def test_default_config_has_all_sources(self):
        """Default config should have entries for all expected sources."""
        config = get_default_config()
        expected_sources = ["opencode", "claude", "codex", "cursor", "ampcode"]
        for source in expected_sources:
            assert source in config.sources
            assert isinstance(config.sources[source], SourceConfig)

    def test_default_sources_are_enabled(self):
        """Default sources should be enabled."""
        config = get_default_config()
        for source_name, source_config in config.sources.items():
            assert source_config.enabled is True, f"{source_name} should be enabled"

    def test_default_source_paths_exist(self):
        """Default sources should have valid path strings."""
        config = get_default_config()
        for source_name, source_config in config.sources.items():
            assert source_config.path is not None
            assert len(source_config.path) > 0

    def test_default_viewer_config(self):
        """Default viewer config should have expected values."""
        config = get_default_config()
        assert config.viewer.port == 3000
        assert config.viewer.open_browser is True

    def test_default_export_config(self):
        """Default export config should have expected values."""
        config = get_default_config()
        assert config.export.default_format == "agenttrace"
        assert "~/.sagg/exports" in config.export.output_dir


class TestLoadConfigMissingFile:
    """Tests for loading config when file doesn't exist."""

    def test_load_config_missing_file_returns_defaults(self, temp_config_dir):
        """Loading from non-existent file should return defaults."""
        config_path = temp_config_dir / "config.toml"
        config = load_config(config_path)

        # Should return default config
        default_config = get_default_config()
        assert len(config.sources) == len(default_config.sources)
        assert config.viewer.port == default_config.viewer.port

    def test_load_config_missing_directory_returns_defaults(self, temp_config_dir):
        """Loading from non-existent directory should return defaults."""
        config_path = temp_config_dir / "nonexistent" / "config.toml"
        config = load_config(config_path)

        assert isinstance(config, Config)
        assert len(config.sources) > 0


class TestLoadConfigFromFile:
    """Tests for loading config from a TOML file."""

    def test_load_config_parses_sources(self, temp_config_dir):
        """Config file sources should be parsed correctly."""
        config_content = """
[sources.opencode]
enabled = true
path = "/custom/opencode/path"

[sources.claude]
enabled = false
path = "/custom/claude/path"
"""
        config_path = temp_config_dir / "config.toml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        assert config.sources["opencode"].enabled is True
        assert config.sources["opencode"].path == "/custom/opencode/path"
        assert config.sources["claude"].enabled is False
        assert config.sources["claude"].path == "/custom/claude/path"

    def test_load_config_parses_viewer(self, temp_config_dir):
        """Config file viewer settings should be parsed correctly."""
        config_content = """
[viewer]
port = 8080
open_browser = false
"""
        config_path = temp_config_dir / "config.toml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        assert config.viewer.port == 8080
        assert config.viewer.open_browser is False

    def test_load_config_parses_export(self, temp_config_dir):
        """Config file export settings should be parsed correctly."""
        config_content = """
[export]
default_format = "json"
output_dir = "/custom/exports"
"""
        config_path = temp_config_dir / "config.toml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        assert config.export.default_format == "json"
        assert config.export.output_dir == "/custom/exports"

    def test_load_config_merges_with_defaults(self, temp_config_dir):
        """Partial config should be merged with defaults."""
        config_content = """
[sources.opencode]
enabled = false
path = "/custom/path"

[viewer]
port = 9000
"""
        config_path = temp_config_dir / "config.toml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        # Explicitly set values
        assert config.sources["opencode"].enabled is False
        assert config.sources["opencode"].path == "/custom/path"
        assert config.viewer.port == 9000

        # Default values for non-specified sources
        assert "claude" in config.sources
        assert config.sources["claude"].enabled is True

        # Default values for non-specified viewer settings
        assert config.viewer.open_browser is True


class TestPathExpansion:
    """Tests for path expansion (~ to home directory)."""

    def test_expand_path_with_tilde(self, temp_config_dir):
        """Paths with ~ should be expanded to home directory."""
        config_content = """
[sources.opencode]
enabled = true
path = "~/.local/share/opencode/storage"
"""
        config_path = temp_config_dir / "config.toml"
        config_path.write_text(config_content)

        config = load_config(config_path)
        expanded_path = config.get_source_path("opencode")

        assert expanded_path is not None
        assert "~" not in str(expanded_path)
        assert str(expanded_path).startswith(str(Path.home()))

    def test_expand_path_absolute(self, temp_config_dir):
        """Absolute paths should remain unchanged."""
        config_content = """
[sources.opencode]
enabled = true
path = "/absolute/path/to/opencode"
"""
        config_path = temp_config_dir / "config.toml"
        config_path.write_text(config_content)

        config = load_config(config_path)
        expanded_path = config.get_source_path("opencode")

        assert expanded_path is not None
        assert str(expanded_path) == "/absolute/path/to/opencode"


class TestSourceEnableDisable:
    """Tests for source enable/disable functionality."""

    def test_is_source_enabled_true(self, temp_config_dir):
        """Enabled sources should return True."""
        config_content = """
[sources.opencode]
enabled = true
path = "/path"
"""
        config_path = temp_config_dir / "config.toml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        assert config.is_source_enabled("opencode") is True

    def test_is_source_enabled_false(self, temp_config_dir):
        """Disabled sources should return False."""
        config_content = """
[sources.opencode]
enabled = false
path = "/path"
"""
        config_path = temp_config_dir / "config.toml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        assert config.is_source_enabled("opencode") is False

    def test_is_source_enabled_unknown_source(self):
        """Unknown sources should return False."""
        config = get_default_config()

        assert config.is_source_enabled("nonexistent_source") is False


class TestGetSourcePath:
    """Tests for get_source_path method."""

    def test_get_source_path_returns_path(self, temp_config_dir):
        """get_source_path should return Path object for valid source."""
        config_content = """
[sources.opencode]
enabled = true
path = "~/.local/share/opencode/storage"
"""
        config_path = temp_config_dir / "config.toml"
        config_path.write_text(config_content)

        config = load_config(config_path)
        path = config.get_source_path("opencode")

        assert path is not None
        assert isinstance(path, Path)

    def test_get_source_path_unknown_source(self):
        """get_source_path should return None for unknown source."""
        config = get_default_config()

        path = config.get_source_path("nonexistent_source")

        assert path is None

    def test_get_source_path_disabled_source(self, temp_config_dir):
        """get_source_path should still return path for disabled source."""
        config_content = """
[sources.opencode]
enabled = false
path = "/path/to/opencode"
"""
        config_path = temp_config_dir / "config.toml"
        config_path.write_text(config_content)

        config = load_config(config_path)
        path = config.get_source_path("opencode")

        # Path should still be returned even if source is disabled
        assert path is not None
        assert str(path) == "/path/to/opencode"


class TestConfigSingleton:
    """Tests for global config access."""

    def test_get_config_returns_config(self):
        """get_config should return a Config instance."""
        from sagg.config import get_config

        config = get_config()

        assert isinstance(config, Config)

    def test_get_config_is_cached(self):
        """get_config should return the same instance on repeated calls."""
        from sagg.config import get_config, _clear_config_cache

        _clear_config_cache()  # Clear any existing cache

        config1 = get_config()
        config2 = get_config()

        assert config1 is config2


class TestFullConfigFile:
    """Test loading a complete config file matching the spec."""

    def test_load_full_spec_config(self, temp_config_dir):
        """Full config file from spec should load correctly."""
        config_content = """
# ~/.sagg/config.toml

[sources.opencode]
enabled = true
path = "~/.local/share/opencode/storage"

[sources.claude]
enabled = true
path = "~/.claude/projects"

[sources.codex]
enabled = true
path = "~/.codex/sessions"

[sources.cursor]
enabled = true
path = "~/Library/Application Support/Cursor/User/globalStorage/state.vscdb"

[sources.ampcode]
enabled = true
path = "~/.sagg/cache/ampcode"

[viewer]
port = 3000
open_browser = true

[export]
default_format = "agenttrace"
output_dir = "~/.sagg/exports"
"""
        config_path = temp_config_dir / "config.toml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        # Verify all sources
        assert len(config.sources) >= 5
        assert config.sources["opencode"].enabled is True
        assert config.sources["claude"].enabled is True
        assert config.sources["codex"].enabled is True
        assert config.sources["cursor"].enabled is True
        assert config.sources["ampcode"].enabled is True

        # Verify viewer
        assert config.viewer.port == 3000
        assert config.viewer.open_browser is True

        # Verify export
        assert config.export.default_format == "agenttrace"
        assert "exports" in config.export.output_dir
