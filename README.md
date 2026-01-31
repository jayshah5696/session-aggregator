# Session Aggregator (sagg)

Unified AI Coding Session Aggregator - collect, search, and export sessions from multiple AI coding tools.

## Features

- **Multi-tool support**: Collect sessions from OpenCode, Claude Code, Codex CLI, Cursor, and Ampcode
- **Interactive TUI**: Browse sessions with a terminal UI (vim keybindings, search, export)
- **Unified format**: Normalize sessions into a consistent data model
- **Full-text search**: Search across all sessions with SQLite FTS5
- **AgentTrace export**: Export to the [AgentTrace](https://agent-trace.dev) standard format
- **Rich CLI**: Beautiful terminal output with Rich

## Supported Tools

| Tool | Status | Path |
|------|--------|------|
| OpenCode | Supported | `~/.local/share/opencode/storage/` |
| Claude Code | Supported | `~/.claude/projects/` |
| OpenAI Codex CLI | Supported | `~/.codex/sessions/` |
| Cursor | Supported | Platform-specific SQLite database |
| Ampcode | Supported | Cloud-based (capture via `--stream-json`) |

## Installation

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

### Cross-Platform Support (Windows, macOS, Linux)
`sagg` is designed to run on all major operating systems. Path detection for tool storage is handled automatically for each platform.

```bash
# Clone the repository
git clone https://github.com/yourusername/session-aggregator.git
cd session-aggregator

# Install with uv (for development)
uv sync

# Run the CLI
uv run sagg --help

# Or install globally with pip/pipx
pip install -e .
sagg --help
```

### Global Installation

To use `sagg` as a global command without `uv run`:

```bash
# Option 1: pipx (recommended for CLI tools)
pipx install -e /path/to/session-aggregator

# Option 2: pip in a virtualenv
pip install -e /path/to/session-aggregator

# Now use directly
sagg tui
sagg stats
```

## Contributing

We welcome contributions! Please see our [Technical Specification](spec.md) for architecture details.

1.  **Fork and Clone**: Fork the repo and clone locally.
2.  **Setup Environment**: Run `uv sync --extra dev` to install dependencies and test tools.
3.  **Run Tests**: Verify changes with `uv run pytest`.
4.  **Lint**: Ensure code quality with `uv run ruff check src/`.
5.  **Submit PR**: Open a Pull Request with your changes.

### Adding a New Adapter
To add support for a new tool:
1.  Create a new file in `src/sagg/adapters/`.
2.  Implement the `SessionAdapter` interface.
3.  Register it in `src/sagg/adapters/__init__.py`.
4.  Add tests in `tests/`.

## Quick Start

```bash
# Check which tools are available on your system
sagg sources

# Collect sessions from all available tools (last 7 days)
sagg collect --since 7d

# Launch the interactive TUI
sagg tui

# List recent sessions
sagg list

# Search for sessions
sagg search "authentication"

# Show session details
sagg show <session-id>

# Export to AgentTrace format
sagg export <session-id> --agenttrace

# View usage statistics
sagg stats
```

## Terminal UI (TUI)

Launch the interactive session browser:

```bash
sagg tui
```

### Layout

```
┌───────────────────────────┬─────────────────────────────────────────┐
│ [Search...              ] │ Conversation (18 messages)              │
├───────────────────────────┤─────────────────────────────────────────│
│ ▼ ai_experiments 2.6M     │ Fix authentication bug                  │
│   ▼ This Week (18)        │ opencode · ai_experiments · 2026-01-29  │
│     ▶ Fix auth bug...     │                                         │
│   ▶ This Month            │ ┃ USER  14:30:22                        │
│ ▼ backend-api 1.3M        │ ┃ The auth is failing with JWT error    │
│   ▼ Today (2)             │                                         │
│ ▶ frontend 800k           │ ┃ ASSISTANT  14:30:25  2.5k             │
│                           │ ┃ I'll investigate the issue...         │
│                           │                                         │
│                           │ ┌─ → read ──────────────────────────────┐
│                           │ │ {"path": "src/auth/handler.ts"}       │
│                           │ └───────────────────────────────────────┘
│                           │                                         │
├───────────────────────────┤ (scrollable conversation)               │
│ Total: 187 · 7.5M tokens  │                                         │
└───────────────────────────┴─────────────────────────────────────────┘
│ / search  Tab switch  j/k scroll  e export  ? help  q quit         │
```

**Features:**
- **Scrollable chat view** - All messages in one scrollable container
- **Two-panel layout** - Sessions on left, full conversation on right
- **Color-coded messages** - Blue=user, Green=assistant, Amber=tool
- **Tool calls inline** - Inputs and outputs shown with syntax highlighting
- **Live preview** - Conversation loads when you navigate sessions

### Keybindings

| Key | Action |
|-----|--------|
| `/` or type in search | Filter sessions |
| `j` / `k` or arrows | Navigate up/down |
| `Tab` / `Shift+Tab` | Switch panels |
| `1` / `2` / `3` | Focus specific panel |
| `Enter` | Select / expand |
| `e` | Export session |
| `r` | Refresh |
| `?` | Help |
| `q` | Quit |

## Commands

### `sagg tui`

Launch the interactive terminal UI for browsing sessions.

```bash
sagg tui
```

### `sagg sources`

List configured sources and their availability.

```bash
$ sagg sources
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Name     ┃ Display Name     ┃ Status    ┃ Path                   ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━┩
│ opencode │ OpenCode         │ Available │ ~/.local/share/...     │
│ claude   │ Claude Code      │ Available │ ~/.claude/projects     │
│ codex    │ OpenAI Codex CLI │ Available │ ~/.codex/sessions      │
│ cursor   │ Cursor           │ Available │ ~/Library/App...       │
└──────────┴──────────────────┴───────────┴────────────────────────┘
```

### `sagg collect`

Collect sessions from configured sources.

```bash
# Collect from all sources
sagg collect

# Collect from specific source
sagg collect --source opencode

# Collect only recent sessions
sagg collect --since 7d
sagg collect --since 2w
sagg collect --since 24h
```

### `sagg list`

List recent sessions.

```bash
# List recent sessions (default: 20)
sagg list

# Filter by source
sagg list --source claude

# Filter by project
sagg list --project myapp

# Limit results
sagg list --limit 50
```

### `sagg search`

Full-text search across sessions.

```bash
# Search for keyword
sagg search "authentication"

# Limit results
sagg search "database" --limit 10
```

### `sagg show`

Show session details.

```bash
# Show session (supports partial ID)
sagg show 019c0c59-d83

# Output as JSON
sagg show <session-id> --json
```

### `sagg export`

Export sessions to JSON or AgentTrace format.

```bash
# Export session as JSON
sagg export <session-id>

# Export in AgentTrace format
sagg export <session-id> --agenttrace

# Export to file
sagg export <session-id> --agenttrace -o trace.json

# Export all sessions
sagg export --all -o all-sessions.json
```

### `sagg stats`

Show usage statistics.

```bash
# Overall statistics
sagg stats

# Group by model
sagg stats --by model

# Group by source
sagg stats --by source
```

## Data Storage

Session data is stored in `~/.sagg/`:

```
~/.sagg/
├── db.sqlite              # Metadata and search index
└── sessions/              # Full session content (JSONL)
    ├── opencode/
    ├── claude/
    ├── codex/
    └── cursor/
```

## AgentTrace Integration

[AgentTrace](https://agent-trace.dev) is an open specification for tracking AI-generated code. Export sessions to this format for interoperability:

```bash
sagg export <session-id> --agenttrace
```

Example output:

```json
{
  "version": "0.1.0",
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-01-29T14:30:00Z",
  "tool": {
    "name": "opencode",
    "version": "1.0.0"
  },
  "files": [
    {
      "path": "src/auth/handler.ts",
      "conversations": [
        {
          "url": "local://session/ses_abc123",
          "contributor": {
            "type": "ai",
            "model_id": "anthropic/claude-opus-4-5"
          }
        }
      ]
    }
  ]
}
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                           sagg CLI                               │
├─────────────────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    Adapter Layer                           │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │  │
│  │  │ OpenCode │ │  Claude  │ │  Codex   │ │  Cursor  │      │  │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘      │  │
│  └───────┼────────────┼────────────┼────────────┼────────────┘  │
│          └────────────┴─────┬──────┴────────────┘               │
│                             ▼                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Unified Session Store (SQLite)                │  │
│  └───────────────────────────────────────────────────────────┘  │
│                             │                                    │
│          ┌──────────────────┼──────────────────┐                │
│          ▼                  ▼                  ▼                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Exporter   │  │    Search    │  │  Statistics  │          │
│  │ (AgentTrace) │  │   (FTS5)     │  │  (Analytics) │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

## Development

```bash
# Install dev dependencies
uv sync --extra dev

# Run linting
uv run ruff check src/

# Run type checking
uv run mypy src/

# Run tests
uv run pytest
```

## Project Structure

```
session-aggregator/
├── pyproject.toml          # Project configuration
├── README.md               # This file
├── research.md             # Research findings
├── spec.md                 # Technical specification
├── todo.md                 # Progress tracking
├── src/sagg/
│   ├── __init__.py         # Package exports
│   ├── cli.py              # CLI commands (Click)
│   ├── models.py           # Pydantic data models
│   ├── adapters/
│   │   ├── __init__.py     # Adapter registry
│   │   ├── base.py         # Base adapter interface
│   │   ├── opencode.py     # OpenCode adapter
│   │   ├── claude.py       # Claude Code adapter
│   │   ├── codex.py        # Codex CLI adapter
│   │   ├── cursor.py       # Cursor adapter
│   │   └── ampcode.py      # Ampcode adapter
│   ├── storage/
│   │   ├── __init__.py     # Storage exports
│   │   ├── db.py           # Database management
│   │   └── store.py        # Session store
│   ├── export/
│   │   ├── __init__.py     # Export exports
│   │   └── agenttrace.py   # AgentTrace exporter
│   └── tui/
│       ├── __init__.py     # TUI exports
│       ├── app.py          # Main Textual app
│       ├── styles.tcss     # Textual CSS styling
│       └── widgets/        # UI components
└── tests/                  # Test files
```

## License

MIT

## Related Projects

- [AgentTrace](https://agent-trace.dev) - Open specification for tracking AI-generated code
- [Langfuse](https://github.com/langfuse/langfuse) - Open source LLM observability
- [OpenLLMetry](https://github.com/traceloop/openllmetry) - OpenTelemetry for LLMs
- [Agent Prism](https://github.com/evilmartians/agent-prism) - React components for trace visualization
