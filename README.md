# Session Aggregator (sagg)

Unified AI Coding Session Aggregator - collect, search, and export sessions from multiple AI coding tools.

## Features

- **Multi-tool support**: Collect sessions from OpenCode, Claude Code, Codex CLI, Cursor, Gemini CLI, and Ampcode
- **Interactive TUI**: Browse sessions with a terminal UI (vim keybindings, search, export)
- **Unified format**: Normalize sessions into a consistent data model
- **Full-text search**: Search across all sessions with SQLite FTS5
- **AgentTrace export**: Export to the [AgentTrace](https://agent-trace.dev) standard format
- **Rich CLI**: Beautiful terminal output with Rich

### New in v1.3

- **`sagg analyze-sessions`** (v2): Extensible 10-extractor pipeline producing ~40 attributes per session — tool call stats, error analysis, user intervention detection, timing, conversation patterns, and more
- **`sagg insights --format html`**: Standalone HTML report with inline CSS, dark mode, CSS bar charts, and copy buttons — no external dependencies
- **`sagg insights`**: Cross-tool usage insights report — compare Claude vs Cursor vs OpenCode effectiveness
- **LLM via CLI tools**: Uses `claude -p`, `codex`, or `gemini` CLI for analysis — no SDK dependencies
- **AGENTS.md suggestions**: Auto-detect friction patterns and suggest config additions per tool

### New in v1.1

- **`sagg sync --watch`**: Live filesystem watching for automatic session collection
- **`sagg oracle`**: "Have I solved this before?" - semantic search through your history
- **`sagg similar`**: Find sessions similar to a query using TF-IDF
- **`sagg heatmap`**: GitHub-style contribution heatmap of your AI usage
- **`sagg budget`**: Token budget tracking with visual alerts
- **`sagg git-link`**: Associate sessions with git commits by timestamp
- **`sagg friction-points`**: Detect sessions with excessive retries or errors
- **`sagg bundle export/import`**: Portable session bundles for multi-machine sync
- **Config file**: Customize paths and settings via `~/.sagg/config.toml`

## Supported Tools

| Tool | Status | Path |
|------|--------|------|
| OpenCode | Supported | `~/.local/share/opencode/storage/` |
| Claude Code | Supported | `~/.claude/projects/` |
| OpenAI Codex CLI | Supported | `~/.codex/sessions/` |
| Cursor | Supported | Platform-specific SQLite database |
| Gemini CLI | Supported | `~/.gemini/tmp/` |
| Ampcode | Supported | Cloud-based (capture via `--stream-json`) |

## Installation

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

### Cross-Platform Support (Windows, macOS, Linux)
`sagg` is designed to run on all major operating systems. Path detection for tool storage is handled automatically for each platform.

```bash
# Clone the repository
git clone https://github.com/jayshah5696/session-aggregator.git
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

# "Have I solved this before?" - semantic history search
sagg oracle "rate limiting"

# Show session details
sagg show <session-id>

# View usage statistics and activity heatmap
sagg stats
sagg heatmap

# Export to AgentTrace format
sagg export <session-id> --agenttrace

# Set a weekly token budget
sagg budget set --weekly 500k

# Watch for new sessions in real-time
sagg sync --watch

# Analyze sessions and generate cross-tool insights
sagg analyze-sessions --since 30d
sagg insights
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

### `sagg sync`

Incremental sync with optional live watching.

```bash
# One-time incremental sync
sagg sync

# Watch for changes continuously
sagg sync --watch

# Sync specific source only
sagg sync --source opencode

# Preview what would be synced
sagg sync --dry-run
```

### `sagg oracle`

Search your history: "Have I solved this before?"

```bash
# Find sessions related to a query
sagg oracle "rate limiting"

# Limit results
sagg oracle "authentication" --top 5

# Show full snippets
sagg oracle "fix TypeError" --verbose
```

### `sagg similar`

Find sessions similar to a query or another session.

```bash
# Find similar by query
sagg similar "implement authentication"

# Find similar to an existing session
sagg similar --session <session-id>

# Limit results
sagg similar "API design" --top 10
```

### `sagg heatmap`

Display a GitHub-style activity heatmap.

```bash
# Show last 12 weeks (default)
sagg heatmap

# Custom time range
sagg heatmap --weeks 24

# Color by token usage instead of session count
sagg heatmap --by tokens
```

### `sagg budget`

Token budget tracking with alerts.

```bash
# Set budgets
sagg budget set --weekly 500k
sagg budget set --daily 100k

# Show current usage vs budget
sagg budget show

# Clear budgets
sagg budget clear --weekly
```

### `sagg git-link`

Associate sessions with git commits.

```bash
# Show sessions with linked commits
sagg git-link

# Filter by project
sagg git-link --project myapp

# Update session git info
sagg git-link --update
```

### `sagg analyze-sessions`

Extract structured facets from sessions for insights analysis.

```bash
# Analyze with heuristic (free, no LLM needed)
sagg analyze-sessions --since 30d

# Use LLM for higher quality (auto-detects claude/codex/gemini CLI)
sagg analyze-sessions --analyzer llm

# Re-analyze already analyzed sessions
sagg analyze-sessions --since 7d --force

# Preview what would be analyzed
sagg analyze-sessions --dry-run
```

### `sagg insights`

Generate cross-tool usage insights report. Requires `analyze-sessions` first.

```bash
# CLI summary report
sagg insights

# Compare specific tools
sagg insights --source claude --source cursor

# Generate standalone HTML report
sagg insights --format html -o report.html

# Export as JSON
sagg insights --format json -o report.json

# Detailed breakdown
sagg insights --verbose
```

### `sagg friction-points`

Detect sessions with excessive back-and-forth.

```bash
# Show friction points
sagg friction-points

# Filter by time
sagg friction-points --since 7d

# Custom retry threshold
sagg friction-points --threshold 5
```

### `sagg bundle`

Export and import portable session bundles.

```bash
# Export sessions to bundle
sagg bundle export -o my-sessions.sagg
sagg bundle export --since 7d --project myapp -o weekly.sagg

# Import from bundle
sagg bundle import my-sessions.sagg
sagg bundle import backup.sagg --dry-run

# Verify bundle integrity
sagg bundle verify my-sessions.sagg
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
├── spec.md                 # Technical specification
├── src/sagg/
│   ├── __init__.py         # Package exports
│   ├── cli.py              # CLI commands (Click)
│   ├── models.py           # Pydantic data models
│   ├── config.py           # Configuration management
│   ├── sync.py             # Session synchronization
│   ├── bundle.py           # Export/import bundles
│   ├── git_utils.py        # Git integration utilities
│   ├── adapters/           # Source tool adapters
│   │   ├── opencode.py     # OpenCode adapter
│   │   ├── claude.py       # Claude Code adapter
│   │   ├── codex.py        # Codex CLI adapter
│   │   ├── cursor.py       # Cursor adapter
│   │   └── ampcode.py      # Ampcode adapter
│   ├── storage/            # Data persistence
│   │   ├── db.py           # Database management
│   │   └── store.py        # Session store
│   ├── export/             # Export formats
│   │   ├── agenttrace.py   # AgentTrace exporter
│   │   ├── html_report.py  # Standalone HTML insights report
│   │   └── markdown.py     # Markdown exporter
│   ├── analytics/          # Analysis features
│   │   ├── oracle.py       # History search
│   │   ├── similar.py      # Similarity matching
│   │   ├── friction.py     # Friction detection
│   │   ├── heatmap.py      # Activity heatmap
│   │   └── insights/       # Insights pipeline
│   │       ├── extractors.py  # V2 10-extractor pipeline
│   │       ├── heuristic.py   # V1 heuristic analyzer
│   │       ├── cli_llm.py     # LLM analyzer via CLI tools
│   │       ├── aggregator.py  # Report aggregation
│   │       └── models.py      # Facet/report data models
│   ├── security/           # Data protection
│   │   └── scrubber.py     # Sensitive data redaction
│   └── tui/                # Terminal UI
│       ├── app.py          # Main Textual app
│       └── widgets/        # UI components
└── tests/                  # Test files (380+ tests)
```

## License

MIT

## Related Projects

- [AgentTrace](https://agent-trace.dev) - Open specification for tracking AI-generated code
- [Langfuse](https://github.com/langfuse/langfuse) - Open source LLM observability
- [OpenLLMetry](https://github.com/traceloop/openllmetry) - OpenTelemetry for LLMs
- [Agent Prism](https://github.com/evilmartians/agent-prism) - React components for trace visualization
