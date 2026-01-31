# Session Aggregator - Technical Specification

**Project**: Unified AI Coding Session Aggregator  
**Version**: 0.1.0  
**Date**: January 29, 2026  
**Status**: Draft

---

## 1. Overview

### 1.1 Problem Statement

Developers using multiple AI coding tools (OpenCode, Claude Code, Codex, Antigravity, Cursor) have session data scattered across different locations in incompatible formats. There is no unified way to:
- View all sessions in one place
- Search across sessions from different tools
- Convert sessions to a standard format (AgentTrace)
- Track metadata (project, duration, models used, token costs)
- Analyze patterns across coding sessions

### 1.2 Solution

Build **Session Aggregator** (`sagg`), a CLI tool and viewer that:
1. **Collects** sessions from multiple AI coding tools
2. **Normalizes** them to a unified internal format
3. **Stores** them in a searchable local database
4. **Exports** to AgentTrace format
5. **Provides** a web-based viewer for browsing and searching

### 1.3 Non-Goals (v1)

- Real-time sync (batch collection only)
- Cloud storage or multi-device sync
- Modification of original session files
- Full AgentTrace line-level attribution (requires git integration)

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                              sagg CLI                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                      Adapter Layer                              │ │
│  │                                                                  │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐│ │
│  │  │ OpenCode │ │  Claude  │ │  Codex   │ │  Cursor  │ │Antigrav││ │
│  │  │ Adapter  │ │  Adapter │ │  Adapter │ │  Adapter │ │ Adapter││ │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘│ │
│  └───────┼────────────┼────────────┼────────────┼───────────┼─────┘ │
│          │            │            │            │           │       │
│          └────────────┴─────┬──────┴────────────┴───────────┘       │
│                             ▼                                        │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    Unified Session Model                        │ │
│  │                                                                  │ │
│  │  Session → Turn → Message → Part (text | tool_call | tool_result)│
│  └────────────────────────────────────────────────────────────────┘ │
│                             │                                        │
│                             ▼                                        │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                      Storage Layer                              │ │
│  │                                                                  │ │
│  │  ~/.sagg/                                                        │ │
│  │  ├── db.sqlite          # Metadata, search index                │ │
│  │  ├── sessions/          # Full session content (JSONL)          │ │
│  │  └── exports/           # AgentTrace exports                    │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                             │                                        │
│          ┌──────────────────┼──────────────────┐                    │
│          ▼                  ▼                  ▼                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │   Exporter   │  │    Viewer    │  │    Search    │              │
│  │ (AgentTrace) │  │  (Web UI)    │  │   (FTS5)     │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Model

### 3.1 Unified Session Schema

```typescript
interface UnifiedSession {
  // Identity
  id: string;                    // UUID v7 (time-sortable)
  source: SourceTool;            // 'opencode' | 'claude' | 'codex' | 'cursor' | 'antigravity'
  sourceId: string;              // Original session ID
  sourcePath: string;            // Original file path
  
  // Metadata
  title: string;
  projectPath: string;
  projectName: string;           // Derived from path
  
  // Git context (if available)
  git?: {
    branch: string;
    commit: string;
    remote?: string;
  };
  
  // Timing
  createdAt: Date;
  updatedAt: Date;
  durationMs?: number;
  
  // Stats
  stats: {
    turnCount: number;
    messageCount: number;
    inputTokens: number;
    outputTokens: number;
    toolCallCount: number;
    filesModified: string[];
  };
  
  // Model info
  models: ModelUsage[];
  
  // Content
  turns: Turn[];
}

interface Turn {
  id: string;
  index: number;
  startedAt: Date;
  endedAt?: Date;
  messages: Message[];
}

interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  timestamp: Date;
  model?: string;
  parts: Part[];
  usage?: TokenUsage;
}

type Part = 
  | { type: 'text'; content: string }
  | { type: 'tool_call'; toolName: string; toolId: string; input: unknown }
  | { type: 'tool_result'; toolId: string; output: string; isError: boolean }
  | { type: 'file_change'; path: string; diff?: string };

interface ModelUsage {
  modelId: string;              // models.dev format: provider/model
  provider: string;
  messageCount: number;
  inputTokens: number;
  outputTokens: number;
}

interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  cachedTokens?: number;
}

type SourceTool = 'opencode' | 'claude' | 'codex' | 'cursor' | 'ampcode' | 'antigravity';
```

### 3.2 SQLite Schema (Metadata + Search)

```sql
-- Sessions table (metadata for fast queries)
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_path TEXT NOT NULL,
  title TEXT,
  project_path TEXT,
  project_name TEXT,
  git_branch TEXT,
  git_commit TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  duration_ms INTEGER,
  turn_count INTEGER DEFAULT 0,
  message_count INTEGER DEFAULT 0,
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  tool_call_count INTEGER DEFAULT 0,
  models_json TEXT,              -- JSON array of model IDs used
  files_modified_json TEXT,      -- JSON array of file paths
  imported_at INTEGER NOT NULL,
  UNIQUE(source, source_id)
);

-- Full-text search index
CREATE VIRTUAL TABLE sessions_fts USING fts5(
  title,
  project_name,
  content,                       -- Extracted text from all messages
  content=sessions,
  content_rowid=rowid
);

-- Models used (for filtering/analytics)
CREATE TABLE session_models (
  session_id TEXT NOT NULL REFERENCES sessions(id),
  model_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  message_count INTEGER DEFAULT 0,
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  PRIMARY KEY (session_id, model_id)
);

-- Tool calls (for analytics)
CREATE TABLE session_tools (
  session_id TEXT NOT NULL REFERENCES sessions(id),
  tool_name TEXT NOT NULL,
  call_count INTEGER DEFAULT 0,
  PRIMARY KEY (session_id, tool_name)
);

-- Indexes
CREATE INDEX idx_sessions_source ON sessions(source);
CREATE INDEX idx_sessions_project ON sessions(project_path);
CREATE INDEX idx_sessions_created ON sessions(created_at DESC);
CREATE INDEX idx_sessions_updated ON sessions(updated_at DESC);
```

### 3.3 Session Content Storage

Full session content stored as JSONL files:
```
~/.sagg/sessions/<source>/<session-id>.jsonl
```

Each line is a `Message` object serialized as JSON.

---

## 4. CLI Interface

### 4.1 Commands

```bash
# Collection
sagg collect                      # Collect from all sources
sagg collect --source opencode    # Collect from specific source
sagg collect --since 7d           # Only sessions from last 7 days
sagg collect --watch              # Watch for new sessions

# Listing & Search
sagg list                         # List recent sessions
sagg list --source claude         # Filter by source
sagg list --project myapp         # Filter by project
sagg list --model claude-opus     # Filter by model
sagg search "authentication"      # Full-text search

# Viewing
sagg show <session-id>            # Show session details
sagg show <session-id> --json     # Output as JSON
sagg show <session-id> --messages # Show all messages

# Export
sagg export <session-id>          # Export to AgentTrace JSON
sagg export --all --format agenttrace
sagg export --project myapp --output ./traces/

# Analytics
sagg stats                        # Usage statistics
sagg stats --by model             # Group by model
sagg stats --by project           # Group by project
sagg stats --since 30d            # Time range

# Viewer
sagg serve                        # Start web viewer on localhost:3000
sagg serve --port 8080            # Custom port

# Management
sagg sources                      # List configured sources
sagg sources add --type cursor --path "..."
sagg prune --older-than 90d       # Remove old sessions
sagg reset                        # Reset database
```

### 4.2 Configuration

```toml
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
# macOS default
path = "~/Library/Application Support/Cursor/User/globalStorage/state.vscdb"

[sources.antigravity]
enabled = false  # Format not documented yet
path = "~/.gemini/antigravity"

[viewer]
port = 3000
open_browser = true

[export]
default_format = "agenttrace"
output_dir = "~/.sagg/exports"
```

---

## 5. Adapter Specifications

### 5.1 Adapter Interface

```typescript
interface SessionAdapter {
  readonly name: SourceTool;
  readonly displayName: string;
  
  // Check if source is available
  isAvailable(): Promise<boolean>;
  
  // Get default path for this platform
  getDefaultPath(): string;
  
  // List all session IDs with their timestamps
  listSessions(since?: Date): AsyncGenerator<SessionRef>;
  
  // Parse a session into unified format
  parseSession(ref: SessionRef): Promise<UnifiedSession>;
  
  // Check if session has been modified since last import
  hasChanged(ref: SessionRef, lastImport: Date): Promise<boolean>;
}

interface SessionRef {
  id: string;
  path: string;
  createdAt: Date;
  updatedAt: Date;
}
```

### 5.2 OpenCode Adapter

**Input**: `~/.local/share/opencode/storage/`

```typescript
class OpenCodeAdapter implements SessionAdapter {
  async *listSessions(since?: Date) {
    // Read project/*.json to get project paths
    // For each project, read session/<project-id>/*.json
    // Yield SessionRef for each session file
  }
  
  async parseSession(ref: SessionRef) {
    // Read session JSON
    // Read all messages from message/<session-id>/*.json
    // Read all parts from part/<message-id>/*.json
    // Assemble into UnifiedSession
  }
}
```

**Mapping**:
| OpenCode | Unified |
|----------|---------|
| `ses_*` | `sourceId` |
| `projectID` | Lookup project path |
| `msg_*.role` | `message.role` |
| `prt_*.type: text` | `part.type: text` |
| `prt_*.type: tool` | `part.type: tool_call` or `tool_result` |

### 5.3 Claude Code Adapter

**Input**: `~/.claude/projects/<encoded-path>/*.jsonl`

```typescript
class ClaudeCodeAdapter implements SessionAdapter {
  async *listSessions(since?: Date) {
    // Glob ~/.claude/projects/*/*.jsonl
    // Skip agent-*.jsonl (subagents)
    // Parse first line to get session metadata
  }
  
  async parseSession(ref: SessionRef) {
    // Read JSONL file line by line
    // Group entries by parentUuid to form turns
    // Extract message content from entries
  }
}
```

**Mapping**:
| Claude Code | Unified |
|-------------|---------|
| `sessionId` | `sourceId` |
| `cwd` | `projectPath` |
| `gitBranch` | `git.branch` |
| Entry `type: user` | `message.role: user` |
| Entry `type: assistant` | `message.role: assistant` |
| `tool_use` content | `part.type: tool_call` |
| Entry `type: tool_result` | `part.type: tool_result` |

### 5.4 Codex Adapter

**Input**: `~/.codex/sessions/`

```typescript
class CodexAdapter implements SessionAdapter {
  async *listSessions(since?: Date) {
    // Read session files from ~/.codex/sessions/
  }
  
  async parseSession(ref: SessionRef) {
    // Parse JSONL events
    // thread.started → session start
    // turn.started/completed → turn boundaries
    // item.* → messages and parts
  }
}
```

**Mapping**:
| Codex | Unified |
|-------|---------|
| `thread_id` | `sourceId` |
| `item.type: agent_message` | `message.role: assistant`, `part.type: text` |
| `item.type: command_execution` | `part.type: tool_call` (tool: bash) |
| `usage.input_tokens` | `usage.inputTokens` |

### 5.5 Cursor Adapter

**Input**: `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`

```typescript
class CursorAdapter implements SessionAdapter {
  async *listSessions(since?: Date) {
    // Open SQLite database
    // Query cursorDiskKV for composerData:* keys
    // Parse JSON values to get session metadata
  }
  
  async parseSession(ref: SessionRef) {
    // Query composerData:<id>
    // Parse conversation array
    // Extract bubble content
  }
}
```

**Mapping**:
| Cursor | Unified |
|--------|---------|
| `composerId` | `sourceId` |
| `conversation[].type: 1` | `message.role: user` |
| `conversation[].type: 2` | `message.role: assistant` |
| `context.fileSelections` | Associated files |

### 5.6 Ampcode Adapter

**Input**: Cloud-based (Sourcegraph Amp), captured via `amp --stream-json`

**Architecture Decision**: Ampcode uses a **cloud-first architecture** - sessions are stored on ampcode.com servers, not locally. This adapter uses a **capture-based approach**:

1. Users capture sessions: `amp --execute "prompt" --stream-json > ~/.sagg/cache/ampcode/session.jsonl`
2. Adapter reads from cache directory: `~/.sagg/cache/ampcode/*.jsonl`

**Availability Detection**:
- Check for `amp` CLI in PATH
- Check for `~/.local/share/amp/secrets.json` (credentials)
- Check for cached sessions in `~/.sagg/cache/ampcode/`

**Stream JSON Format**:
```typescript
type AmpMessage =
  | { type: "system"; subtype: "init"; cwd: string; session_id: string; tools: string[] }
  | { type: "assistant"; message: { role: "assistant"; content: ContentBlock[]; usage?: Usage }; session_id: string }
  | { type: "user"; message: { role: "user"; content: ToolResult[] }; session_id: string }
  | { type: "result"; subtype: "success" | "error_*"; duration_ms: number; session_id: string; usage?: Usage }
```

**Mapping**:
| Ampcode | Unified |
|---------|---------|
| `session_id` (T-{uuid}) | `sourceId` |
| `cwd` from init | `projectPath` |
| `type: assistant` | `message.role: assistant` |
| `content[].type: tool_use` | `part.type: tool_call` |
| `content[].type: tool_result` | `part.type: tool_result` |
| `duration_ms` | `durationMs` |

**Key Differences**:
- No per-message timestamps (only `duration_ms` in result)
- No model info per message (assumes Anthropic models)
- Session IDs prefixed with `T-`

### 5.7 Antigravity Adapter (Research Only)

**Status**: **DEPRIORITIZED**. Research indicates high risk due to proprietary binary formats.

**Risk Assessment (Extreme)**:
- **Critique**: Reverse-engineering Google's internal Protobuf formats is a massive time sink. Unless Antigravity becomes a dominant market leader, this is not worth the v1 engineering effort.
- **Decision**: Wait for Google to publish official export functionality or an API. Keep in "Research" status for now.

**What is Antigravity**: Google's AI-powered IDE (VS Code fork), available at https://antigravity.google. Released November 2025 in public preview. Uses Gemini 3 Pro, Claude Sonnet 4.5, and GPT-OSS 120B models.

**Input**: `~/.gemini/antigravity/`

**Storage Structure**:
```
~/.gemini/antigravity/
├── brain/                       # Task artifacts by session UUID
│   └── <session-uuid>/
│       ├── task.md              # Task list (markdown)
│       ├── task.md.metadata.json # Task metadata (JSON)
│       └── implementation_plan.md
├── conversations/               # Conversation history (binary protobuf)
│   └── <session-uuid>.pb
├── code_tracker/                # Code changes tracking
│   ├── active/<project_hash>/
│   └── history/
└── user_settings.pb             # User settings (protobuf binary)
```

**Challenges**:
| Challenge | Details |
|-----------|---------|
| Binary Conversations | Main conversation data is Protocol Buffers (`.pb`) with unknown schema |
| No JSONL | Unlike other tools, doesn't use human-readable message format |
| Schema Unknown | No public `.proto` files for the binary formats |

**Feasible Extraction (Partial)**:
- Parse `brain/<uuid>/*.metadata.json` for session metadata (timestamps, summaries)
- Extract task lists from `brain/<uuid>/task.md`
- Extract implementation plans from `brain/<uuid>/implementation_plan.md`
- Map to projects via `code_tracker/active/` directory names

**Full Implementation Requires**:
- Reverse-engineering the `.pb` schema
- Or intercepting the local HTTP API while Antigravity is running
- Or waiting for Google to publish official export functionality

---

## 6. AgentTrace Export

### 6.1 Export Logic

```typescript
function exportToAgentTrace(session: UnifiedSession): AgentTraceRecord {
  return {
    version: "0.1.0",
    id: uuidv4(),
    timestamp: session.updatedAt.toISOString(),
    vcs: session.git ? {
      type: "git",
      revision: session.git.commit
    } : undefined,
    tool: {
      name: session.source,
      version: "unknown"  // Could be extracted if available
    },
    files: extractFileContributions(session),
    metadata: {
      source_session_id: session.sourceId,
      project_path: session.projectPath,
      duration_ms: session.durationMs,
      token_usage: {
        input: session.stats.inputTokens,
        output: session.stats.outputTokens
      }
    }
  };
}

function extractFileContributions(session: UnifiedSession): AgentTraceFile[] {
  // Group file changes by path
  // For each file, create conversation entries
  // Note: Line-level ranges require git diff analysis (future work)
  
  const files = new Map<string, AgentTraceFile>();
  
  for (const turn of session.turns) {
    for (const message of turn.messages) {
      for (const part of message.parts) {
        if (part.type === 'file_change') {
          // Add to files map with conversation reference
        }
      }
    }
  }
  
  return Array.from(files.values());
}
```

### 6.2 Limitations

AgentTrace requires line-level attribution which needs:
1. Git commit SHA at time of change
2. Diff analysis to determine exact lines
3. Content hashing for tracking

**v1 Scope**: Export session-level attribution only (files touched, models used). Line-level attribution deferred to v2.

---

## 7. Viewer Specification

### 7.1 Technology Stack

- **Framework**: React 19 + TypeScript
- **Build**: Vite
- **Styling**: Tailwind CSS v4
- **Components**: Agent Prism (for trace visualization)
- **Backend**: Embedded HTTP server (Go or Rust)
- **Data**: SQLite queries via REST API

### 7.2 Views

#### Session List View
```
┌─────────────────────────────────────────────────────────────────┐
│ Session Aggregator                          [Search...] [Filter]│
├─────────────────────────────────────────────────────────────────┤
│ Filters: [All Sources ▼] [All Projects ▼] [Last 7 days ▼]     │
├─────────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ [OC] Implement user authentication                          │ │
│ │ myapp • claude-opus-4 • 45 turns • 2h ago                   │ │
│ └─────────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ [CC] Fix database connection pool                           │ │
│ │ backend-api • claude-sonnet-4 • 12 turns • 5h ago           │ │
│ └─────────────────────────────────────────────────────────────┘ │
│ ...                                                             │
└─────────────────────────────────────────────────────────────────┘
```

Source badges: `[OC]` OpenCode, `[CC]` Claude Code, `[CX]` Codex, `[CU]` Cursor

#### Session Detail View
```
┌─────────────────────────────────────────────────────────────────┐
│ ← Back    Implement user authentication         [Export] [Copy] │
├─────────────────────────────────────────────────────────────────┤
│ Source: OpenCode  Project: /Users/dev/myapp  Branch: feature/auth│
│ Duration: 45min  Tokens: 125k in / 48k out  Models: claude-opus-4│
├──────────────────────────────────┬──────────────────────────────┤
│ Timeline                         │ Files Modified               │
│ ┌──────────────────────────────┐ │ src/auth/handler.ts         │
│ │ ████░░░░░░░░░░░░░░░░░░░░░░░░ │ │ src/auth/middleware.ts      │
│ └──────────────────────────────┘ │ src/db/users.ts             │
├──────────────────────────────────┴──────────────────────────────┤
│ Conversation                                                     │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 👤 User                                                      │ │
│ │ Help me implement JWT authentication for the API            │ │
│ └─────────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 🤖 Assistant (claude-opus-4)                                │ │
│ │ I'll help you implement JWT authentication...               │ │
│ │ [Tool: read_file] src/auth/handler.ts                       │ │
│ │ [Tool: write_file] src/auth/middleware.ts                   │ │
│ └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

#### Analytics View
```
┌─────────────────────────────────────────────────────────────────┐
│ Analytics                                    [Last 30 days ▼]   │
├─────────────────────────────────────────────────────────────────┤
│ Sessions by Source          │ Token Usage by Model              │
│ ┌─────────────────────────┐ │ ┌─────────────────────────────┐   │
│ │ OpenCode    ████████ 45 │ │ │ claude-opus     ████████ 2M │   │
│ │ Claude Code ██████ 32   │ │ │ claude-sonnet   █████ 1.2M  │   │
│ │ Cursor      ███ 18      │ │ │ gpt-4o          ██ 400k     │   │
│ │ Codex       █ 5         │ │ └─────────────────────────────┘   │
│ └─────────────────────────┘ │                                   │
├─────────────────────────────┴───────────────────────────────────┤
│ Sessions Over Time                                              │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │     ▄▄    ▄▄▄▄                  ▄▄▄▄▄▄▄▄                    │ │
│ │ ▄▄▄████▄▄██████▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄████████████▄▄▄              │ │
│ └─────────────────────────────────────────────────────────────┘ │
│ Jan 1                        Jan 15                      Jan 29 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. Implementation Plan

### Phase 1: Core CLI (2 weeks)

**Week 1**:
- [ ] Project setup (Python with uv, or Rust)
- [ ] Config file parsing
- [ ] Unified session model types
- [ ] SQLite schema and migrations
- [ ] OpenCode adapter implementation
- [ ] Claude Code adapter implementation

**Week 2**:
- [ ] Codex adapter implementation
- [ ] Cursor adapter implementation
- [ ] `sagg collect` command
- [ ] `sagg list` and `sagg show` commands
- [ ] Basic tests

### Phase 2: Search & Export (1 week)

- [ ] Full-text search with FTS5
- [ ] `sagg search` command
- [ ] AgentTrace export logic
- [ ] `sagg export` command
- [ ] `sagg stats` command

### Phase 3: Viewer (2 weeks)

**Week 1**:
- [ ] Embedded HTTP server
- [ ] REST API endpoints
- [ ] React app scaffold with Vite
- [ ] Session list view
- [ ] Search integration

**Week 2**:
- [ ] Session detail view
- [ ] Analytics dashboard
- [ ] Agent Prism integration for trace visualization
- [ ] Polish and testing

### Phase 4: Polish (1 week)

- [ ] Watch mode for live collection
- [ ] Documentation
- [ ] Homebrew/cargo/pip packaging
- [ ] GitHub release

---

## 9. Technology Choices

### 9.1 CLI Language Options

| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| **Python** | Fast dev, good libs, cross-platform | Packaging complexity, runtime needed | Good for v1 |
| **Rust** | Fast, single binary, SQLite support | Slower dev, steeper curve | Best for distribution |
| **Go** | Good balance, single binary | Less ecosystem for this domain | Alternative to Rust |
| **TypeScript** | Share code with viewer | Node runtime, slower startup | Not recommended |

**Recommendation**: Start with **Python + uv** for rapid development, consider Rust port later if distribution becomes a priority.

### 9.2 Viewer Technology

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Framework | React 19 | Agent Prism requires it |
| Build | Vite | Fast, standard |
| Styling | Tailwind v4 | Matches Agent Prism |
| State | Zustand | Simple, performant |
| HTTP | Built-in fetch | No additional deps |
| Embedding | Tauri or PyWebView | Bundle with CLI |

---

## 10. Open Questions

1. **Antigravity format**: Need access to actual session files to reverse-engineer format
2. **Line-level attribution**: Defer to v2 or implement basic git diff analysis?
3. **Real-time updates**: Filesystem watcher vs polling?
4. **Multi-user**: Is shared access needed? (probably not for v1)
5. **Remote sessions**: SSH/container sessions stored differently?

---

## 11. Success Criteria

### MVP (v0.1) - COMPLETED
- [x] Collect sessions from OpenCode, Claude Code, Codex, Cursor
- [x] Search across all sessions (FTS5 full-text search)
- [x] Export to AgentTrace format
- [x] TUI viewer with session tree and scrollable chat (`sagg tui`)

### v1.0 - IN PROGRESS
- [x] All MVP features stable
- [x] Analytics via `sagg stats` command
- [ ] Watch mode for live collection
- [ ] Installable via Homebrew/pip
- [x] Basic documentation (README, spec.md)

### v1.1 - PLANNED (Sync & Portability)
- [ ] `sagg sync` - Incremental sync with watch mode
- [ ] `sagg export` / `sagg import` - Multi-machine session portability
- [ ] Cost tracking with pricing data

### v1.2 - PLANNED (Analytics)
- [ ] `sagg analyze` - Query clustering and topic modeling
- [ ] TUI analytics dashboard with visualizations
- [ ] `sagg skill-suggestions` - Auto-generate skills, commands, hooks, agents

### Future
- [ ] Session replay/debugging mode
- [ ] Line-level AgentTrace attribution with git integration
- [ ] Antigravity adapter (requires protobuf reverse-engineering)
- [ ] Session comparison/diff
- [ ] Web UI (`sagg serve`) with FastAPI + HTMX
- [ ] Team sharing and collaboration

---

## 12. Adapter Status

| Adapter | Status | Project Extraction | Title Extraction | Model Tracking |
|---------|--------|-------------------|------------------|----------------|
| OpenCode | Working | From `session.directory` | From `session.title` | Full (per-message) |
| Claude Code | Working | From `cwd` | From context | Full (per-message) |
| Codex | Working | From `session_meta.cwd` | From first user message | Provider only |
| Cursor | Working | From `fileSelections.uri.path` | From first user message | Not available |
| Ampcode | Working | From `system.init.cwd` | From first user message | Limited |
| Antigravity | Research Complete | From `brain/` artifacts | From `task.md.metadata.json` | Limited (quota API) |

### Known Limitations

**Codex**:
- Legacy format sessions (pre-0.63.0) have no `session_meta`, so no project/model info
- Model ID not available, only provider (shows as `openai/codex`)

**Cursor**:
- Project path derived from file selections (may be inaccurate for large projects)
- Messages stored in separate `bubbleId:` keys, not in `conversation` array
- No timestamps on individual messages (uses session timestamp)
- Empty sessions (no bubbles) have no project/title info

---

## 13. Feature Roadmap (v1.1+)

### 13.1 `sagg sync` - Incremental Synchronization

**CLI Interface:**
```bash
sagg sync [OPTIONS]

Options:
  -s, --source TEXT      Sync specific source only
  --full                 Force full rescan (ignore sync state)
  --dry-run              Show what would be synced without making changes
  -v, --verbose          Show detailed progress
  
Watch Mode:
  --watch, -w            Watch for changes and sync continuously
  --debounce INTEGER     Debounce interval in ms (default: 2000)
```

**Technical Approach:**
- **Timestamp-based detection**: Use file mtime for new/updated files
- **Per-source sync state**: Store `last_sync_at`, `cursor`, `session_count` in SQLite
- **Watch mode**: Use `watchfiles` library (Rust-backed, cross-platform)
- **Debouncing**: 500ms for OpenCode/Codex, 2000ms for Cursor (SQLite WAL)

**Effort**: 4-5 days

---

### 13.2 `sagg analyze` - Query Clustering & Topic Modeling

**CLI Interface:**
```bash
sagg analyze [OPTIONS]

Options:
  --output FILE          Export analysis to JSON file
  --topics INTEGER       Target number of topics (default: auto-detect)
  --since DURATION       Only analyze sessions from last N (e.g., 7d, 30d)
  --project TEXT         Filter to specific project

Analysis Types:
  --clusters             Cluster user queries by topic (default)
  --workflows            Identify common tool sequences
  --time-patterns        Analyze usage patterns over time
```

**Technical Approach:**
- **Embedding Model**: `BAAI/bge-base-en-v1.5` (free, local) or `text-embedding-3-small`
- **Clustering**: BERTopic with HDBSCAN (auto-detects cluster count, handles outliers)
- **Topic Labels**: LLM-generated names for clusters (cost-effective: ~$0.02 for 30 topics)
- **Preprocessing**: Handle code blocks, normalize whitespace, deduplicate

**Dependencies:**
```toml
# These are heavy dependencies (~500MB+). 
# Install via `pip install sagg[analytics]`
[project.optional-dependencies]
analytics = [
  "bertopic>=0.16.0",
  "sentence-transformers>=2.2.0",
  "umap-learn>=0.5.0",
  "hdbscan>=0.8.0",
]
```

**Implementation Note**:
To avoid bloat in the core CLI, the `analyze` command should check for these imports at runtime and prompt the user to install the extra group if missing. Alternatively, v1 could support a lightweight keyword-based clustering to avoid these deps entirely.

**Expected Output:**
```
Query Clusters (598 sessions, 1,847 user queries)
═══════════════════════════════════════════════════
 Cluster              Count   Example Query
───────────────────────────────────────────────────
 debugging-errors      142    "Fix this TypeError..."
 refactoring-code      89     "Extract this into..."
 testing-coverage      67     "Add tests for..."
 documentation         45     "Update README with..."
 git-operations        38     "Help me resolve merge..."
 configuration         32     "Set up TypeScript..."
 ○ outliers            28     (unique/unusual queries)
```

**Effort**: 5-7 days

---

### 13.3 `sagg skill-suggestions` - Pattern-Based Automation

**CLI Interface:**
```bash
sagg skill-suggestions [OPTIONS]

Options:
  --min-frequency N      Minimum sessions for a pattern (default: 3)
  --type TYPE            Filter by type: skill, command, hook, agent
  --format FORMAT        Output format: markdown, json (default: markdown)
  --export NAME          Export specific suggestion to file
  --output DIR           Output directory (default: ~/.config/opencode/skills/)

Interactive:
  --interactive          Review and accept/reject suggestions
```

**Detection Criteria:**

| Type | Threshold | Trigger |
|------|-----------|---------|
| **Skill** | ≥5 sessions, ≥2 projects | Domain knowledge needed |
| **Command** | ≥3 sessions, parameterizable | Same prompt template |
| **Hook** | Event-driven, consistent action | Pre-commit, post-save patterns |
| **Agent** | Specialized tools, distinct persona | Read-only, security-focused |

**Technical Approach:**
1. **Feature Extraction**: Tool sequences, file patterns, intent keywords
2. **Clustering**: Group sessions by similar workflows
3. **LLM Synthesis**: Generate suggestions with evidence citations
4. **Confidence Scoring**: Frequency × cross-project × consistency

**Output Example:**
```markdown
# Skill Suggestions Report
Generated: 2026-01-30 | Sessions analyzed: 598

## High Confidence (>0.8)

### 1. Skill: pytest-coverage (85% confidence)
**Appeared in**: 12 sessions across 3 projects
**Trigger phrases**: "run tests", "test coverage", "fix failing"

<generated SKILL.md content>

---

### 2. Command: /fix-types (78% confidence)
**Template**: "Fix TypeScript errors in $FILE"
**Appeared in**: 8 sessions
```

**Effort**: 7-10 days

---

### 13.4 TUI Analytics Dashboard

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│ Analytics                          [Last 30 Days ▼] [/] Filter
├───────────────────────────┬─────────────────────────────────┤
│ Sessions Over Time        │ Query Topics                    │
│ ▁▂▃▅▆▇▆▅▃▂▁▃▅▇█▇▆▅▄▃     │ ▼ debugging (142)               │
│ └─ 30 days ──────────┘    │   ├─ python (45)                │
│                           │   ├─ git (32)                   │
│                           │   └─ build (28)                 │
├───────────────────────────┤ ► refactoring (89)              │
│ Model Distribution        │ ► documentation (45)            │
│ claude: ████████░░ 65%    │                                 │
│ gemini: ████░░░░░░ 28%    ├─────────────────────────────────┤
│ codex:  █░░░░░░░░░  7%    │ Skill Suggestions               │
├───────────────────────────┤ ● pytest-coverage (85%)         │
│ Tool Usage                │ ● fix-types (78%)               │
│ bash:  ████████░░ 1,935   │ ● django-testing (72%)          │
│ read:  ██████░░░░ 1,321   │                                 │
│ edit:  ████░░░░░░   980   │ [Enter] View Details            │
└───────────────────────────┴─────────────────────────────────┘
```

**Widgets:**
- **Sparkline**: Session trends over time (built-in Textual widget)
- **Tree**: Topic cluster hierarchy with drill-down
- **Custom DistributionBar**: Model/tool usage percentages
- **ListView**: Skill suggestions with confidence scores

**Dependencies:**
```toml
textual-plotext = ">=0.2.0"  # Optional: richer charts
```

**Effort**: 4-6 days

---

### 13.5 `sagg export` / `sagg import` - Multi-Machine Session Sync

Enable users to export sessions from one machine and import on another.

**Use Cases:**
- Sync work machine sessions to personal machine
- Share specific project sessions with teammates
- Backup sessions before reinstalling
- Merge session histories from multiple machines

**Export CLI Interface:**
```bash
sagg export [OPTIONS]

Options:
  -o, --output FILE      Output file (default: sagg-export-YYYY-MM-DD.sagg)
  -n, --name TEXT        Named export (e.g., "work-sessions", "personal")
  --since DURATION       Only sessions from last N (e.g., 7d, 30d)
  --project TEXT         Filter to specific project
  --source TEXT          Filter to specific source tool
  --dry-run              Preview what would be exported
  -v, --verbose          Show detailed progress
```

**Import CLI Interface:**
```bash
sagg import FILE [OPTIONS]

Options:
  --strategy STRATEGY    Merge strategy: skip (default), replace, rename
  --dry-run              Preview changes without importing
  --verify               Verify integrity before import
  -v, --verbose          Show detailed progress
  
Merge Strategies:
  skip      Keep existing sessions, skip duplicates (default, safe)
  replace   Overwrite existing with imported version
  rename    Import with new ID if collision (keep both)
```

**Export Format: `.sagg` (JSONL + gzip)**

```
sagg-export-2026-01-30-work-macbook.sagg
```

**Internal Structure:**
```jsonl
{"type": "header", "version": "1.0.0", "machine_id": "abc123", "exported_at": "...", "session_count": 150}
{"type": "session", "id": "0195abc...", "source": "opencode", "turns": [...], ...}
{"type": "session", "id": "0195def...", "source": "cursor", "turns": [...], ...}
...
{"type": "footer", "checksum": "sha256:xyz789", "session_count": 150}
```

**Why JSONL + gzip?**
| Format | Size (1k sessions) | Streaming | Human Readable |
|--------|-------------------|-----------|----------------|
| JSON | ~100MB | No | Yes |
| JSONL.gz | ~10MB | Yes | With zcat |
| SQLite | ~80MB | No | No |

**Example Workflows:**

```bash
# Export from work machine
$ sagg export --since 30d -n work-sessions
Exporting 142 sessions...
Created: work-sessions-2026-01-30.sagg (4.2 MB)

# Import on personal machine  
$ sagg import work-sessions-2026-01-30.sagg --dry-run
Would import 142 sessions (0 duplicates, 142 new)

$ sagg import work-sessions-2026-01-30.sagg
Imported 142 sessions

# Share project-specific sessions
$ sagg export --project auth-service --since 7d -o auth-debug.sagg
$ # Share auth-debug.sagg with teammate
```

**Identity & Deduplication:**
- Sessions identified by `(source, source_id)` tuple
- Machine ID stored in `~/.sagg/machine_id` (auto-generated UUID)
- Same session on different machines = same identity (deduped)

**Cross-Platform Considerations:**
- Paths stored as metadata only (project_name used for grouping)
- Timestamps in ISO 8601 / UTC
- UTF-8 encoding throughout

**Provenance Tracking (Schema Addition):**
```sql
ALTER TABLE sessions ADD COLUMN origin_machine TEXT;      -- NULL = local
ALTER TABLE sessions ADD COLUMN origin_machine_id TEXT;   -- UUID of source
ALTER TABLE sessions ADD COLUMN import_source TEXT;       -- bundle filename
ALTER TABLE sessions ADD COLUMN imported_at INTEGER;      -- when imported
ALTER TABLE sessions ADD COLUMN sync_status TEXT DEFAULT 'local'; -- local|imported
```

**TUI Display for Imported Sessions:**
```
▼ ai_experiments  2.6M tokens  [12 local, 5 imported]
  ▼ Today (5)
    ▶ Fix auth bug                   42k  opc
    ▶ Add validation [work]          18k  cla    ← badge shows origin
    ▶ Debug issue [home]             31k  opc
```

**Filter Options:**
| Filter | CLI Flag | TUI Key | Description |
|--------|----------|---------|-------------|
| All | `--all` | `a` | Show all sessions (default) |
| Local only | `--local` | `l` | Only sessions from this machine |
| Imported | `--imported` | `i` | Only imported sessions |
| By machine | `--from <name>` | `m` | Filter by origin machine |

**Conflict Resolution:**
When same session exists locally and imported:
```
┌─ Session Conflict ────────────────────────────────────────┐
│ Local: Updated 2026-01-30 15:30, 42k tokens, 12 turns    │
│ Imported (work): Updated 2026-01-30 14:45, 38k tokens    │
│                                                           │
│ [K]eep local  [U]se imported  [B]oth (rename)            │
└───────────────────────────────────────────────────────────┘
```

**Effort**: 4-5 days

---

### 13.6 `sagg summarize` - Automated Work Reports

**Status**: Research Complete (Jan 30, 2026). Implementation Planned.

**Concept**:
Generate a high-level, bulleted summary of "Work Accomplished" over a time period (e.g., last 7 days) by analyzing session logs from all tools.

**CLI Interface:**
```bash
sagg summarize [OPTIONS]

Options:
  --since DURATION       Time range (default: 7d)
  --project TEXT         Filter by project
  --model TEXT           LLM to use (default: gpt-4o or claude-3-5-sonnet)
  --output FILE          Save report to file
  --store/--no-store     Store summary in database (default: True)
```

**Architecture (Map-Reduce Pipeline)**:
1.  **Map (Per-Session)**:
    *   Input: Full session transcript + diff stats.
    *   Prompt: "Extract key accomplishments, files modified, and decisions made."
    *   Output: Structured JSON (bullets, files, tags).
    *   *Fallback*: If no LLM, extract deterministic stats (files touched, duration, tool counts).
2.  **Reduce (Aggregation)**:
    *   Cluster session summaries by day and project.
    *   Prompt: "Synthesize these session summaries into a coherent weekly report. Deduplicate and group by theme."
    *   Output: Final Markdown report.

**Data Model**:
```sql
CREATE TABLE summaries (
    id TEXT PRIMARY KEY,
    range_start INTEGER NOT NULL,
    range_end INTEGER NOT NULL,
    content TEXT NOT NULL,         -- The final report
    summary_type TEXT NOT NULL,    -- 'weekly', 'daily', 'custom'
    generator_model TEXT,          -- e.g., 'gpt-4o'
    created_at INTEGER NOT NULL
);

CREATE TABLE summary_sessions (
    summary_id TEXT REFERENCES summaries(id),
    session_id TEXT REFERENCES sessions(id),
    PRIMARY KEY (summary_id, session_id)
);
```

**Testing Strategy (AI Engineering)**:
1.  **Deterministic Checks (CI/CD)**:
    *   Verify summary contains top 3 modified filenames (from `stats`).
    *   Verify summary mentions "test" if tests were run.
    *   Verify summary structure (headers, bullets).
2.  **LLM-as-a-Judge**:
    *   Use a strong model (e.g., Opus) to grade the generated summary against the raw session logs.
    *   **Rubric**: Factuality (1-5), Coverage (1-5), Hallucination (Pass/Fail).
    *   *Note*: Run this on a sampled subset, not every run.

**Dependencies**:
*   `langchain-core` (for prompt management/chaining, lightweight)
*   `openai` or `anthropic` SDKs

---

## 14. Technical Dependencies

### Current (v1.0)
```toml
dependencies = [
    "click>=8.1.0",
    "rich>=13.0.0",
    "pydantic>=2.0.0",
    "textual>=0.89.0",
]
```

### Planned (v1.1+)
```toml
dependencies = [
    # ... existing ...
    
    # Sync
    "watchfiles>=1.0.0",
    
    # TUI visualization (optional)
    "textual-plotext>=0.2.0",
]

[project.optional-dependencies]
analytics = [
    "bertopic>=0.16.0",
    "sentence-transformers>=2.2.0",
    "umap-learn>=0.5.0",
    "hdbscan>=0.8.0",
]
```

---

## 15. Market Positioning

### Unique Value Proposition
**"The unified observability layer for AI-assisted development"**

### Competitive Gaps We Fill
| Feature | cursor-chat-browser | Langfuse | LangSmith | **sagg** |
|---------|---------------------|----------|-----------|----------|
| Multi-tool support | ❌ | ❌ | ❌ | ✅ |
| Coding context awareness | ✅ | ❌ | ❌ | ✅ |
| Session replay | ❌ | ❌ | ❌ | ✅ |
| Pattern extraction | ❌ | ❌ | ❌ | ✅ |
| Self-hostable | ❌ | ✅ | ❌ | ✅ |
| Multi-machine sync | ❌ | ❌ | ❌ | ✅ |

---

## 16. Future Feature Ideas (Brainstorm)

### Must-Have (High Value, Achievable)

| Feature | Description | Complexity |
|---------|-------------|------------|
| `sagg scrubbing` | **Security**: Automated redaction of sensitive data (API keys, .env values) before export. User-definable regex patterns. | Low |
| `sagg to-md` | **Sharing**: Export session to clean Markdown for PRs/Documentation. Removes JSON noise, formats for human reading. | Low |
| `sagg resume` | **Interoperability**: Generate a "prompt context" file to resume a session in a *different* tool. Summarizes previous context. | Medium |
| `sagg snippets` | Extract and index all code blocks from sessions into searchable library | Low |
| `sagg git-link` | Associate sessions with git commits by timestamp proximity | Low |
| `sagg oracle` | Before new session, search history: "Have I solved this before?" | Medium |
| `sagg budget` | Set token budgets with alerts: `sagg budget set --weekly 500k` | Low |
| `sagg similar` | Find sessions similar to a query using embeddings | Medium |
| `sagg friction-points` | Detect sessions with excessive back-and-forth or restarts | Low |
| `sagg wins` | Extract "breakthrough moments" - successful problem resolutions | Medium |
| `sagg diff-replay` | Show file diffs that resulted from a session, linked to conversation | Low |

### Nice-to-Have (Delightful)

| Feature | Description | Complexity |
|---------|-------------|------------|
| `sagg replay` | Step through past session interactively, one exchange at a time | Medium |
| `sagg heatmap` | Terminal heatmap of AI usage by hour/day (like GitHub contributions) | Low |
| `sagg velocity` | Track "problems solved per session" trends over time | Medium |
| `sagg journal` | Auto-generate daily/weekly developer journal from sessions | Medium |
| `sagg model-compare` | Analyze token efficiency by model and task type | Low |
| `sagg changelog-assist` | Generate changelog from sessions in a date range | Medium |
| `sagg context-cost` | Show which context (files, docs) consumes most tokens vs value | Medium |

### Key Insight

The theme across the best ideas: **turning passive session storage into active knowledge retrieval**. The data is already there — the value is in surfacing it at the right moment.

**Killer Feature**: `sagg oracle` - "You asked about rate limiting 3 times — here's what worked."

---

## 17. References

- [AgentTrace Specification](https://agent-trace.dev)
- [Agent Prism Components](https://github.com/evilmartians/agent-prism)
- [cursor-chat-browser](https://github.com/thomas-pedersen/cursor-chat-browser)
- [claude-code-viewer](https://github.com/esc5221/claude-code-viewer)
- [OpenLLMetry](https://github.com/traceloop/openllmetry)
- [Langfuse](https://github.com/langfuse/langfuse)
