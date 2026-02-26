# Session Aggregator - Technical Specification

**Project**: Unified AI Coding Session Aggregator  
**Version**: 0.1.0  
**Date**: February 1, 2026  
**Status**: Draft

---

## 1. Overview

### 1.1 Problem Statement

Developers using multiple AI coding tools (OpenCode, Claude Code, Codex, Cursor, Ampcode, Gemini CLI, Antigravity) have session data scattered across different locations in incompatible formats. There is no unified way to:
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

Adapter layer includes OpenCode, Claude Code, Codex, Cursor, Ampcode, Gemini CLI, and Antigravity (research).

---

## 3. Data Model

### 3.1 Unified Session Schema

```typescript
interface UnifiedSession {
  // Identity
  id: string;                    // UUID v7 (time-sortable)
  source: SourceTool;            // 'opencode' | 'claude' | 'codex' | 'cursor' | 'gemini' | 'ampcode' | 'antigravity'
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

type SourceTool = 'opencode' | 'claude' | 'codex' | 'cursor' | 'gemini' | 'ampcode' | 'antigravity';
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
sagg init                         # Setup wizard - finds your AI tools automatically
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

[sources.gemini]
enabled = true
path = "~/.gemini/tmp"

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

### 5.7 Gemini CLI Adapter

**Input**: `~/.gemini/tmp/<project_hash>/chats/` (base path respects `GEMINI_CLI_HOME`)

**Session Files**: `session-<YYYY-MM-DDTHH-MM>-<session_id_prefix>.json`

**Session Record Format**:
```typescript
type GeminiConversation = {
  sessionId: string;
  projectHash: string;
  startTime: string;     // ISO timestamp
  lastUpdated: string;   // ISO timestamp
  messages: MessageRecord[];
  summary?: string;
  directories?: string[];
}

type MessageRecord =
  | { type: "user"; id: string; timestamp: string; content: PartListUnion; displayContent?: PartListUnion }
  | { type: "gemini"; id: string; timestamp: string; content: PartListUnion | string; model?: string; tokens?: TokensSummary; toolCalls?: ToolCallRecord[] }
  | { type: "info" | "warning" | "error"; id: string; timestamp: string; content: PartListUnion | string };
```

**Mapping**:
| Gemini CLI | Unified |
|------------|---------|
| `sessionId` | `sourceId` |
| `startTime` / `lastUpdated` | `createdAt` / `updatedAt` |
| `messages[].type: user` | `message.role: user` |
| `messages[].type: gemini` | `message.role: assistant` |
| `messages[].tokens` | `usage.inputTokens` / `usage.outputTokens` |
| `toolCalls[]` | `part.type: tool_call` + `part.type: tool_result` |
| `directories[0]` | `projectPath` (best-effort) |
| `summary` | `title` (fallback to first user message) |

**Key Notes**:
- Sessions are per-project and stored under a hashed project directory.
- Full project path is not stored directly; `directories` is used as best-effort.

### 5.8 Antigravity Adapter (Research Only)

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

### Phase 5: Smart Features (3 weeks)

**Week 1: Setup**
- [ ] `sagg init` command that finds your AI tools and sets up config
- [ ] Better adapter detection (check what's actually installed)
- [ ] Fix configuration handling
- [ ] Build session fingerprinting - hash the problem type, files touched, and approach used

**Week 2: Session fingerprints**
- [ ] Extract what the session was trying to solve (using embeddings)
- [ ] Generate signatures based on file patterns
- [ ] Track the sequence of tools used
- [ ] Fast similarity search (LSH)
- [ ] `sagg session-dna` and `sagg similar` commands

**Week 3: Tool comparison**
- [ ] Track which suggestions get accepted vs rejected
- [ ] Classify tasks automatically (bugfix vs feature vs refactor)
- [ ] Collect timing and cost data
- [ ] Basic `sagg benchmark` command
- [ ] Simple recommendation engine ("use Claude for Python debugging")

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


### 9.3 Distribution & Installation Strategy

**Goals**
- One-liner install across macOS, Linux, and Windows
- No system Python pollution (isolated env)
- Simple upgrades and uninstalls
- Deterministic versioning and checksums

**Primary (all OS)**
- Publish `sagg` to PyPI (pure-Python wheel).
- Recommended commands:
  - `uv tool install sagg` (preferred)
  - `pipx install sagg` (fallback)
- Upgrade: `uv tool upgrade sagg` / `pipx upgrade sagg`
- Uninstall: `uv tool uninstall sagg` / `pipx uninstall sagg`

**Bootstrap scripts**
- `install.sh` for macOS/Linux:
  - Detect OS/arch
  - Ensure `uv` (install if missing)
  - `uv tool install sagg`
  - Print PATH hints if `~/.local/bin` not on PATH
- `install.ps1` for Windows:
  - Ensure `uv` or `pipx`
  - `uv tool install sagg` (preferred) or `pipx install sagg`
  - Print PATH hints for user bin location

**Package-manager convenience (optional)**
- Homebrew tap for macOS/Linux:
  - `brew install <tap>/sagg`
  - Formula wraps `pipx` or `uv tool install` to keep logic consistent
- Scoop or winget manifests for Windows when demand justifies

**Release pipeline**
1. Tag version `vX.Y.Z`
2. Build sdist + wheel (py3-none-any)
3. Publish to PyPI + GitHub Release
4. Update Homebrew/Scoop manifests
5. Update installer scripts with latest version + checksums

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

### v1.0 - COMPLETED
- [x] All MVP features stable
- [x] Analytics via `sagg stats` command
- [x] Watch mode for live collection (`sagg sync --watch`)
- [x] Config file support (`~/.sagg/config.toml`)
- [x] Basic documentation (README, spec.md)
- [ ] Installable via Homebrew/pip (pending)

### v1.1 - COMPLETED (Sync & Portability)
- [x] `sagg sync` - Incremental sync with watch mode
- [x] `sagg bundle export` / `sagg bundle import` - Multi-machine session portability
- [x] `sagg budget` - Token budget tracking with alerts
- [x] `sagg git-link` - Associate sessions with git commits
- [x] `sagg heatmap` - GitHub-style activity visualization
- [ ] Cost tracking with pricing data (pending)

### v1.2 - COMPLETED (Analytics)
- [x] `sagg oracle` - "Have I solved this before?" semantic search
- [x] `sagg similar` - Find similar sessions using TF-IDF
- [x] `sagg friction-points` - Detect sessions with excessive retries/errors
- [ ] `sagg analyze` - Query clustering and topic modeling (pending)
- [ ] TUI analytics dashboard with visualizations (pending)
- [ ] `sagg skill-suggestions` - Auto-generate skills (pending)

### v1.3 - IN PROGRESS (Insights & Smart Features)
- [x] `sagg analyze-sessions` - Extract per-session facets via heuristic or LLM (§13.7) — Implemented Feb 5, 2026
- [x] `sagg insights` - Cross-tool usage insights CLI report (§13.7) — Implemented Feb 5, 2026
- [ ] `sagg insights --format html` - HTML export for insights report (§13.7)
- [ ] `sagg insights` TUI view - Tabbed Textual interface with drill-down (§13.7)
- [ ] `sagg init` - setup wizard that detects your tools
- [ ] Tool benchmarking - track which AI works best for what
- [ ] `sagg benchmark` - get recommendations based on your actual usage
- [ ] Smart routing - suggest the best tool for each task

### v1.4 - PLANNED (Knowledge Base)
- [ ] `sagg learn` - Auto-extract patterns and skills from session history (§20)
- [ ] `sagg knowledge` - View, search, and export accumulated knowledge (§20)
- [ ] Pattern memory - bounded, curated, auto-populated from cross-session analysis (§20.5)
- [ ] Skill library - procedural skills extracted from successful workflows (§20.6)
- [ ] Project profiles - per-project conventions and tool preferences (§20.4)
- [ ] `sagg knowledge suggest-rules` - Generate AGENTS.md additions from learned patterns (§20.13)

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

### 13.1 `sagg sync` - Incremental Synchronization ✅ COMPLETED

**Status**: Implemented January 31, 2026. Tests: 17/17 passing.

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

### 13.7 `sagg insights` - Cross-Tool Usage Insights Report

**Status**: Planned
**Inspired by**: Claude Code's `/insights` command (analyzed February 2026)
**Key differentiator**: Cross-tool analysis across Claude, Cursor, OpenCode, Codex, Gemini CLI — not locked to one tool

#### The Problem

Claude Code has a built-in `/insights` command that analyzes session history and generates an HTML report with friction analysis, interaction patterns, and suggestions. But it only sees Claude Code sessions. Developers using multiple AI tools have no unified view of their productivity patterns, friction points, or tool effectiveness across all their AI-assisted coding.

#### How Claude Code Does It Internally (Reference Architecture)

Claude Code's insights pipeline has three layers. We replicate and extend this for multi-tool:

```
Claude Code Architecture (single-tool, for reference):
──────────────────────────────────────────────────────
Layer 1: Raw JSONL session logs
  ~/.claude/projects/<path>/<uuid>.jsonl
  Each line = event (user msg, assistant response, tool call, file snapshot)
  Fields: uuid, timestamp, sessionId, type, message, usage

Layer 2: Per-session facets (LLM-generated)
  ~/.claude/usage-data/facets/<sessionId>.json
  An LLM reads each transcript and classifies:
    underlying_goal, goal_categories, outcome,
    friction_counts, claude_helpfulness, session_type,
    primary_success, brief_summary

Layer 3: Aggregated report
  ~/.claude/stats-cache.json → daily stats, token counts, model usage
  ~/.claude/usage-data/report.html → charts + narrative sections

Key insight: Facets are LLM-generated. Claude Code sends each session
transcript to a model that classifies goals, friction, outcomes, and
satisfaction. Then it aggregates across all facets to find patterns.
```

**Claude Code Facet Schema (what each per-session analysis looks like):**

```json
{
  "underlying_goal": "Create a centralized documentation system...",
  "goal_categories": {
    "documentation_organization": 1,
    "spec_implementation": 1
  },
  "outcome": "partially_achieved",
  "user_satisfaction_counts": { "likely_satisfied": 1 },
  "claude_helpfulness": "moderately_helpful",
  "session_type": "multi_task",
  "friction_counts": {
    "user_rejected_action": 2,
    "wrong_approach": 1
  },
  "friction_detail": "User interrupted Claude twice when it tried to use subagents...",
  "primary_success": "multi_file_changes",
  "brief_summary": "User wanted to consolidate documentation and implement...",
  "session_id": "87bf08fb-fedf-4253-9c27-1541f25ef028"
}
```

**Claude Code Report Sections (10 sections in the HTML report):**

| # | Section | Content | Charts |
|---|---------|---------|--------|
| 1 | At a Glance | Yellow card: working / hindering / quick wins / ambitious | — |
| 2 | What You Work On | Project areas with session counts | Goal bars, tool usage bars, language bars, session type bars |
| 3 | How You Use CC | Narrative about interaction style + key pattern callout | Response time histogram, time-of-day histogram, multi-clauding stats, tool errors |
| 4 | Impressive Things | Top 3 workflows that went well | "What helped most" bars, outcomes bars |
| 5 | Where Things Go Wrong | Friction categories with examples | Friction type bars, satisfaction bars |
| 6 | Features to Try | CLAUDE.md additions + feature cards with copyable code | — |
| 7 | New Usage Patterns | Pattern cards with copyable prompts | — |
| 8 | On the Horizon | Purple cards with ambitious future workflow ideas | — |
| 9 | Team Feedback | Collapsible (often empty) | — |
| 10 | Fun Ending | Humorous headline from session history | — |

#### sagg Architecture (Multi-Tool Extension)

```
sagg insights pipeline:
────────────────────────
Layer 1: Already done — sagg collect normalizes all tools to UnifiedSession
  Adapters: Claude, OpenCode, Cursor, Codex, Gemini CLI, Ampcode
  Storage: ~/.sagg/db.sqlite + ~/.sagg/sessions/<source>/<id>.jsonl

Layer 2: NEW — session_facets table in existing SQLite
  sagg analyze-sessions reads each session, extracts structured facets
  via LLM (preferred) or heuristic classifier (fallback)
  LLM backend: shell out to claude -p / codex / gemini CLI (no SDK deps)

Layer 3: NEW — sagg insights aggregates facets + existing stats
  Cross-tool comparison, friction patterns, tool recommendations
  Primary output: TUI (Textual) with tabbed layout + drill-down
  Export: --format html for sharing, --format json for scripting
```

#### Our Facet Schema (Extended for Multi-Tool)

```python
class SessionFacet(BaseModel):
    """AI-extracted or heuristic-extracted analysis of a single session."""

    # Identity
    session_id: str
    source: SourceTool                     # Which tool (claude, cursor, opencode, etc.)
    analyzed_at: datetime

    # Goal classification
    underlying_goal: str                   # What the user was trying to accomplish
    goal_categories: dict[str, int]        # e.g. {"bugfix": 1, "refactor": 1}
    task_type: str                         # bugfix | feature | refactor | docs | debug | config | exploration

    # Outcome assessment
    outcome: str                           # fully_achieved | partially_achieved | abandoned | unclear
    completion_confidence: float           # 0.0-1.0 how confident we are in the outcome

    # Session characteristics
    session_type: str                      # quick_question | single_task | multi_task | iterative_refinement
    complexity_score: int                  # 1-5 how complex was the session

    # Friction analysis (extends existing friction.py)
    friction_counts: dict[str, int]        # {type: count} — wrong_approach, user_rejected, data_quality, etc.
    friction_detail: str | None            # Human-readable explanation
    friction_score: float                  # 0.0-1.0 composite (reuse from analytics/friction.py)

    # Tool effectiveness (cross-tool specific)
    tools_that_helped: list[str]           # Tool names that contributed to success
    tools_that_didnt: list[str]            # Tool names that caused friction
    tool_helpfulness: str                  # unhelpful | slightly | moderately | very | extremely

    # Languages and files
    primary_language: str | None           # Dominant language in session
    files_pattern: str | None              # "python_backend" | "react_frontend" | "config" | "docs"

    # Summary
    brief_summary: str                     # 1-2 sentence description
    key_decisions: list[str]               # Major decisions or pivots made
```

#### Database Schema (New Tables in Existing SQLite)

```sql
-- Migration v3 → v4

-- Per-session facets (the core analysis unit)
CREATE TABLE IF NOT EXISTS session_facets (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    analyzed_at INTEGER NOT NULL,
    analyzer_version TEXT NOT NULL,            -- "heuristic_v1" or "llm_v1"
    analyzer_model TEXT,                       -- e.g. "claude-sonnet-4" if LLM-generated

    -- Goal
    underlying_goal TEXT NOT NULL,
    goal_categories_json TEXT NOT NULL,        -- JSON dict
    task_type TEXT NOT NULL,

    -- Outcome
    outcome TEXT NOT NULL,
    completion_confidence REAL DEFAULT 0.5,

    -- Session type
    session_type TEXT NOT NULL,
    complexity_score INTEGER DEFAULT 3,

    -- Friction
    friction_counts_json TEXT,                 -- JSON dict
    friction_detail TEXT,
    friction_score REAL DEFAULT 0.0,

    -- Tool effectiveness
    tools_helped_json TEXT,                    -- JSON array
    tools_didnt_json TEXT,                     -- JSON array
    tool_helpfulness TEXT,

    -- Context
    primary_language TEXT,
    files_pattern TEXT,

    -- Summary
    brief_summary TEXT NOT NULL,
    key_decisions_json TEXT                    -- JSON array
);

-- Aggregated insights cache (avoid recomputing on every run)
CREATE TABLE IF NOT EXISTS insights_cache (
    id TEXT PRIMARY KEY,                       -- "report_<date_range_hash>"
    range_start INTEGER NOT NULL,
    range_end INTEGER NOT NULL,
    session_count INTEGER NOT NULL,
    facet_count INTEGER NOT NULL,
    report_json TEXT NOT NULL,                 -- Full InsightsReport as JSON
    report_html TEXT,                          -- Rendered HTML (cached)
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL                -- Cache TTL (default: 24h)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_facets_source ON session_facets(source);
CREATE INDEX IF NOT EXISTS idx_facets_task_type ON session_facets(task_type);
CREATE INDEX IF NOT EXISTS idx_facets_outcome ON session_facets(outcome);
CREATE INDEX IF NOT EXISTS idx_facets_analyzed ON session_facets(analyzed_at DESC);
CREATE INDEX IF NOT EXISTS idx_facets_language ON session_facets(primary_language);
```

#### CLI Interface

```bash
# Stage 1: Extract facets from sessions
sagg analyze-sessions [OPTIONS]

Options:
  --since DURATION           Only analyze sessions from last N (e.g., 7d, 30d)
  --source TEXT               Filter by source tool
  --project TEXT              Filter by project
  --force                     Re-analyze sessions that already have facets
  --analyzer [heuristic|llm]  Analysis method (default: heuristic, falls back if no LLM CLI)
  --llm-cli [claude|codex|gemini]  Which CLI tool to use for LLM analysis (default: auto-detect)
  --batch-size INTEGER        Sessions per LLM call (default: 10)
  --dry-run                   Show what would be analyzed without doing it
  -v, --verbose               Show per-session analysis results

# Stage 2: Generate insights report
sagg insights [OPTIONS]

Options:
  --since DURATION           Time range (default: 30d)
  --source TEXT               Filter by source tool (repeatable for comparison)
  --project TEXT              Filter by project
  --format [tui|html|json]   Output format (default: tui)
  --output FILE               Save report to file (html/json only)
  --open                      Open HTML report in browser
  --no-cache                  Force regeneration (ignore cached report)
  -v, --verbose               Show detailed breakdowns
```

#### LLM Backend: CLI Tools Instead of SDKs

**Key design decision**: Instead of adding `anthropic` or `openai` Python SDKs as dependencies, shell out to whichever AI CLI tool the user already has installed. This is natural for sagg — the user already has these tools (that's why they use sagg in the first place).

```python
class CLILLMBackend:
    """Run LLM analysis by shelling out to installed AI CLI tools.

    No SDK dependencies needed. Uses the user's existing auth and billing.
    """

    # Detection order — try each, use first available
    BACKENDS = [
        {
            "name": "claude",
            "check": ["claude", "--version"],
            "cmd": ["claude", "-p"],             # pipe mode: reads stdin, prints response
            "stdin": True,
        },
        {
            "name": "codex",
            "check": ["codex", "--version"],
            "cmd": ["codex", "--quiet"],         # quiet mode: prompt as arg
            "stdin": False,
        },
        {
            "name": "gemini",
            "check": ["gemini", "--version"],
            "cmd": ["gemini", "-p"],
            "stdin": True,
        },
    ]

    def detect_available(self) -> str | None:
        """Find first available CLI tool in PATH."""
        for backend in self.BACKENDS:
            try:
                subprocess.run(backend["check"], capture_output=True, timeout=5)
                return backend["name"]
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        return None

    def analyze(self, prompt: str, backend_name: str) -> str:
        """Send prompt to CLI tool and return response."""
        backend = next(b for b in self.BACKENDS if b["name"] == backend_name)
        if backend["stdin"]:
            result = subprocess.run(
                backend["cmd"],
                input=prompt,
                capture_output=True, text=True, timeout=120,
            )
        else:
            result = subprocess.run(
                backend["cmd"] + [prompt],
                capture_output=True, text=True, timeout=120,
            )
        return result.stdout
```

**Why this approach:**

| Approach | New Deps | Auth Setup | Billing | Works Offline |
|----------|----------|------------|---------|---------------|
| `anthropic` SDK | ~50MB | API key needed | Separate account | No |
| `openai` SDK | ~30MB | API key needed | Separate account | No |
| `claude -p` | **0** | Already configured | User's existing | No |
| `codex -p` | **0** | Already configured | User's existing | No |
| Heuristic only | **0** | None | Free | **Yes** |

**Fallback chain**: `claude -p` → `codex -p` → `gemini -p` → heuristic-only

**Cost estimate (LLM backend):**
- ~3K input tokens + ~500 output tokens per session (condensed transcript)
- At Claude Sonnet pricing: ~$0.012 per session
- 256 sessions ≈ $3.07 total
- Batch mode (10 sessions/call): ~$1.50 total

#### Facet Extraction: Two Backends

**Backend A: Heuristic Analyzer (zero cost, always available)**

Uses existing sagg infrastructure + new heuristics:

```python
class HeuristicAnalyzer:
    """Extract facets without LLM using pattern matching and existing analytics."""

    def analyze(self, session: UnifiedSession) -> SessionFacet:
        # 1. Goal: first user message + title
        goal = self._extract_goal(session)

        # 2. Task type: from tool usage + file extensions
        #    high error_rate (from friction.py) → "debug"
        #    mostly Read/Grep → "exploration"
        #    mostly Edit/Write → "feature" or "refactor"
        #    "test" in tools/files → "testing"
        task_type = self._classify_task_type(session)

        # 3. Outcome: heuristic from session ending
        #    last message is assistant with no follow-up → likely achieved
        #    session < 2 turns → abandoned
        #    high friction score → partially_achieved
        outcome = self._assess_outcome(session)

        # 4. Friction: reuse existing analytics/friction.py
        friction_score = calculate_friction_score(
            analyze_retries(session),
            analyze_error_rate(session),
            analyze_back_and_forth(session),
        )

        # 5. Language: from file extensions in files_modified
        language = self._detect_language(session)

        # 6. Summary: first user message truncated + stats
        summary = self._generate_summary(session)

        return SessionFacet(...)
```

**Backend B: LLM Analyzer (higher quality, uses CLI tools)**

Sends condensed transcript to LLM via CLI:

```python
class LLMAnalyzer:
    """Extract facets using an LLM via CLI tools (claude -p, codex, etc.)."""

    PROMPT = """Analyze this AI coding session and extract structured metadata.

Session Info:
- Tool: {source}
- Project: {project_name}
- Duration: {duration}
- Turns: {turn_count}
- Models: {models}

Transcript (condensed):
{condensed_transcript}

Respond with JSON only, matching this schema:
{schema}

Guidelines:
- goal_categories: use lowercase_snake_case keys
- task_type: one of bugfix, feature, refactor, docs, debug, config, exploration
- outcome: one of fully_achieved, partially_achieved, abandoned, unclear
- friction_counts keys: wrong_approach, user_rejected_action, data_quality,
  incomplete_response, tool_error, context_loss, performance_issue
- Be concise in brief_summary (1-2 sentences)
"""

    def condense_transcript(self, session: UnifiedSession, max_tokens: int = 4000) -> str:
        """Reduce transcript to fit LLM context budget.

        Keep:
          ✓ All user messages (verbatim)
          ✓ First 200 chars of each assistant text response
          ✓ Tool names + whether they succeeded/failed
          ✓ Error messages (full text)
          ✓ File paths modified

        Drop:
          ✗ Tool input parameters (file contents, code blocks)
          ✗ Tool output results (command output, file reads)
          ✗ System messages
          ✗ Cached/repeated content
        """
        ...

    def analyze(self, session: UnifiedSession, cli: CLILLMBackend) -> SessionFacet:
        condensed = self.condense_transcript(session)
        prompt = self.PROMPT.format(...)
        response = cli.analyze(prompt, backend_name="claude")
        return SessionFacet.model_validate_json(response)
```

#### Insights Report Model

```python
class InsightsReport(BaseModel):
    """The complete insights report, aggregated from all facets."""

    # Metadata
    generated_at: datetime
    range_start: datetime
    range_end: datetime
    total_sessions: int
    total_facets: int

    # Sections (mapped to TUI tabs)
    at_a_glance: AtAGlance
    project_areas: list[ProjectArea]
    interaction_style: InteractionStyle
    impressive_workflows: list[Workflow]
    friction_analysis: FrictionAnalysis
    tool_comparison: ToolComparison           # Cross-tool — sagg exclusive
    suggestions: SuggestionsSection           # Includes AGENTS.md suggestions
    trends: TrendAnalysis
    fun_ending: FunEnding


class AtAGlance(BaseModel):
    whats_working: str
    whats_hindering: str
    quick_wins: str
    ambitious_workflows: str


class ProjectArea(BaseModel):
    name: str
    session_count: int
    description: str
    primary_tools: list[str]                  # Which AI tools used here
    success_rate: float                       # % fully_achieved
    avg_friction: float


class ToolComparison(BaseModel):
    """Cross-tool analysis — the unique value sagg provides over Claude's /insights."""

    tools_analyzed: list[str]
    sessions_per_tool: dict[str, int]
    tool_metrics: list[ToolMetric]
    best_for: dict[str, str]                  # {"python_debug": "claude", "react_ui": "cursor"}
    narrative: str


class ToolMetric(BaseModel):
    tool: str                                 # "claude" | "cursor" | "opencode"
    session_count: int
    avg_turns: float
    avg_duration_ms: int | None
    avg_friction_score: float
    success_rate: float
    avg_tokens: int
    top_task_types: list[str]
    helpfulness_distribution: dict[str, int]


class FrictionAnalysis(BaseModel):
    total_friction_sessions: int
    friction_by_category: dict[str, int]
    friction_by_tool: dict[str, float]        # {tool: avg_friction_score}
    top_friction_patterns: list[FrictionPattern]
    narrative: str


class FrictionPattern(BaseModel):
    category: str
    count: int
    description: str
    affected_tools: list[str]
    examples: list[str]


class SuggestionsSection(BaseModel):
    """Suggestions including AGENTS.md additions for each tool."""

    agents_md_additions: list[AgentsMdSuggestion]
    usage_patterns: list[UsagePattern]
    tool_recommendations: list[ToolRecommendation]


class AgentsMdSuggestion(BaseModel):
    """Suggested addition to AGENTS.md (or CLAUDE.md, .cursorrules, etc.)

    Unlike Claude's /insights which only suggests CLAUDE.md changes,
    sagg detects which config file each tool uses and suggests additions
    for all of them.
    """
    target_file: str                          # "CLAUDE.md" | ".cursorrules" | "AGENTS.md" | "codex.md"
    target_tool: str                          # Which tool this applies to
    addition: str                             # The text to add
    why: str                                  # Evidence from session data
    section_hint: str                         # e.g. "Add under ## Data Processing"


class UsagePattern(BaseModel):
    title: str
    suggestion: str
    detail: str
    copyable_prompt: str | None


class ToolRecommendation(BaseModel):
    task_type: str                            # "python_debug" | "react_ui" | "docs"
    recommended_tool: str
    reason: str
    confidence: float                         # 0.0-1.0 based on sample size


class TrendAnalysis(BaseModel):
    sessions_per_day: dict[str, int]
    friction_trend: str                       # "improving" | "stable" | "worsening"
    tool_adoption: dict[str, list[int]]       # tool → [week1_count, week2_count, ...]
    productivity_trend: str


class FunEnding(BaseModel):
    headline: str
    detail: str
```

#### TUI Layout (Primary Output)

```
┌─ sagg insights ──────────────── 256 sessions · 30d ── [c]laude [u]rsor [o]pencode [a]ll ┐
│                                                                                          │
│  At a Glance                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Working: Most productive with Claude for Python (92% success rate)                  │  │
│  │ Hindering: OpenCode has 2.3x higher friction than Claude                            │  │
│  │ Quick win: Create a /preprocess skill for your data validation workflow             │  │
│  └─────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                          │
│ ┌ [1] Overview ─ [2] Tools ─ [3] Friction ─ [4] Trends ─ [5] Suggestions ─ [6] Horizon ┐│
│ │                                                                                        ││
│ │  Cross-Tool Comparison                                                                 ││
│ │  ═══════════════════                                                                   ││
│ │               Sessions  Success  Friction  Avg Turns  Best For                         ││
│ │  Claude           83     88%      0.21       12.3     Python, debugging                ││
│ │  Cursor           89     82%      0.31        8.7     React, UI work                   ││
│ │  OpenCode         84     79%      0.48        6.2     Quick edits                      ││
│ │                                                                                        ││
│ │  Success Rate                                                                          ││
│ │  Claude   ████████████████████░░ 88%                                                   ││
│ │  Cursor   ████████████████░░░░░░ 82%                                                   ││
│ │  OpenCode ███████████████░░░░░░░ 79%                                                   ││
│ │                                                                                        ││
│ │  Recommendation: Use Claude for Python debugging (34% faster)                          ││
│ │                  Use Cursor for React/UI (shorter sessions, less friction)              ││
│ │                                                                                        ││
│ └────────────────────────────────────────────────── ↑↓ scroll · Tab next · Enter drill ──┘│
│                                                                                          │
│  Fun: "User interrupted Claude twice to stop subagent spawning"                          │
│  [e] Export HTML   [j] Export JSON   [q] Quit                                            │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

**TUI Tabs:**

| Tab | Key | Content | Drill-down |
|-----|-----|---------|------------|
| Overview | `1` | At a Glance + project areas + goal/language/session type bars | Enter on project area → show its sessions |
| Tools | `2` | Cross-tool comparison table + success/friction bars + recommendations | Enter on tool → show its sessions |
| Friction | `3` | Friction categories with examples + friction type bars + satisfaction | Enter on friction pattern → show affected sessions |
| Trends | `4` | Sessions over time (sparkline) + friction trend + tool adoption | — |
| Suggestions | `5` | AGENTS.md additions + usage patterns + tool recommendations | Enter on suggestion → copy to clipboard |
| Horizon | `6` | Ambitious workflow ideas (like Claude's On the Horizon) | Enter → copy prompt to clipboard |

**Drill-down** is the key advantage over HTML — press Enter on any friction pattern, tool metric, or project area to see the actual sessions that produced that data point. This turns insights from a static report into an interactive debugging tool for your workflow.

**Keyboard shortcuts:**
- `1`-`6`: Switch tabs
- `c`, `u`, `o`, `a`: Filter by Claude / Cursor / OpenCode / All
- `Enter`: Drill into selected item
- `e`: Export as HTML
- `j`: Export as JSON
- `q`: Quit
- `↑↓`: Scroll within tab
- `Tab`/`Shift+Tab`: Next/previous tab

#### Suggestions Tab: AGENTS.md Additions

Unlike Claude's `/insights` which only suggests CLAUDE.md changes, sagg detects which configuration file each tool uses and suggests additions for all relevant tools:

```
┌─ [5] Suggestions ──────────────────────────────────────────────────────────────────────┐
│                                                                                        │
│  AGENTS.md / Tool Config Suggestions                                                   │
│  ════════════════════════════════════                                                   │
│  Based on friction patterns across your sessions, add these to your tool configs:      │
│                                                                                        │
│  ┌─ CLAUDE.md ─────────────────────────────────────────────────────────────────────┐   │
│  │ [x] "Use polars instead of pandas for datasets with >90% missing values"        │   │
│  │     Why: 186 data quality friction events; pandas→polars switch in 3 sessions   │   │
│  │                                                                                  │   │
│  │ [x] "Check for existing spec.md before creating new documentation"              │   │
│  │     Why: Had to redirect Claude to existing spec files 4 times                  │   │
│  │                                                                                  │   │
│  │ [x] "Avoid using task agents unless explicitly requested"                       │   │
│  │     Why: User rejected subagent usage 162 times                                 │   │
│  └──────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                        │
│  ┌─ .cursorrules ──────────────────────────────────────────────────────────────────┐   │
│  │ [x] "For Python files, prefer polars over pandas for data processing"           │   │
│  │     Why: Cursor Python sessions had 31% friction from wrong library choice      │   │
│  └──────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                        │
│  ┌─ AGENTS.md (universal) ─────────────────────────────────────────────────────────┐   │
│  │ [x] "Industrial equipment data has 90%+ missing values. Always profile first."  │   │
│  │     Why: Pattern detected across Claude (83 sessions) + OpenCode (84 sessions)  │   │
│  └──────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                        │
│  [Enter] Copy selected   [Space] Toggle checkbox   [A] Copy all checked               │
│                                                                                        │
│  Tool Recommendations                                                                  │
│  ════════════════════                                                                   │
│  Python debugging  → Claude (34% faster, 92% success)                                  │
│  React/UI work     → Cursor (shorter sessions, better completions)                     │
│  Quick file edits  → OpenCode (fastest start-to-finish)                                │
│  Documentation     → Claude (handles multi-file updates well)                          │
│                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

**Target file detection logic:**

| Tool | Config File | Detection |
|------|-------------|-----------|
| Claude Code | `CLAUDE.md` | Always present if Claude sessions exist |
| Cursor | `.cursorrules` or `.cursor/rules` | Check project root |
| OpenCode | `AGENTS.md` or `opencode.md` | Check project root |
| Codex | `codex.md` or `AGENTS.md` | Check project root |
| Universal | `AGENTS.md` | Cross-tool patterns (same friction in 2+ tools) |

**How suggestions are generated:**
1. Aggregate `friction_counts` across all facets
2. Group by friction type and affected tool
3. For each pattern appearing ≥3 times: generate a config suggestion
4. If same pattern appears across 2+ tools: generate an `AGENTS.md` (universal) suggestion
5. Format as copyable text with evidence ("Why: ...")

#### HTML Export

`sagg insights --format html --output report.html --open`

- Standalone HTML file with all CSS/JS inline (no external deps)
- Styled similarly to Claude Code's report (clean, Inter font, card-based layout)
- All sections from the TUI rendered as scrollable HTML
- Bar charts rendered as CSS (like Claude's report — no charting library needed)
- Copy buttons on all suggestions and prompts
- Stored at `~/.sagg/reports/insights-<date>.html` by default

#### Aggregation Logic

```python
def generate_insights(store: SessionStore, since: str = "30d") -> InsightsReport:
    """Main insights generation pipeline."""

    # 1. Load all facets in range
    facets = store.get_facets(since=since)

    # 2. Load session stats (reuse existing store.get_stats())
    stats = store.get_stats()

    # 3. Cross-tool comparison
    #    Group facets by source tool
    #    Calculate per-tool: avg friction, success rate, avg turns, top tasks
    #    Generate "best for" recommendations
    tool_comparison = _build_tool_comparison(facets)

    # 4. Project area clustering
    #    Group by project_name + goal_categories
    #    Merge similar projects (same git repo, different branches)
    #    Calculate per-area stats
    project_areas = _cluster_project_areas(facets)

    # 5. Friction aggregation
    #    Sum friction_counts across all facets
    #    Group by tool to find tool-specific patterns
    #    Find top friction categories
    friction = _aggregate_friction(facets)

    # 6. Interaction style narrative
    #    Session type distribution (quick_question vs multi_task)
    #    Average complexity
    #    Tool switching patterns
    style = _analyze_interaction_style(facets, stats)

    # 7. Trends
    #    Weekly session counts
    #    Friction trend (compare last 2 weeks)
    #    Tool adoption changes
    trends = _compute_trends(facets)

    # 8. Suggestions (rule-based from friction patterns)
    #    AGENTS.md / CLAUDE.md / .cursorrules additions
    #    Tool recommendations per task type
    suggestions = _generate_suggestions(facets, friction, tool_comparison)

    # 9. Fun ending (pick most memorable session)
    fun = _pick_fun_ending(facets)

    return InsightsReport(...)
```

#### Integration with Existing Analytics

| Existing Module | How Insights Uses It |
|---|---|
| `analytics/friction.py` | Friction scores feed into facet `friction_score` and `friction_counts` |
| `analytics/similar.py` | TF-IDF vectors help cluster project areas and detect duplicate goals |
| `analytics/heatmap.py` | Activity data feeds into `TrendAnalysis.sessions_per_day` |
| `analytics/oracle.py` | Search infrastructure helps find example sessions for friction patterns |
| `storage/store.py` | All queries go through existing store; new methods added for facets |
| `models.py` | `SessionFacet` added as new model; `UnifiedSession` unchanged |

#### New Store Methods

```python
# Added to SessionStore
def upsert_facet(self, facet: SessionFacet) -> None: ...
def get_facet(self, session_id: str) -> SessionFacet | None: ...
def get_facets(self, source=None, since=None, project=None) -> list[SessionFacet]: ...
def get_unfaceted_sessions(self, since=None, limit=100) -> list[UnifiedSession]: ...
def get_insights_cache(self, range_hash: str) -> InsightsReport | None: ...
def set_insights_cache(self, range_hash: str, report: InsightsReport, ttl_hours=24) -> None: ...
def get_facet_stats(self) -> dict: ...
```

#### Example Workflows

```bash
# First time: analyze all sessions with heuristic (free, fast)
$ sagg analyze-sessions --since 30d
Analyzing 256 sessions (heuristic)...
  ████████████████████████████████████████ 256/256
Created 256 facets (heuristic_v1)

# View insights in TUI
$ sagg insights
[opens TUI with tabbed layout]

# Higher quality with LLM (auto-detects claude -p)
$ sagg analyze-sessions --since 7d --analyzer llm
Detected: claude -p (Claude Code CLI)
Analyzing 42 sessions via claude -p...
  ████████████████████████████████████████ 42/42
Created 42 facets (llm_v1 via claude)
Estimated cost: ~$0.50

# Force a specific CLI backend
$ sagg analyze-sessions --analyzer llm --llm-cli codex
Analyzing via codex...

# Compare tools, export HTML
$ sagg insights --source claude --source cursor --format html --open
[generates HTML, opens in browser]

# JSON for scripting
$ sagg insights --since 7d --format json > weekly-insights.json
```

#### Relationship to Other Planned Features

- **`sagg summarize` (§13.6)**: Summarize generates *work reports* ("what did I do"). Insights generates *meta-analysis* ("how am I working"). They share the LLM infrastructure (CLI backend) but serve different purposes.
- **`sagg analyze` (§13.2)**: Topic clustering feeds into insights' `project_areas` grouping. Insights is the consumer; analyze is the producer.
- **`sagg benchmark` (§16.3)**: Benchmark tracks per-suggestion acceptance. Insights uses higher-level per-session outcomes. Benchmark data could enrich facets in future.
- **`sagg session-dna` (§16.2)**: Session fingerprints could replace or supplement TF-IDF clustering in project area detection.
- **`sagg friction-points` (existing)**: Insights subsumes friction-points by aggregating friction across all sessions with cross-tool breakdown. The existing `friction-points` command remains useful for quick per-session checks.

#### Dependencies

```toml
# No new required dependencies.
# Heuristic analyzer: uses existing sagg code only.
# LLM analyzer: shells out to CLI tools already on user's PATH.
# TUI: uses existing textual dependency.
# HTML export: generates standalone HTML with inline CSS (no template engine needed).
```

#### Success Criteria

| Criteria | Metric |
|---|---|
| Heuristic analyzer covers all sessions | 100% of collected sessions get facets |
| LLM analyzer quality | Manual review: facets rated "accurate" ≥80% |
| Cross-tool comparison is actionable | ≥1 tool recommendation per task type |
| TUI loads fast | <3s for 500 sessions (from cached facets) |
| HTML report is shareable | Standalone file, no external deps |
| Incremental analysis | Only new/changed sessions re-analyzed |
| No new pip dependencies | CLI tools + heuristics only |

---

### 13.7.1 Insights v2: Extensible Heuristic Pipeline + LLM Map-Reduce

**Status**: Planned (replaces heuristic_v1 + current aggregator)
**Motivation**: The v1 heuristic analyzer extracts shallow signals (keyword matching on first user message, turn count thresholds, aggregate retry/error counts). Every trace contains rich structured data — tool calls, error results, user corrections, timing, file patterns — that can produce actionable insights *without any LLM*. The LLM layer should be a cherry on top, not a prerequisite for a useful report.

#### Design Principles

1. **Exhaust heuristics first.** Extract every computable signal from the structured trace data. The heuristic layer alone should produce a report worth reading.
2. **Extensible feature pipeline.** Adding a new signal means writing one function and registering it. Re-running `analyze-sessions --force` recomputes all facets with the new feature.
3. **LLM as map-reduce.** Batch facet JSONs into groups of 10-20, process in parallel, then reduce to a final narrative. LLM adds interpretation, not raw data.
4. **Structured HTML output.** The final report is a standalone HTML file with all data inline — no external deps, shareable, actionable.

#### Architecture

```
                    ┌─────────────────────────┐
                    │    UnifiedSession        │
                    │  (turns/messages/parts)  │
                    └───────────┬──────────────┘
                                │
                    ┌───────────▼──────────────┐
                    │   Feature Extractor       │
                    │   Pipeline (registry)     │
                    │                           │
                    │  ┌─ tool_call_stats ──┐   │
                    │  ├─ error_analysis ───┤   │
                    │  ├─ intervention ─────┤   │
                    │  ├─ timing ───────────┤   │
                    │  ├─ file_patterns ────┤   │
                    │  ├─ token_usage ──────┤   │
                    │  ├─ conversation_flow ┤   │
                    │  ├─ outcome_signals ──┤   │
                    │  └─ (add new here) ───┘   │
                    └───────────┬──────────────┘
                                │
                    ┌───────────▼──────────────┐
                    │   SessionFacetV2 (JSON)   │
                    │   ~40 attributes per      │
                    │   session, all computed    │
                    └───────────┬──────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                   │
    ┌─────────▼──────┐  ┌──────▼───────┐  ┌───────▼────────┐
    │   Heuristic     │  │  LLM Layer   │  │   HTML Report   │
    │   Aggregator    │  │  (map-reduce) │  │   Generator     │
    │   (always runs) │  │  (opt-in)    │  │                 │
    └─────────┬──────┘  └──────┬───────┘  └───────▲────────┘
              │                 │                   │
              └─────────────────┴───────────────────┘
                        InsightsReportV2
```

#### Feature Extractor Registry

Each feature extractor is a function that takes a `UnifiedSession` and returns a dict. Extractors are registered in a list. The pipeline runs all of them and merges results into the facet.

```python
from typing import Protocol

class FeatureExtractor(Protocol):
    """A single heuristic feature extractor."""
    name: str
    version: str

    def extract(self, session: UnifiedSession) -> dict:
        """Extract features from a session. Returns a flat or nested dict."""
        ...

# Registry — just a list. Add new extractors here.
EXTRACTORS: list[FeatureExtractor] = [
    ToolCallStatsExtractor(),
    ErrorAnalysisExtractor(),
    InterventionExtractor(),
    TimingExtractor(),
    FilePatternExtractor(),
    TokenUsageExtractor(),
    ConversationFlowExtractor(),
    OutcomeSignalsExtractor(),
    GoalClassificationExtractor(),
    ComplexityExtractor(),
]

def extract_facet(session: UnifiedSession) -> dict:
    """Run all extractors and merge into a single facet dict."""
    facet = {"session_id": session.id, "source": session.source.value}
    for extractor in EXTRACTORS:
        facet.update(extractor.extract(session))
    facet["analyzer_version"] = f"heuristic_v2"
    facet["extractor_versions"] = {e.name: e.version for e in EXTRACTORS}
    return facet
```

**To add a new feature**: Write a class with `name`, `version`, `extract()`. Append to `EXTRACTORS`. Run `sagg analyze-sessions --force` to recompute.

#### Feature Extractors: Complete Catalog

##### 1. `ToolCallStatsExtractor` — What tools were used and how

Walks every `Message.parts` looking for `ToolCallPart` instances.

| Output Key | Type | Description |
|---|---|---|
| `tool_calls_total` | `int` | Total tool call count |
| `tool_calls_by_name` | `dict[str, int]` | Per-tool call counts (`{Edit: 12, Read: 18, Bash: 9}`) |
| `tool_call_sequence` | `list[str]` | Ordered list of tool names as called (for pattern detection) |
| `unique_tools_used` | `int` | Number of distinct tools |
| `most_used_tool` | `str` | Tool with highest call count |
| `tool_diversity_ratio` | `float` | `unique_tools / total_calls` — high = exploratory, low = focused |
| `read_write_ratio` | `float` | `(Read+Grep+Glob) / (Edit+Write+Bash)` — >1 = exploration, <1 = modification |

**Adapter availability**: Claude (full), OpenCode (full), Codex (partial — no results), Cursor (none — text only), Gemini (full), Ampcode (full).

##### 2. `ErrorAnalysisExtractor` — What went wrong

Walks every `Message.parts` looking for `ToolResultPart` where `is_error=True`. Correlates back to the `ToolCallPart` that triggered it using `tool_id`.

| Output Key | Type | Description |
|---|---|---|
| `tool_results_total` | `int` | Total tool result count |
| `tool_errors_total` | `int` | Count of `ToolResultPart` with `is_error=True` |
| `error_rate` | `float` | `errors / total_results` (0.0–1.0) |
| `errors_by_tool` | `dict[str, int]` | Per-tool error counts (`{Bash: 3, Edit: 1}`) |
| `error_details` | `list[ErrorDetail]` | Up to 10 most significant errors |
| `first_error_turn_index` | `int\|None` | Which turn the first error occurred in |
| `error_free_streak_max` | `int` | Longest consecutive successful tool calls |
| `error_clustering` | `str` | `"early"` / `"middle"` / `"late"` / `"scattered"` — where errors concentrate |
| `error_recovery_rate` | `float` | Fraction of errors followed by a successful call to the same tool |

```python
class ErrorDetail:
    tool_name: str
    tool_id: str
    input_preview: str     # First 100 chars of tool input
    error_preview: str     # First 200 chars of error output
    turn_index: int
    recovered: bool        # Was the same tool called successfully later?
```

**Adapter availability**: Claude (full), OpenCode (full), Codex (no — missing ToolResultPart), Cursor (no), Gemini (full), Ampcode (full). For Codex/Cursor, `tool_errors_total` will be 0 and fields will have safe defaults.

##### 3. `InterventionExtractor` — When the user corrected the agent

Detects user messages that are *corrections* or *redirections*. A user message is classified as an intervention when:
- It follows an assistant message that contained a tool error
- It is short (<100 chars) and contains correction language ("no", "don't", "instead", "wrong", "stop", "actually", "rather", "use X not Y")
- It follows an assistant message and precedes a different approach (tool name change)

| Output Key | Type | Description |
|---|---|---|
| `intervention_count` | `int` | Total user corrections/redirections |
| `intervention_details` | `list[InterventionDetail]` | Up to 10 intervention records |
| `intervention_rate` | `float` | `interventions / user_messages` (0.0–1.0) |
| `post_error_interventions` | `int` | Interventions that directly followed a tool error |
| `proactive_redirections` | `int` | Interventions where user preemptively changed direction (no prior error) |

```python
class InterventionDetail:
    turn_index: int
    user_text: str           # The correction message (full text)
    trigger: str             # "post_error" | "proactive" | "rejection"
    preceding_tool: str|None # What tool was used before the intervention
    following_tool: str|None # What tool was used after the intervention
```

##### 4. `TimingExtractor` — Session and turn timing patterns

Uses `Turn.started_at` / `Turn.ended_at` and `Message.timestamp`.

| Output Key | Type | Description |
|---|---|---|
| `session_duration_ms` | `int\|None` | From `UnifiedSession.duration_ms` or computed from first/last turn |
| `avg_turn_duration_ms` | `float\|None` | Average time per turn |
| `max_turn_duration_ms` | `int\|None` | Longest single turn (indicator of complexity or stuck) |
| `time_to_first_tool_call_ms` | `int\|None` | How quickly the agent started working |
| `time_to_first_error_ms` | `int\|None` | How early the first problem hit |
| `active_time_ratio` | `float\|None` | Ratio of sum-of-turn-durations to total session duration (gaps = user thinking) |

**Adapter availability**: Claude (full timestamps), OpenCode (full), Codex (has timestamps), Cursor (degraded — session-level only), Gemini (full), Ampcode (no — uses `datetime.now()`). For adapters with degraded timing, fields return `None`.

##### 5. `FilePatternExtractor` — What files were touched and how

Uses `SessionStats.files_modified`, tool call inputs (for `Edit`/`Write`/`Read` tools), and file extension mapping.

| Output Key | Type | Description |
|---|---|---|
| `files_modified` | `list[str]` | All files written/edited (from stats + tool calls) |
| `files_read` | `list[str]` | Files read but not modified (exploration signals) |
| `files_read_only` | `list[str]` | `files_read - files_modified` |
| `file_count_modified` | `int` | Count of modified files |
| `file_count_read` | `int` | Count of read files |
| `languages_touched` | `dict[str, int]` | Language distribution by file count (`{python: 8, yaml: 2}`) |
| `primary_language` | `str\|None` | Most frequent language |
| `files_pattern` | `str` | `"python_backend"` / `"react_frontend"` / `"config"` / `"docs"` / `"testing"` / `"mixed"` |
| `test_files_touched` | `bool` | Whether any test files were modified |
| `config_files_touched` | `bool` | Whether any config files were modified |
| `scope` | `str` | `"single_file"` / `"single_dir"` / `"multi_dir"` / `"cross_project"` |

##### 6. `TokenUsageExtractor` — Token consumption patterns

Uses `Message.usage` (per-message `TokenUsage`) and `UnifiedSession.models`.

| Output Key | Type | Description |
|---|---|---|
| `total_input_tokens` | `int` | Sum of all input tokens |
| `total_output_tokens` | `int` | Sum of all output tokens |
| `total_tokens` | `int` | Input + output |
| `cached_tokens` | `int` | Sum of cached tokens (context window efficiency) |
| `cache_hit_ratio` | `float` | `cached / input` — high = good context reuse |
| `tokens_per_turn` | `float` | Average tokens per turn |
| `models_used` | `list[str]` | Model IDs used in session |
| `primary_model` | `str\|None` | Most-used model by message count |
| `cost_estimate_usd` | `float\|None` | Estimated cost (if pricing data available) |

**Adapter availability**: Claude (full), OpenCode (full), Codex (partial — last message only), Cursor (no per-message), Gemini (full), Ampcode (full). Fields default to 0 when not available.

##### 7. `ConversationFlowExtractor` — How the conversation went

Analyzes the sequence of roles and message characteristics across the session.

| Output Key | Type | Description |
|---|---|---|
| `user_messages_count` | `int` | Total user messages |
| `assistant_messages_count` | `int` | Total assistant messages |
| `avg_user_message_length` | `float` | Average user message length in chars (short = precise commands, long = context dumps) |
| `avg_assistant_message_length` | `float` | Average assistant message length |
| `max_user_message_length` | `int` | Longest user message |
| `user_message_lengths` | `list[int]` | Distribution of user message lengths (for pattern detection) |
| `turn_count` | `int` | Number of turns |
| `back_and_forth_count` | `int` | Short user messages (<50 chars) after assistant — corrections/follow-ups |
| `conversation_pattern` | `str` | `"single_shot"` (1-2 turns) / `"iterative"` (many short exchanges) / `"detailed_briefing"` (long first msg, few follow-ups) / `"evolving"` (messages get longer over time) |
| `first_user_message_length` | `int` | Length of the opening request (indicates how much context was provided upfront) |

##### 8. `OutcomeSignalsExtractor` — Did it work?

Smarter outcome detection than v1. Looks at multiple signals from the end of the session.

| Output Key | Type | Description |
|---|---|---|
| `outcome` | `str` | `"fully_achieved"` / `"partially_achieved"` / `"abandoned"` / `"unclear"` |
| `completion_confidence` | `float` | 0.0–1.0 |
| `outcome_signals` | `list[str]` | What signals contributed to the assessment |
| `last_message_role` | `str` | Who spoke last |
| `session_ended_cleanly` | `bool` | Last message was assistant with no pending errors |
| `had_late_errors` | `bool` | Errors in the final 20% of the session |
| `user_expressed_satisfaction` | `bool\|None` | Detected "thanks", "perfect", "great" etc. in last user messages |
| `user_expressed_frustration` | `bool\|None` | Detected "wrong", "no", "stop", "ugh" etc. in last user messages |

**Outcome logic (v2)**:
1. If session has 0-1 turns → `abandoned` (confidence 0.7)
2. If last user message contains satisfaction language → `fully_achieved` (confidence 0.8)
3. If last user message contains frustration language → `partially_achieved` (confidence 0.7)
4. If last message is assistant, no late errors, error_rate < 0.2 → `fully_achieved` (confidence 0.6 + turn bonus)
5. If error_rate > 0.4 or intervention_rate > 0.3 → `partially_achieved` (confidence 0.5)
6. Otherwise → `unclear` (confidence 0.3)

##### 9. `GoalClassificationExtractor` — What was the user trying to do

Enhanced goal extraction from v1. Looks beyond just the first message.

| Output Key | Type | Description |
|---|---|---|
| `underlying_goal` | `str` | First user message text (truncated to 200 chars) |
| `goal_categories` | `dict[str, int]` | Keyword-matched categories from all user messages |
| `task_type` | `str` | Primary task classification |
| `session_type` | `str` | `"quick_question"` / `"single_task"` / `"multi_task"` / `"iterative_refinement"` |
| `goal_evolution` | `bool` | Whether the goal changed mid-session (detected by new categories appearing in later messages) |
| `multi_goal` | `bool` | Whether multiple distinct goal categories were detected |

##### 10. `ComplexityExtractor` — How complex was the work

| Output Key | Type | Description |
|---|---|---|
| `complexity_score` | `int` | 1-5 composite score |
| `complexity_factors` | `dict[str, int]` | What contributed (`{turns: 2, tools: 1, files: 1, errors: 1}`) |
| `brief_summary` | `str` | Auto-generated summary: title/goal + stats |

**Complexity scoring v2**:
- Base 1
- `+1` if turn_count > 5
- `+1` if turn_count > 15
- `+1` if tool_calls_total > 20 OR unique_tools_used > 5
- `+1` if file_count_modified > 5 OR scope == "multi_dir"
- `+1` if error_rate > 0.3 OR intervention_count > 3
- Cap at 5

#### Updated Facet Schema (v2)

The `session_facets` table gets a new `facet_json` column that stores the complete extractor output as JSON. The existing typed columns remain for indexed queries.

```sql
-- Migration v4 → v5
ALTER TABLE session_facets ADD COLUMN facet_json TEXT;
-- facet_json contains the full extractor output (all ~40 attributes)
-- Existing columns (outcome, task_type, friction_score, etc.) remain
-- for indexed SQL queries. facet_json is the source of truth for
-- aggregation and reporting.
```

This means:
- **Existing columns** = fast SQL queries (`WHERE outcome = 'fully_achieved'`)
- **facet_json** = full richness for aggregation and HTML reports
- Adding a new extractor only requires re-running analysis — no schema migration

#### LLM Layer: Map-Reduce on Facet JSONs

The LLM layer operates on the *already-extracted* facet JSONs, not raw transcripts. This makes LLM calls much cheaper (facets are ~1KB each vs ~8KB condensed transcripts) and the prompts more focused.

```
Phase 1: MAP (parallel)
────────────────────────
  facets[0:10]   → LLM → batch_summary_1
  facets[10:20]  → LLM → batch_summary_2
  facets[20:30]  → LLM → batch_summary_3
  ...
  (asyncio.gather or subprocess pool — max 5 concurrent)

Phase 2: REDUCE (single call)
──────────────────────────────
  [batch_summary_1, batch_summary_2, ...] → LLM → final_narrative

Output of REDUCE:
  {
    "executive_summary": "...",       # 2-3 sentence overview
    "tool_narratives": {              # Per-tool natural language analysis
      "claude": "You use Claude primarily for...",
      "cursor": "Cursor sessions tend to be..."
    },
    "pattern_insights": [...],        # Patterns the heuristic can't detect
    "agents_md_suggestions": [...],   # LLM-quality suggestions with actual content
    "workflow_recommendations": [...] # "Based on your error patterns, try..."
  }
```

**MAP prompt** (per batch of 10-20 facets):
```
You are analyzing AI coding session data. Below are {n} session facets
extracted from {tools} sessions over the past {period}.

Each facet contains: tool_calls_total, error_rate, errors_by_tool,
intervention_count, outcome, task_type, primary_language, complexity_score,
conversation_pattern, and more.

Summarize patterns in this batch:
1. What tools are being used for what? Success rates?
2. Where are errors concentrating? Which tools/operations?
3. Are there user intervention patterns? What triggers corrections?
4. What's working well vs. causing friction?

Respond with JSON: {batch_summary_schema}

Session facets:
{facets_json}
```

**REDUCE prompt** (on all batch summaries):
```
You are generating a final insights report from {n} batch summaries
covering {total} sessions across {tools} tools over {period}.

Synthesize into a cohesive narrative:
1. Executive summary (2-3 sentences)
2. Per-tool analysis (what each tool is good/bad at)
3. Cross-tool patterns (things that happen regardless of tool)
4. Actionable AGENTS.md suggestions (specific, with evidence)
5. Workflow recommendations (what to change)

Be direct and specific. Reference actual numbers.

Respond with JSON: {final_report_schema}

Batch summaries:
{summaries_json}
```

#### Heuristic Aggregator v2

The aggregator works on the full facet JSONs (not the limited set of columns). Fixed bugs from v1:

1. **`affected_tools` bug fixed**: v1 used a dict comprehension that overwrote per-source (last write wins). v2 uses `defaultdict(list)`.
2. **No hardcoded suggestions**: All suggestions derived from actual data patterns.
3. **Richer tool comparison**: Uses `read_write_ratio`, `error_rate`, `intervention_rate`, `avg_user_message_length`, not just success/friction.
4. **Trend computation**: Weekly windows instead of half-split. Detects tool adoption changes.

#### HTML Report Generator

Standalone HTML file with inline CSS. No external dependencies.

**Structure**:
```
┌────────────────────────────────────────────────────────┐
│  sagg insights · 256 sessions · Jan 25–Feb 25, 2026   │
│  Tools: Claude (83) · Cursor (89) · OpenCode (84)     │
├────────────────────────────────────────────────────────┤
│                                                        │
│  ┌─ At a Glance ───────────────────────────────────┐  │
│  │ Working: ...                                     │  │
│  │ Hindering: ...                                   │  │
│  │ Quick win: ...                                   │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌─ Tool Comparison ───────────────────────────────┐  │
│  │ Table with bar charts (CSS-rendered)             │  │
│  │ Success rate bars, friction bars                  │  │
│  │ "Best for" recommendations                       │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌─ Error Hotspots ────────────────────────────────┐  │
│  │ Top errored tools with counts                    │  │
│  │ Error clustering patterns                        │  │
│  │ Recovery rate by tool                            │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌─ User Intervention Patterns ────────────────────┐  │
│  │ When you had to correct the agent                │  │
│  │ Most common triggers                             │  │
│  │ Post-error vs. proactive redirections            │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌─ Friction Analysis ─────────────────────────────┐  │
│  │ Top friction categories                          │  │
│  │ Per-tool friction breakdown                      │  │
│  │ Trend over time                                  │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌─ Conversation Patterns ─────────────────────────┐  │
│  │ How you talk to each tool                        │  │
│  │ Message length distributions                     │  │
│  │ Conversation flow types                          │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌─ Suggestions ───────────────────────────────────┐  │
│  │ AGENTS.md / CLAUDE.md / .cursorrules additions   │  │
│  │ Each with copy button and evidence               │  │
│  │ Tool recommendations per task type               │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌─ Trends ────────────────────────────────────────┐  │
│  │ Activity over time (CSS bar chart)               │  │
│  │ Friction trend / Productivity trend              │  │
│  │ Tool adoption over time                          │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌─ LLM Narrative (if available) ──────────────────┐  │
│  │ Executive summary from map-reduce                │  │
│  │ Per-tool narratives                              │  │
│  │ Pattern insights                                 │  │
│  │ Workflow recommendations                         │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌─ Fun Ending ────────────────────────────────────┐  │
│  │ Most dramatic / impressive session               │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  Generated by sagg v1.3 · https://github.com/...      │
└────────────────────────────────────────────────────────┘
```

**HTML design constraints**:
- Single file, all CSS inline in `<style>` block
- No JavaScript required for core functionality (progressive enhancement OK for copy buttons)
- Inter/system font stack
- Card-based layout with subtle borders
- Bar charts rendered as CSS `<div>` with percentage widths
- Dark mode via `prefers-color-scheme` media query
- Mobile-responsive (single column on narrow screens)
- Copy buttons on suggestions use `navigator.clipboard.writeText()`

#### Updated CLI Interface

```bash
# Analyze with v2 heuristic pipeline (default)
sagg analyze-sessions --since 30d
# Produces facets with ~40 attributes per session

# Force re-analysis (e.g., after adding new extractor)
sagg analyze-sessions --force --since 30d

# Analyze + run LLM map-reduce on top
sagg analyze-sessions --since 30d --analyzer llm
# Phase 1: Heuristic extraction (all sessions)
# Phase 2: LLM map-reduce on facet JSONs (batches of 10-20)

# Generate HTML report (heuristic data only — no LLM needed)
sagg insights --format html --output report.html --open

# Generate HTML with LLM narratives merged in
sagg insights --format html --with-llm --output report.html --open

# CLI summary (quick terminal view)
sagg insights --format cli

# JSON for scripting
sagg insights --format json -o data.json
```

#### Implementation Phases

**Phase A**: Feature extractor pipeline + 10 extractors → replaces `heuristic.py`
**Phase B**: Aggregator v2 → replaces `aggregator.py` (fixes bugs, uses full facet_json)
**Phase C**: HTML report generator → replaces "coming soon" stub
**Phase D**: LLM map-reduce layer → replaces current per-session LLM approach

#### Success Criteria (v2)

| Criteria | Metric |
|---|---|
| Heuristic facet has >=30 attributes per session | Count distinct keys in facet_json |
| Adding a new extractor requires no schema migration | Only code change + `--force` re-run |
| HTML report renders without external dependencies | Single file, no CDN links |
| LLM cost reduced vs v1 | Facet-based batching uses ~60% fewer tokens than transcript batching |
| Heuristic-only report is actionable | Contains error hotspots, intervention patterns, tool comparison — without LLM |

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
| `sagg session-dna` | Create fingerprints for coding sessions so you can find when you've solved similar problems before | Medium |
| `sagg benchmark` | Track which AI tools work best for different tasks in your codebase (speed, accuracy, cost per language/project type) | High |

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

### High-Priority New Features (Detailed)

#### 16.1 `sagg init` - Setup wizard

**The problem**: Setting up sagg is annoying. You have to figure out where each AI tool stores its data, write config files, and hope you got the paths right.

**What we'll build**: A setup command that finds your tools and writes the config for you.

```bash
$ sagg init

Looking for AI tools...

✅ Found Claude Code: ~/.claude/projects (567 sessions)
✅ Found Cursor: ~/Library/Application Support/Cursor/... (89 sessions)
✅ Found OpenCode: ~/.local/share/opencode/storage (1,234 sessions)
❌ Codex: not installed
❌ Ampcode: not found (need to install amp CLI)

Enable Claude Code? [Y/n] Y
Enable Cursor? [Y/n] Y
Enable OpenCode? [Y/n] Y
Custom paths? [y/N] N

Created ~/.sagg/config.toml
Run 'sagg collect' to import your sessions.
```

**How it works**:
- Use the existing `isAvailable()` and `getDefaultPath()` adapter methods
- Show what it found with session counts
- Ask which ones to enable (default to yes for found tools)
- Generate the config file
- Set up the database

#### 16.2 Session fingerprints - Find past solutions

**The problem**: You solve the same authentication bug three times because you forgot about the previous solutions.

**What we'll build**: "DNA" fingerprints for each session that let you find similar past work.

**Session fingerprint**:
```typescript
interface SessionDNA {
  intentHash: string;        // What problem were you solving?
  filesSignature: string;    // What types of files did you touch?
  toolSequence: string;      // What tools did you use in what order?
  outcomeType: string;       // Did it work? fail? get abandoned?
  complexityScore: number;   // How big was the change? (1-10)
}
```

**Why this works**:
- **Duplicate detection**: "You debugged JWT validation in auth.py two weeks ago"
- **Solution reuse**: "Here's a session with 95% similar fingerprint that worked"
- **Pattern recognition**: "You always use Claude for debugging, Cursor for UI work"
- **Team knowledge**: "Sarah solved something similar - here's her approach"

**Commands**:
```bash
$ sagg session-dna ses_abc123
🧬 Fingerprint: auth_validation_7a8b9c2d
   Problem: JWT token validation bug
   Files: Python auth modules (3 files)
   Tools: read→research→edit→test→debug
   Result: Fixed (2 tries, 18 minutes)

$ sagg similar --dna 7a8b9c2d
Found 3 similar sessions:
   ses_def456 (98% match) - "Fix token expiry" - worked on first try
   ses_ghi789 (87% match) - "Auth middleware bug" - took 3 attempts
   ses_jkl012 (82% match) - "JWT parsing error" - different approach
```

**Technical approach**:
1. **Intent extraction**: Use embeddings to hash the problem description
2. **File patterns**: Generate signature from file types and directory structure
3. **Tool sequence**: Create normalized pattern of tool usage
4. **Fast search**: Use LSH (Locality-Sensitive Hashing) to find similar fingerprints
5. **Storage**: New table for session fingerprints with indexed components

#### 16.3 AI tool benchmarking - Which tool works best?

**The problem**: You have Claude, Cursor, Codex, and others. Which one should you use for Python debugging? React components? Nobody knows.

**What we'll build**: Performance tracking that tells you which AI tool works best for different types of work in your codebase.

**What we'll measure**:
```typescript
interface PerformanceData {
  // Speed
  timeToCompletion: number;          // Minutes from start to working solution
  iterationsNeeded: number;          // How many back-and-forth rounds
  acceptanceRate: number;            // % of suggestions you actually used

  // Quality
  successRate: number;               // % of tasks that actually got finished
  bugRate: number;                   // How often the suggestion broke something
  codeQuality: number;               // Did it improve or hurt the code?

  // Cost
  costPerTask: number;               // Dollar cost (tokens + tool fees)
  tokenEfficiency: number;           // Useful changes per token spent

  // Context
  taskType: string;                  // bugfix, feature, refactor, docs
  language: string;                  // python, javascript, go, etc
  projectSize: number;               // How complex is this codebase?
  developerSkill: string;            // junior, mid, senior
}
```

**Database changes**:
```sql
-- Track every suggestion and what happened to it
CREATE TABLE suggestion_events (
  id TEXT PRIMARY KEY,
  session_id TEXT,
  tool_name TEXT,              -- claude-sonnet, cursor, codex
  event_type TEXT,             -- suggested, accepted, rejected, edited
  task_type TEXT,              -- bugfix, feature, refactor (auto-detected)
  language TEXT,               -- from file extension
  suggestion_size INTEGER,     -- lines or tokens
  time_to_decision INTEGER,    -- seconds to accept/reject
  timestamp INTEGER
);

-- Track task outcomes
CREATE TABLE task_results (
  task_id TEXT PRIMARY KEY,
  session_id TEXT,
  completed BOOLEAN,           -- Did you finish the task?
  duration_minutes INTEGER,    -- Start to finish
  attempts INTEGER,            -- How many tries did it take?
  files_changed INTEGER,
  tests_passed BOOLEAN,
  cost_dollars DECIMAL(8,4),
  created_at INTEGER
);
```

**Output example**:
```bash
$ sagg benchmark --task-type bugfix --language python

Python debugging performance (last 30 days, 47 tasks):

Claude Sonnet:     ⭐⭐⭐⭐⭐ (best choice)
├ Success rate:    94% (44/47 tasks completed)
├ Average time:    12.3 minutes
├ Acceptance rate: 87% (you used most suggestions)
├ Average cost:    $0.45 per task
└ Iterations:      2.1 tries per task

Cursor:            ⭐⭐⭐⭐⚬
├ Success rate:    89% (39/44 tasks)
├ Average time:    18.7 minutes
├ Acceptance rate: 71%
├ Average cost:    $0.31 per task
└ Iterations:      2.8 tries per task

Recommendation: Use Claude Sonnet for Python bugs.
34% faster than Cursor, higher success rate.
$0.14 more expensive but saves 6.4 minutes per task.

Confidence: High (47 tasks analyzed, statistically significant)
```

**Auto-routing**:
```bash
$ sagg route --prompt "Fix this auth bug in auth.py"
Best tool: Claude Sonnet
Predicted: 89% success, ~11 minutes, $0.43 cost
Starting Claude session...
```

**Implementation steps**:
1. **Event collection**: Track every suggestion, acceptance, rejection
2. **Task detection**: Auto-classify what type of work is happening
3. **Statistical analysis**: Calculate confidence intervals, handle bias
4. **Recommendations**: Multi-factor scoring (speed + cost + quality)
5. **Smart routing**: Real-time tool suggestions based on current context

### What makes these features different

Most session trackers just store data. These features actually help you code better.

**The real value**: You've already got all this AI session data sitting around. Instead of just letting it pile up, use it to avoid repeating yourself and pick the right tool for each job.

**Why this combination works**: `sagg init` gets you started quickly, session fingerprints help you reuse past solutions, and benchmarking tells you which AI tool actually works best for your code. Together they turn your session history into something useful.

---

## 17. Trajectory Visualization: Hodoscope Integration

**Added:** 2026-02-22

### What is Hodoscope

[Hodoscope](https://github.com/AR-FORUM/hodoscope) is an unsupervised agent trajectory analysis tool. It takes raw session logs, summarizes each agent action via LLM, embeds them into a shared vector space, and renders interactive t-SNE/UMAP scatter plots. Density diffing (KDE overlay) shows exactly where two agent configurations diverge behaviorally.

### How It Fits Into sagg

```
sagg collect → session JSONL → hodoscope analyze → embed → t-SNE viz
                                                  → KDE density diff
```

- Feed collected session JSONL files directly into `hodoscope analyze`
- Use `--group-by` on sagg metadata fields (e.g., `source`, `pain_score`, `model`, `project`) to compare behavioral clusters across tools or sessions
- Density overlay pinpoints where high-pain sessions diverge from low-pain ones — ideal for `sagg friction-points` follow-up

### Integration Paths

**Option 1: Hodoscope CLI (immediate, zero infra)**
```bash
pip install hodoscope
hodoscope analyze ~/.sagg/sessions/claude/*.jsonl
hodoscope viz *.hodoscope.json --group-by source --open
```
Best for: exploration, validating whether behavioral clusters are meaningful before engineering effort.

**Option 2: Native sagg pipeline (production)**
Replicate Hodoscope's core inside sagg using LiteLLM + UMAP:
- `sagg viz` subcommand
- Integrates directly with `sessions.db`
- Feeds into `sagg analyze` (§13.2) clustering pipeline
- No external dependency

### Recommendation

Start with Hodoscope CLI to validate patterns visually. If clusters show clear separation (e.g., high-pain vs. low-pain sessions group distinctly), port the summarize→embed→project pipeline natively into `sagg analyze` (§13.2).

### References

- [Hodoscope GitHub](https://github.com/AR-FORUM/hodoscope)
- [Hodoscope PyPI](https://pypi.org/project/hodoscope/)
- Zhong et al., *Hodoscope: Unsupervised Behavior Discovery in AI Agents* (2026)

---

## 18. References

- [AgentTrace Specification](https://agent-trace.dev)
- [Agent Prism Components](https://github.com/evilmartians/agent-prism)
- [cursor-chat-browser](https://github.com/thomas-pedersen/cursor-chat-browser)
- [claude-code-viewer](https://github.com/esc5221/claude-code-viewer)
- [OpenLLMetry](https://github.com/traceloop/openllmetry)
- [Langfuse](https://github.com/langfuse/langfuse)

---

## 19. Fine-Tuning Data Export Pipeline

**Added:** 2026-02-25
**Priority:** v0.2
**Motivation:** sagg already parses all session logs into `UnifiedSession` with full turn/message/tool_call structure. The missing piece is a fine-tuning exporter + judge pass that turns these sessions into high-quality training data automatically.

### 19.1 Problem

Coding session logs are valuable fine-tuning data (real human-AI collaboration, not synthetic), but they sit in raw JSONL with no quality filtering, PII scrubbing, or standard training format. Tools like DataClaw (https://github.com/peteromallet/dataclaw) prove the pattern works — but they publish publicly. We need a private, filtered, local-first version integrated into sagg.

### 19.2 Design

Three-stage pipeline:

```
sagg collect
    -> sagg export --format finetune   (convert to ShareGPT JSONL)
    -> sagg judge                      (LLM quality scoring 0/1/2)
    -> sagg publish                    (push to private HuggingFace repo)
```

Each stage is independently runnable (composable). Output at each stage is a JSONL file.

### 19.3 Stage 1: Fine-Tune Exporter (`sagg export --format finetune`)

**New file:** `src/sagg/export/finetune.py`

**Output format:** ShareGPT (industry standard, compatible with LLaMA-Factory, Axolotl, Unsloth, TRL):

```jsonl
{
  "conversations": [
    {"from": "human", "value": "<user turn text>"},
    {"from": "gpt", "value": "<assistant turn text>"}
  ],
  "source": "claude",
  "session_id": "abc123",
  "project": "/home/user/myproject",
  "model": "claude-sonnet-4-5",
  "tool_calls": 3,
  "input_tokens": 1200,
  "output_tokens": 400,
  "quality_score": null
}
```

**Filtering rules (pre-judge):**
- Skip turns with < 2 messages (no real exchange)
- Skip turns where assistant response is < 50 chars (likely error/refusal)
- Skip turns where user message is < 10 chars
- Skip turns with only tool calls and no assistant text
- Optionally skip turns where `is_error=True` on all tool results

**Multi-turn support:** Configurable. Default: export each turn as a standalone conversation. `--multi-turn` flag: export full session as one conversation with all turns.

**CLI:**
```bash
sagg export --format finetune --output finetune.jsonl
sagg export --format finetune --since 30d --source claude --output finetune.jsonl
sagg export --format finetune --multi-turn --output finetune_full.jsonl
```

### 19.4 Stage 2: LLM Judge Pass (`sagg judge`)

**New command:** `sagg judge`

Scores each (prompt, response) pair using an LLM judge. Same 0/1/2 rubric as the Bullshit Benchmark (https://github.com/petergpt/bullshit-benchmark):

```
0 = Low quality: vague, hallucinated, wrong, or unhelpful response
1 = Partial quality: correct but incomplete or poorly structured
2 = High quality: correct, clear, complete, useful
```

**Judge prompt template:**
```
You are evaluating the quality of an AI coding assistant response.

User request:
{user_message}

Assistant response:
{assistant_message}

Score this response 0, 1, or 2:
0 = Low quality (vague, wrong, or unhelpful)
1 = Partial quality (correct but incomplete)
2 = High quality (correct, clear, complete)

Respond with ONLY the number.
```

**Implementation:**
- Uses LLM via CLI tools (same pattern as `sagg analyze-sessions --analyzer llm`): `claude -p`, `gemini`, or `codex`
- No SDK dependency
- Panel of judges (configurable, default: 1 judge)
- Batched with configurable concurrency (default: 5 concurrent)
- Writes `quality_score` field back to JSONL

**CLI:**
```bash
sagg judge --input finetune.jsonl --output scored.jsonl --model claude
sagg judge --input finetune.jsonl --output scored.jsonl --model gemini --concurrency 10
sagg judge --input finetune.jsonl --output scored.jsonl --filter-score 1  # only emit score >= 1
```

**Cost estimate:** ~100 tokens per judge call. 1000 sessions x 5 turns avg = 5000 calls = ~500K tokens. At Claude Haiku pricing: ~$0.05. Cheap.

### 19.5 Stage 3: Redaction (`sagg redact`)

**New command:** `sagg redact` (or flag on export)

Scrubs PII and secrets before any export or publish step. Hooks into the existing `src/sagg/security/` module.

**Redaction targets:**
- API keys and tokens (regex patterns: `sk-`, `Bearer `, `ghp_`, etc.)
- File paths containing username (replace with `~`)
- Email addresses
- Configurable custom patterns via `~/.sagg/config.toml` `[redact]` section

**CLI:**
```bash
sagg export --format finetune --redact --output finetune.jsonl
# or standalone
sagg redact --input finetune.jsonl --output redacted.jsonl
```

### 19.6 Stage 4: Publish (`sagg publish`)

**New command:** `sagg publish`

Pushes final JSONL to a private HuggingFace dataset repo. Requires `HF_TOKEN` env var.

**Safety gates (mandatory, cannot be skipped):**
1. `--no-push` dry-run first (shows row count, sample rows, PII scan summary)
2. Explicit `--confirm` flag required to actually push
3. Prompts for repo name if not configured

**CLI:**
```bash
sagg publish --input scored.jsonl --repo username/my-coding-sessions --no-push
sagg publish --input scored.jsonl --repo username/my-coding-sessions --confirm
```

**Full pipeline (one-liner):**
```bash
sagg collect --since 30d && \
sagg export --format finetune --redact --since 30d --output /tmp/raw.jsonl && \
sagg judge --input /tmp/raw.jsonl --filter-score 1 --output /tmp/scored.jsonl && \
sagg publish --input /tmp/scored.jsonl --repo jayshah5696/jay-bench-coding --no-push
```

### 19.7 Data Model Changes

Add `quality_score` and `export_format` to existing `SessionStats` or as a separate `FinetuneRecord` model:

```python
class FinetuneRecord(BaseModel):
    session_id: str
    source: SourceTool
    project: str | None
    model: str | None
    conversations: list[dict]   # ShareGPT format
    tool_calls: int
    input_tokens: int
    output_tokens: int
    quality_score: int | None = None  # 0, 1, 2 from judge
    judge_model: str | None = None
    exported_at: datetime
```

### 19.8 File Structure

```
src/sagg/
    export/
        finetune.py          # NEW: ShareGPT exporter + FinetuneRecord model
    security/
        redactor.py          # EXTEND: add API key + path patterns
    cli.py                   # EXTEND: add judge, redact, publish subcommands
```

### 19.9 Inspiration and References

- **DataClaw** (https://github.com/peteromallet/dataclaw): session log → HuggingFace pipeline with PII redaction. DataClaw is public-first; sagg's pipeline is private-first.
- **Bullshit Benchmark** (https://github.com/petergpt/bullshit-benchmark): LLM judge panel with 0/1/2 rubric. Same pattern for quality scoring.
- **Oxen.ai** (https://docs.oxen.ai): versioned dataset platform with batch LLM annotation. sagg's judge pass replicates their "batch inference for labeling" feature locally.
- **LLaMA-Factory / Axolotl / Unsloth**: target fine-tuning frameworks that consume ShareGPT JSONL natively.
- **AgentTrace** (https://agent-trace.dev): existing sagg export format. Fine-tune export is a parallel track, not a replacement.

### 19.10 Success Criteria

- `sagg export --format finetune` produces valid ShareGPT JSONL from any collected session
- `sagg judge` scores and filters sessions without SDK dependencies (CLI-tool-only approach)
- `sagg redact` catches all API keys and file-path PII in test fixtures
- `sagg publish --no-push` dry-run completes before any network call
- Full pipeline (collect → export → judge → publish) runs end-to-end in < 5 minutes for 1000 sessions

---

## 20. `sagg learn` - Knowledge Base That Grows Over Time

**Added:** 2026-02-25
**Priority:** v1.4
**Inspired by:** [Hermes Agent](https://github.com/NousResearch/hermes-agent) persistent memory and skills system

### 20.1 Problem

sagg collects and analyzes sessions, but the insights are ephemeral -- you run `sagg insights` or `sagg friction-points`, read the output, and the knowledge disappears from context. Meanwhile, your session history contains a wealth of accumulated knowledge:

- **Patterns**: "Claude handles Python refactoring better than Cursor", "always run tests before committing in project X"
- **Solutions**: Multi-step workflows that solved hard problems (Docker CI setup, auth debugging, migration scripts)
- **Preferences**: Which tools, models, and approaches work best for your specific projects

Hermes Agent solves this for a single agent with `MEMORY.md` (bounded curated notes) and a skills system (procedural knowledge documents). But Hermes only sees its own sessions. sagg sees *all* sessions across *all* tools -- it can build a richer, cross-tool knowledge base automatically.

### 20.2 Design Overview

Two knowledge stores, both auto-populated from session history:

```
sagg learn
    ├── Learned Patterns (memory)     -- bounded, curated, declarative facts
    │   "Claude is 34% faster for Python debugging"
    │   "Project X uses ruff + pytest, Python 3.12"
    │   "User prefers small commits, avoids subagents"
    │
    └── Skill Library (skills)        -- procedural, searchable, shareable
        "How to set up Docker CI for Python projects"
        "JWT auth debugging workflow (read → test → fix → verify)"
        "Data pipeline: polars ingestion → validation → export"
```

The `sagg learn` command processes new sessions since the last run, extracts patterns and skills, and updates the knowledge base. Running `sagg learn --refresh` re-processes recent sessions to update stale knowledge.

### 20.3 Architecture

```
┌───────────────────────────────────────────────────────────────────┐
│                         sagg learn                                 │
│                                                                    │
│  ┌────────────────────┐   ┌─────────────────────────────────────┐ │
│  │  Learner (orchestr.)│   │           Data Sources               │ │
│  │                     │   │                                      │ │
│  │  1. Get new sessions│◄──┤  SessionStore (existing sessions)   │ │
│  │  2. Extract patterns│   │  SessionFacets (existing analysis)  │ │
│  │  3. Extract skills  │   │  FrictionPoints (existing friction) │ │
│  │  4. Update stores   │   │  ToolComparison (from insights)     │ │
│  │  5. Save state      │   │                                      │ │
│  └─────┬──────┬────────┘   └─────────────────────────────────────┘ │
│        │      │                                                    │
│   ┌────▼────┐ ┌▼──────────┐                                       │
│   │ Pattern │ │   Skill   │                                       │
│   │ Memory  │ │ Extractor │                                       │
│   │         │ │           │                                       │
│   │ ~/.sagg/│ │ ~/.sagg/  │                                       │
│   │ knowledge/ knowledge/ │                                       │
│   │ memory.md  skills/    │                                       │
│   └─────────┘ └───────────┘                                       │
│                                                                    │
│  Storage: ~/.sagg/knowledge/                                       │
│  ├── memory.md              # Learned patterns (bounded, curated) │
│  ├── projects/              # Per-project knowledge profiles      │
│  │   ├── my-app.md                                                │
│  │   └── backend-api.md                                           │
│  ├── skills/                # Extracted skill documents            │
│  │   ├── docker-ci-python.md                                      │
│  │   ├── jwt-auth-debug.md                                        │
│  │   └── polars-pipeline.md                                       │
│  └── state.json             # Learn state (cursor, counts)        │
└───────────────────────────────────────────────────────────────────┘
```

### 20.4 Data Models

#### LearnState -- Tracks incremental learning progress

```python
class LearnState(BaseModel):
    """Persistent state for incremental learning."""

    last_learned_at: datetime | None = None      # Timestamp of last learn run
    sessions_processed: int = 0                   # Total sessions ever processed
    sessions_since_last: int = 0                  # Sessions processed in last run
    memory_version: int = 0                       # Bumped on every memory mutation
    skill_count: int = 0                          # Total skills extracted
    project_count: int = 0                        # Total project profiles
```

Stored at `~/.sagg/knowledge/state.json`.

#### MemoryEntry -- A single learned pattern

```python
class MemoryEntry(BaseModel):
    """A single declarative fact in the pattern memory."""

    content: str                                  # The learned pattern text
    category: str                                 # tool_preference | project_convention |
                                                  # workflow_pattern | model_insight |
                                                  # environment_fact
    confidence: float = 0.5                       # 0.0-1.0, increases with evidence
    evidence_count: int = 1                       # Number of sessions supporting this
    source_sessions: list[str] = []               # Session IDs (max 5 stored)
    first_seen: datetime                          # When first extracted
    last_confirmed: datetime                      # Last time evidence was found
    superseded_by: str | None = None              # If replaced by a newer pattern
```

#### SkillDocument -- An extracted procedural skill

```python
class SkillDocument(BaseModel):
    """A procedural skill extracted from successful session workflows."""

    id: str                                       # Slugified name
    name: str                                     # Human-readable title
    description: str                              # 1-2 sentence summary
    category: str                                 # debug | setup | migration | testing |
                                                  # deployment | data_pipeline | refactor
    trigger: str                                  # When to use this skill
    procedure: list[str]                          # Step-by-step instructions
    pitfalls: list[str]                           # Known failure modes
    tools_used: list[str]                         # AI tools that were involved
    best_tool: str | None                         # Recommended tool for this workflow
    source_sessions: list[str]                    # Session IDs this was extracted from
    confidence: float                             # 0.0-1.0 based on evidence
    files_pattern: str | None                     # "python_backend" | "react_frontend" etc.
    primary_language: str | None                  # Dominant language
    created_at: datetime
    updated_at: datetime
    version: int = 1                              # Bumped on each update

    def to_markdown(self) -> str:
        """Render as SKILL.md format (agentskills.io compatible)."""
        ...
```

#### ProjectProfile -- Per-project accumulated knowledge

```python
class ProjectProfile(BaseModel):
    """Accumulated knowledge about a specific project."""

    project_name: str
    project_path: str | None
    languages: list[str]                          # Detected languages, ordered by frequency
    frameworks: list[str]                         # Detected frameworks (pytest, react, etc.)
    conventions: list[str]                        # "uses ruff", "prefers small commits"
    preferred_tools: dict[str, str]               # {"debugging": "claude", "ui": "cursor"}
    session_count: int                            # Total sessions for this project
    last_session_at: datetime
    git_remote: str | None
    created_at: datetime
    updated_at: datetime
```

### 20.5 Pattern Memory (`~/.sagg/knowledge/memory.md`)

Inspired by Hermes Agent's `MEMORY.md` but auto-populated rather than agent-managed.

**Key design differences from Hermes:**

| Aspect | Hermes MEMORY.md | sagg memory.md |
|--------|-----------------|----------------|
| Population | Agent writes manually via tool calls | Auto-extracted from session analysis |
| Scope | Single agent's observations | Cross-tool patterns from all sessions |
| Budget | ~2200 chars (~800 tokens) | ~5000 chars (~1800 tokens) -- more to learn from |
| Update trigger | Mid-session via memory tool | `sagg learn` command (batch) |
| Format | `§`-delimited entries | Categorized markdown sections |

**Memory structure:**

```markdown
# Learned Patterns
<!-- Auto-generated by sagg learn. Last updated: 2026-02-25 -->
<!-- 72% capacity (3,600 / 5,000 chars) | 45 patterns | v12 -->

## Tool Preferences
- Claude is 34% faster for Python debugging (92% success vs 79% OpenCode) [14 sessions]
- Cursor produces shorter sessions for React/UI work (avg 8.7 turns vs 12.3 Claude) [9 sessions]
- OpenCode best for quick file edits (fastest start-to-finish) [22 sessions]

## Project Conventions
- session-aggregator: Python 3.12, ruff linting, pytest, hatchling build [48 sessions]
- frontend-app: React 19, TypeScript, Tailwind v4, Vite [12 sessions]

## Workflow Patterns
- Always run tests after refactoring in session-aggregator [seen 8 times]
- Data pipeline work typically needs polars, not pandas [seen 6 times]
- Auth debugging follows: read logs → check middleware → fix handler → test [seen 4 times]

## Model Insights
- claude-sonnet-4 handles multi-file refactoring well (low friction) [11 sessions]
- gemini-2.5-pro good for exploration/research tasks [7 sessions]

## Environment
- Primary OS: Linux (Ubuntu)
- Python managed via uv
- Git workflow: feature branches, small commits
```

**Bounded memory management:**

When memory exceeds 80% capacity (~4000 chars), the learner consolidates:
1. Merge entries with overlapping content (e.g., two entries about Claude + Python → one)
2. Drop entries with `confidence < 0.3` and `evidence_count == 1`
3. Summarize verbose entries (keep the insight, drop the detail)
4. Prefer entries with higher `evidence_count` and more recent `last_confirmed`

### 20.6 Skill Extraction

Skills are extracted when sessions exhibit successful multi-step problem solving. The extractor looks for:

**Extraction criteria (must meet at least 2):**
- Session has ≥ 5 tool calls (non-trivial workflow)
- Session outcome is `fully_achieved` or `partially_achieved` (from facets)
- Friction score < 0.3 (clean execution, not a struggle)
- Similar pattern appears in ≥ 2 sessions (not a one-off)
- Session involves ≥ 3 files modified (real work, not a quick edit)

**Two extraction backends:**

**Backend A: Heuristic Skill Extractor (zero cost)**

```python
class HeuristicSkillExtractor:
    """Extract skills from sessions using pattern matching."""

    def extract(self, sessions: list[UnifiedSession],
                facets: list[dict]) -> list[SkillDocument]:
        # 1. Group sessions by similar tool sequences
        #    e.g., [Read, Grep, Edit, Bash(pytest)] appears 4 times
        sequences = self._extract_tool_sequences(sessions)

        # 2. Cluster by file pattern + task type from facets
        #    "python_backend + debug" sessions that succeeded
        clusters = self._cluster_by_pattern(sessions, facets)

        # 3. For each cluster with ≥2 sessions:
        #    - Extract common tool sequence as "procedure"
        #    - Extract first user message as "trigger"
        #    - Extract error patterns from failed attempts as "pitfalls"
        #    - Name from goal_categories in facets
        skills = []
        for cluster in clusters:
            if len(cluster) >= 2:
                skill = self._synthesize_skill(cluster)
                skills.append(skill)

        return skills
```

**Backend B: LLM Skill Extractor (higher quality)**

```python
class LLMSkillExtractor:
    """Extract skills using LLM via CLI tools."""

    PROMPT = """Analyze these {count} coding sessions that solved similar problems.
Extract a reusable skill document.

Sessions:
{condensed_sessions}

Generate a skill document with:
- name: short descriptive name (kebab-case)
- description: 1-2 sentence summary
- trigger: when should this skill be used
- procedure: step-by-step instructions (numbered)
- pitfalls: common mistakes or failure modes
- best_tool: which AI tool worked best for this

Respond with JSON matching this schema:
{schema}
"""
```

Uses the same CLI LLM backend as `sagg analyze-sessions` (section 13.7) -- no new dependencies.

**Skill file format (`~/.sagg/knowledge/skills/<name>.md`):**

```markdown
---
name: docker-ci-python
description: Set up Docker-based CI for Python projects with pytest
category: setup
confidence: 0.85
evidence_sessions: 4
best_tool: claude
primary_language: python
created_at: 2026-02-20
updated_at: 2026-02-25
version: 2
---

# Docker CI for Python Projects

## When to Use
Setting up or fixing CI/CD pipelines for Python projects that use Docker,
especially when tests need to run in containers.

## Procedure
1. Check existing Dockerfile and docker-compose.yml
2. Create or update `.github/workflows/ci.yml` with Python matrix
3. Configure pytest to run inside container with proper volume mounts
4. Set up caching for pip/uv dependencies (speeds up CI 3-5x)
5. Add health checks and retry logic for flaky tests
6. Run locally with `act` to verify before pushing

## Pitfalls
- Forgetting to copy `pyproject.toml` before `uv sync` (cache bust)
- Missing `--no-cache-dir` flag causes stale packages in CI
- SQLite tests fail in Docker if `/tmp` isn't writable

## Verification
- CI pipeline passes on all matrix entries
- Cache hit rate > 80% on second run
- Total CI time < 5 minutes for standard test suite
```

### 20.7 Learner Orchestrator

The `Learner` class ties everything together:

```python
class Learner:
    """Orchestrates knowledge extraction from session history.

    Processes new sessions since the last run, extracts patterns
    and skills, and updates the knowledge base incrementally.
    """

    def __init__(self, store: SessionStore, knowledge_dir: Path):
        self.store = store
        self.knowledge_dir = knowledge_dir
        self.memory = PatternMemory(knowledge_dir / "memory.md")
        self.skill_library = SkillLibrary(knowledge_dir / "skills")
        self.project_profiles = ProjectProfiles(knowledge_dir / "projects")
        self.state = LearnState.load(knowledge_dir / "state.json")

    def learn(
        self,
        limit: int = 100,
        refresh: bool = False,
        analyzer: str = "heuristic",  # or "llm"
    ) -> LearnResult:
        """Main learning loop.

        Args:
            limit: Max sessions to process in this run.
            refresh: If True, re-process sessions from the last 7 days
                     even if already processed (updates stale knowledge).
            analyzer: Which backend to use for extraction.

        Returns:
            LearnResult with counts of new/updated patterns, skills, profiles.
        """
        # 1. Get sessions to process
        if refresh:
            since = datetime.now() - timedelta(days=7)
            sessions = self.store.list_sessions(since=since, limit=limit)
        else:
            since = self.state.last_learned_at
            sessions = self.store.list_sessions(since=since, limit=limit)

        if not sessions:
            return LearnResult(sessions_processed=0)

        # 2. Load full content + facets for each session
        enriched = self._enrich_sessions(sessions)

        # 3. Extract and update patterns
        new_patterns = self._extract_patterns(enriched)
        self.memory.merge(new_patterns)

        # 4. Extract and update skills
        new_skills = self._extract_skills(enriched, analyzer)
        self.skill_library.merge(new_skills)

        # 5. Update project profiles
        self._update_project_profiles(enriched)

        # 6. Consolidate memory if over budget
        if self.memory.usage_pct > 0.8:
            self.memory.consolidate()

        # 7. Save state
        self.state.last_learned_at = datetime.now()
        self.state.sessions_processed += len(sessions)
        self.state.sessions_since_last = len(sessions)
        self.state.memory_version += 1
        self.state.skill_count = self.skill_library.count()
        self.state.project_count = self.project_profiles.count()
        self.state.save()

        return LearnResult(
            sessions_processed=len(sessions),
            new_patterns=len(new_patterns),
            updated_patterns=self.memory.updated_count,
            new_skills=len(new_skills),
            updated_skills=self.skill_library.updated_count,
            projects_updated=self.project_profiles.updated_count,
        )
```

### 20.8 Pattern Extraction Logic

Patterns are extracted from session metadata, facets, and cross-session analysis:

```python
def _extract_patterns(self, sessions: list[EnrichedSession]) -> list[MemoryEntry]:
    """Extract declarative patterns from a batch of sessions."""
    patterns = []

    # 1. Tool preference patterns
    #    Compare success rates and friction across tools for similar tasks
    tool_stats = self._aggregate_tool_stats(sessions)
    for task_type, stats in tool_stats.items():
        if len(stats) >= 2:  # Need at least 2 tools to compare
            best = max(stats, key=lambda s: s.success_rate)
            if best.success_rate > 0.7 and best.sample_size >= 3:
                patterns.append(MemoryEntry(
                    content=f"{best.tool} is best for {task_type} "
                            f"({best.success_rate:.0%} success, "
                            f"avg {best.avg_turns:.0f} turns)",
                    category="tool_preference",
                    confidence=min(best.sample_size / 10, 1.0),
                    evidence_count=best.sample_size,
                ))

    # 2. Project convention patterns
    #    Detect languages, frameworks, tools from file patterns and tool calls
    for project, proj_sessions in self._group_by_project(sessions):
        conventions = self._detect_conventions(proj_sessions)
        if conventions:
            patterns.append(MemoryEntry(
                content=f"{project}: {', '.join(conventions)}",
                category="project_convention",
                confidence=0.8,
                evidence_count=len(proj_sessions),
            ))

    # 3. Workflow patterns
    #    Repeated tool sequences across sessions
    sequences = self._find_recurring_sequences(sessions, min_count=3)
    for seq in sequences:
        patterns.append(MemoryEntry(
            content=f"{seq.description} [{seq.tool_chain}]",
            category="workflow_pattern",
            confidence=min(seq.count / 5, 1.0),
            evidence_count=seq.count,
        ))

    # 4. Model insights
    #    From facets: which models have low friction for which task types
    model_perf = self._analyze_model_performance(sessions)
    for insight in model_perf:
        patterns.append(MemoryEntry(
            content=insight.text,
            category="model_insight",
            confidence=insight.confidence,
            evidence_count=insight.sample_size,
        ))

    return patterns
```

### 20.9 Database Schema Changes (Migration v4 → v5)

```sql
-- Learn state tracking
CREATE TABLE IF NOT EXISTS learn_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),       -- Singleton row
    last_learned_at INTEGER,
    sessions_processed INTEGER DEFAULT 0,
    memory_version INTEGER DEFAULT 0,
    skill_count INTEGER DEFAULT 0,
    project_count INTEGER DEFAULT 0,
    updated_at INTEGER NOT NULL
);

-- Learned patterns (indexed for search and dedup)
CREATE TABLE IF NOT EXISTS learned_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    category TEXT NOT NULL,                       -- tool_preference, project_convention, etc.
    confidence REAL DEFAULT 0.5,
    evidence_count INTEGER DEFAULT 1,
    source_sessions_json TEXT,                    -- JSON array of session IDs (max 5)
    first_seen INTEGER NOT NULL,
    last_confirmed INTEGER NOT NULL,
    superseded_by INTEGER REFERENCES learned_patterns(id),
    active BOOLEAN DEFAULT 1                      -- soft delete for superseded patterns
);

-- Extracted skills
CREATE TABLE IF NOT EXISTS learned_skills (
    id TEXT PRIMARY KEY,                          -- slugified name
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    content_md TEXT NOT NULL,                     -- Full SKILL.md content
    confidence REAL DEFAULT 0.5,
    evidence_count INTEGER DEFAULT 1,
    source_sessions_json TEXT,
    best_tool TEXT,
    primary_language TEXT,
    files_pattern TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    version INTEGER DEFAULT 1
);

-- Project profiles
CREATE TABLE IF NOT EXISTS project_profiles (
    project_name TEXT PRIMARY KEY,
    project_path TEXT,
    languages_json TEXT,                          -- JSON array
    frameworks_json TEXT,                         -- JSON array
    conventions_json TEXT,                        -- JSON array
    preferred_tools_json TEXT,                    -- JSON dict
    session_count INTEGER DEFAULT 0,
    last_session_at INTEGER,
    git_remote TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

-- FTS for skills search
CREATE VIRTUAL TABLE IF NOT EXISTS learned_skills_fts USING fts5(
    name,
    description,
    content_md,
    content=learned_skills,
    content_rowid=rowid
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_patterns_category ON learned_patterns(category);
CREATE INDEX IF NOT EXISTS idx_patterns_confidence ON learned_patterns(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_patterns_active ON learned_patterns(active);
CREATE INDEX IF NOT EXISTS idx_skills_category ON learned_skills(category);
CREATE INDEX IF NOT EXISTS idx_skills_language ON learned_skills(primary_language);
CREATE INDEX IF NOT EXISTS idx_profiles_sessions ON project_profiles(session_count DESC);
```

### 20.10 CLI Interface

```bash
# Main learning command
sagg learn [OPTIONS]

Options:
  --refresh                  Re-process last 7 days of sessions (update stale knowledge)
  --since DURATION           Only learn from sessions in this time range (e.g., 30d)
  --limit INTEGER            Max sessions to process per run (default: 100)
  --analyzer [heuristic|llm] Extraction backend (default: heuristic)
  --llm-cli [claude|codex|gemini]  Which CLI tool for LLM extraction
  --dry-run                  Show what would be learned without saving
  -v, --verbose              Show each extracted pattern and skill

# View accumulated knowledge
sagg knowledge [OPTIONS]

Subcommands:
  sagg knowledge show             # Show full knowledge base (memory + skills + profiles)
  sagg knowledge memory           # Show just the pattern memory
  sagg knowledge skills           # List all extracted skills
  sagg knowledge skills <name>    # Show a specific skill in detail
  sagg knowledge projects         # List project profiles
  sagg knowledge search <query>   # Search across all knowledge (FTS)
  sagg knowledge export           # Export knowledge base as JSON
  sagg knowledge reset            # Clear all learned knowledge (with confirmation)

Options:
  --format [rich|json|markdown]   Output format (default: rich)
  --project TEXT                   Filter by project
  --category TEXT                  Filter patterns/skills by category
```

### 20.11 Example Workflows

```bash
# First time: learn from all collected sessions
$ sagg learn --since 90d
Processing 342 sessions...
  Analyzing patterns...     ████████████████████████████████ 342/342
  Extracting skills...      ████████████████████████████████ 12 clusters found

Learn complete:
  Sessions processed: 342
  New patterns:       28
  New skills:         7
  Project profiles:   5

# View what was learned
$ sagg knowledge show

╭─ Learned Patterns (28 entries, 62% capacity) ─────────────────────╮
│                                                                    │
│ Tool Preferences (6)                                               │
│  • Claude 34% faster for Python debugging (92% success) [14 ses]  │
│  • Cursor best for React/UI (8.7 avg turns) [9 ses]               │
│  • OpenCode fastest for quick edits [22 ses]                       │
│                                                                    │
│ Project Conventions (5)                                            │
│  • session-aggregator: Python 3.12, ruff, pytest, hatch [48 ses]  │
│  • frontend-app: React 19, TS, Tailwind v4, Vite [12 ses]        │
│                                                                    │
│ ...                                                                │
╰────────────────────────────────────────────────────────────────────╯

╭─ Skills Library (7 skills) ───────────────────────────────────────╮
│  docker-ci-python      Setup Docker CI for Python     85%  claude │
│  jwt-auth-debug        JWT authentication debugging   78%  claude │
│  polars-pipeline       Data pipeline with polars      72%  any    │
│  react-component-test  Testing React components       68%  cursor │
│  ...                                                               │
╰────────────────────────────────────────────────────────────────────╯

# Refresh after a week of new sessions
$ sagg learn --refresh
Processing 23 new sessions since last run...
  Updated patterns:   4 (2 new, 2 strengthened)
  Updated skills:     1 (jwt-auth-debug v2 → v3)
  Projects updated:   2

# Search knowledge
$ sagg knowledge search "docker"
Skills:
  docker-ci-python (85%) - Set up Docker-based CI for Python projects
Patterns:
  "Docker builds need --no-cache-dir for pip in CI" [4 sessions]

# Show a specific skill
$ sagg knowledge skills docker-ci-python
[renders full SKILL.md content with metadata]

# Use LLM for higher quality extraction
$ sagg learn --analyzer llm --since 7d
Detected: claude -p (Claude Code CLI)
Processing 15 sessions via claude -p...
  Estimated cost: ~$0.18
  New patterns: 5 (higher confidence than heuristic)
  New skills: 2
```

### 20.12 Integration with Existing Analytics

| Existing Module | How `learn` Uses It |
|---|---|
| `analytics/friction.py` | Friction scores determine which sessions are "successful" (low friction = skill candidate) |
| `analytics/similar.py` | TF-IDF similarity clusters sessions for skill extraction (similar sessions → one skill) |
| `analytics/oracle.py` | Knowledge base feeds into oracle search -- "Have I learned about this before?" |
| `analytics/heatmap.py` | Activity data helps weight patterns by recency |
| `storage/store.py` | Session queries, facet reads; new methods for learn state and knowledge CRUD |
| `cli.py` insights | `sagg insights` can reference learned patterns in its suggestions |
| `export/` | `sagg knowledge export` produces JSON or Markdown for sharing |

### 20.13 Integration with AI Tool Configs

The knowledge base can optionally feed back into your AI tools:

```bash
# Generate AGENTS.md additions from learned patterns
$ sagg knowledge suggest-rules
Based on 342 sessions, consider adding to your AGENTS.md:

  ## Python Projects
  - Use polars instead of pandas for data processing
  - Always run `uv run pytest` before committing
  - Prefer ruff over flake8/black

  ## Debugging
  - Check logs first, then middleware, then handlers
  - JWT issues: verify token expiry, not just signature

# Auto-append to AGENTS.md (with confirmation)
$ sagg knowledge suggest-rules --apply
```

This bridges sagg's passive observation role with active developer assistance -- the knowledge base becomes a feedback loop from past sessions into future ones.

### 20.14 File Structure

```
src/sagg/
    knowledge/
        __init__.py
        memory.py            # PatternMemory: bounded pattern store with merge/consolidate
        skills.py            # SkillLibrary: skill extraction, storage, search
        projects.py          # ProjectProfiles: per-project knowledge accumulation
        learner.py           # Learner orchestrator: ties everything together
        extractors.py        # HeuristicExtractor + LLMExtractor backends
    storage/
        db.py                # EXTEND: migration v4 → v5 (learn tables)
        store.py             # EXTEND: learn state, patterns, skills, profiles CRUD
    cli.py                   # EXTEND: sagg learn + sagg knowledge commands
```

### 20.15 Dependencies

```toml
# No new required dependencies.
# Heuristic extractor: uses existing sagg analytics code only.
# LLM extractor: shells out to CLI tools already on user's PATH.
# Pattern memory: plain markdown files, no special libraries.
# Skills: markdown files with YAML frontmatter (parsed with existing pydantic).
```

### 20.16 Success Criteria

| Criteria | Metric |
|---|---|
| Pattern extraction covers all sessions | 100% of processed sessions contribute to at least one pattern |
| Skill extraction finds real workflows | Manual review: ≥ 80% of extracted skills are useful/accurate |
| Memory stays bounded | Never exceeds 5000 char limit, consolidation works automatically |
| Incremental learning is fast | `sagg learn` processes 100 sessions in < 30s (heuristic) |
| Refresh updates stale knowledge | Running `--refresh` after 7 days updates confidence scores |
| Knowledge is searchable | FTS search across patterns + skills returns relevant results |
| No new pip dependencies | Everything uses existing sagg code + optional CLI tools |
| Cross-tool patterns detected | Patterns comparing Claude vs Cursor vs OpenCode appear automatically |
| Skills are agentskills.io compatible | Exported skills parse as valid agentskills.io SKILL.md format |

### 20.17 Relationship to Other Features

- **`sagg insights` (§13.7)**: Insights generates *reports*. Learn generates *persistent knowledge*. Insights is consumed once; learn accumulates over time. They share the same facet data.
- **`sagg analyze-sessions` (§13.7)**: Analyze creates per-session facets. Learn consumes those facets to extract cross-session patterns. Run analyze first, then learn.
- **`sagg skill-suggestions` (§13.3)**: Skill suggestions was a planned feature that Learn now **subsumes**. Learn does the same thing (extract skills from patterns) but also maintains a persistent library and handles incremental updates. §13.3 should be considered deprecated in favor of §20.
- **`sagg oracle` (existing)**: Oracle searches session content. Knowledge search is complementary -- it searches the distilled knowledge rather than raw transcripts. Future: oracle could check knowledge base first before searching raw sessions.
- **`sagg friction-points` (existing)**: Friction analysis identifies problem sessions. Learn uses friction scores to determine which sessions are *good* candidates for skill extraction (low friction = successful workflow).
- **Fine-tuning pipeline (§19)**: The knowledge base could tag which sessions make good training data -- high-confidence skills often come from high-quality sessions.
