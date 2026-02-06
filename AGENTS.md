# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**sagg** (Session Aggregator) is a CLI tool that collects, normalizes, searches, and exports AI coding sessions from multiple tools (OpenCode, Claude Code, Codex, Cursor, Gemini CLI, Ampcode) into a unified format. Sessions are stored in SQLite with FTS5 full-text search, and can be exported to AgentTrace or Markdown formats.

## Commands

```bash
# Setup
uv sync                              # Install all dependencies
uv sync --extra dev                  # Install with dev dependencies

# Run CLI
uv run sagg --help                   # Show all commands
uv run sagg collect                  # Collect sessions from all sources
uv run sagg list                     # List collected sessions
uv run sagg search "query"          # Full-text search
uv run sagg tui                      # Launch interactive TUI

# Testing
uv run pytest                        # Run all tests
uv run pytest tests/test_sync.py     # Run a single test file
uv run pytest tests/test_sync.py::test_name  # Run a single test

# Linting & Type Checking
uv run ruff check src/               # Lint
uv run ruff format src/              # Auto-format
uv run mypy src/                     # Type check (strict mode)
```

## Architecture

```
src/sagg/
├── cli.py                 # Click CLI entry point (all commands)
├── models.py              # Pydantic v2 data models (core data layer)
├── config.py              # Config loading (~/.sagg/config.toml)
├── sync.py                # SessionSyncer (orchestrates collection)
├── bundle.py              # Portable bundle export/import
├── git_utils.py           # Git repo detection, commit linking
├── adapters/              # Source tool adapters
│   ├── base.py            # SessionAdapter ABC + SessionRef dataclass
│   ├── registry.py        # AdapterRegistry (discovers available adapters)
│   ├── opencode.py        # OpenCode adapter
│   ├── claude.py          # Claude Code adapter
│   ├── codex.py           # Codex CLI adapter
│   ├── cursor.py          # Cursor adapter
│   ├── gemini.py          # Gemini CLI adapter
│   └── ampcode.py         # Ampcode adapter
├── storage/
│   ├── db.py              # SQLite schema + FTS5 index
│   └── store.py           # SessionStore (CRUD, search, persistence)
├── export/
│   ├── agenttrace.py      # AgentTrace format exporter
│   └── markdown.py        # Markdown exporter
├── security/
│   └── scrubber.py        # Sensitive data redaction
├── analytics/
│   ├── oracle.py          # Semantic search via embeddings
│   ├── similar.py         # TF-IDF session similarity
│   ├── heatmap.py         # GitHub-style activity heatmap
│   └── friction.py        # Friction point detection
└── tui/
    ├── app.py             # Textual TUI application
    └── widgets/           # TUI components (ChatView, SessionTree, etc.)
```

### Data Model Hierarchy

`UnifiedSession` -> `Turn` -> `Message` -> `Part` (TextPart | ToolCallPart | ToolResultPart | FileChangePart)

All adapters implement the `SessionAdapter` ABC from `adapters/base.py`, which requires: `name`, `display_name`, `get_default_path()`, `is_available()`, `list_sessions()`, and `parse_session()`. Each adapter reads a tool's native format and converts it to `UnifiedSession`.

### Storage

Sessions are stored in `~/.sagg/`:
- `db.sqlite` - Metadata and FTS5 search index
- `sessions/` - Full session content as JSONL files

## Code Style

- Python 3.12+, Pydantic v2 for models
- Ruff for linting (line-length 100, rules: E/F/I/N/W/UP/B/C4/SIM, E501 ignored)
- MyPy strict mode enabled
- Pytest with `asyncio_mode = "auto"`
- Build backend: hatchling
