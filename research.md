# AI Coding Session Aggregator - Research Report

**Date**: January 29, 2026  
**Status**: Research Complete

---

## 1. Executive Summary

This research investigates building a unified tool to aggregate AI coding sessions from multiple tools (OpenCode, Claude Code, Codex, Antigravity, Cursor), convert them to the AgentTrace standard format, and provide a searchable viewer with metadata tracking.

**Key Findings**:
- Each tool uses different storage formats (JSON, JSONL, SQLite)
- No existing open-source solution aggregates sessions across all these tools
- AgentTrace (v0.1.0) is the emerging standard for AI code attribution
- OpenTelemetry is the backbone for LLM observability in most tools
- Agent Prism provides reusable React components for trace visualization

---

## 2. Session Storage Formats by Tool

### 2.1 OpenCode

| Attribute | Details |
|-----------|---------|
| **Location** | `~/.local/share/opencode/storage/` |
| **Format** | Individual JSON files |
| **Structure** | Hierarchical: `session/` → `message/` → `part/` |

**Directory Layout**:
```
~/.local/share/opencode/storage/
├── project/<hash>.json
├── session/<project-hash>/<session-id>.json
├── message/<session-id>/<message-id>.json
├── part/<message-id>/<part-id>.json
├── session_diff/<session-id>.json
└── todo/<session-id>.json
```

**Session Schema**:
```json
{
  "id": "ses_3f3bd5e02ffeJrWG6asitc1GIB",
  "projectID": "<sha1-hash>",
  "directory": "/path/to/project",
  "title": "Session title",
  "version": "1.1.42",
  "time": { "created": 1769732219389, "updated": 1769732277426 },
  "summary": { "additions": 0, "deletions": 0, "files": 0 }
}
```

**Message Part Types**: `text`, `tool`, `step-start`

---

### 2.2 Claude Code

| Attribute | Details |
|-----------|---------|
| **Location** | `~/.claude/projects/<encoded-path>/` |
| **Format** | JSONL (one JSON object per line) |
| **File Pattern** | `<session-uuid>.jsonl`, `agent-<id>.jsonl` |

**Path Encoding**:
- `/Users/foo/code/myapp` → `-Users-foo-code-myapp`
- Hidden dirs get double dash: `.config` → `-config`

**Entry Schema**:
```json
{
  "sessionId": "abc123-def456",
  "type": "user|assistant|tool_result|summary|system",
  "uuid": "...",
  "parentUuid": "...",
  "timestamp": "2026-01-26T21:50:11.105Z",
  "cwd": "/path/to/project",
  "version": "2.1.14",
  "gitBranch": "main",
  "message": {
    "role": "user|assistant",
    "content": [...],
    "usage": { "input_tokens": 12345, "output_tokens": 678 }
  }
}
```

**Entry Types**: `user`, `assistant`, `tool_result`, `summary`, `file-history-snapshot`, `system`

---

### 2.3 OpenAI Codex CLI

| Attribute | Details |
|-----------|---------|
| **Location** | `~/.codex/sessions/` |
| **Format** | JSONL |
| **Config** | `~/.codex/config.toml` |

**Event Types**:
```json
{"type": "thread.started", "thread_id": "0199a213-81c0-7800-..."}
{"type": "turn.started"}
{"type": "item.started", "item": {"id": "item_1", "type": "command_execution", "command": "bash -lc ls"}}
{"type": "item.completed", "item": {"id": "item_3", "type": "agent_message", "text": "..."}}
{"type": "turn.completed", "usage": {"input_tokens": 24763, "output_tokens": 122}}
```

**Item Types**: `agent_message`, `command_execution`, `reasoning`, `file_changes`, `mcp_tool_calls`, `web_search`, `plan_updates`

---

### 2.4 Cursor

| Attribute | Details |
|-----------|---------|
| **Location** | `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` (macOS) |
| **Format** | SQLite database |
| **Tables** | `ItemTable`, `cursorDiskKV` |

**Platform Paths**:
- **Windows**: `%APPDATA%\Cursor\User\globalStorage\state.vscdb`
- **Linux**: `~/.config/Cursor/User/globalStorage/state.vscdb`

**Key Patterns in `cursorDiskKV`**:
| Key Pattern | Description |
|-------------|-------------|
| `composerData:<id>` | Full conversation data |
| `bubbleId:<composer>:<bubble>` | Individual messages |
| `messageRequestContext:<id>` | Project/file context |

**Data Structure**:
```typescript
interface ComposerChat {
  composerId: string;
  conversation?: ComposerMessage[];
  name: string;
  createdAt: number;
  lastUpdatedAt: number;
  status: string;
  context: ComposerContext;
}
```

---

### 2.5 Google Antigravity

| Attribute | Details |
|-----------|---------|
| **Location** | `~/.gemini/antigravity/` |
| **Format** | JSON, Markdown |
| **Workspace** | `<workspace>/.agent/` |

**Directory Structure**:
```
~/.gemini/
├── GEMINI.md                    # Global rules
└── antigravity/
    ├── settings.json            # Main settings
    ├── global_workflows/
    ├── skills/
    └── browserAllowlist.txt
```

**Note**: Session log format not publicly documented. Conversations stored in "Inbox" feature within the tool.

---

## 3. AgentTrace Specification Analysis

**Version**: 0.1.0 (RFC)  
**Repository**: https://github.com/cursor/agent-trace  
**Website**: https://agent-trace.dev

### 3.1 Purpose

AgentTrace is an open specification for tracking AI-generated code. It provides vendor-neutral attribution for:
- Which code came from AI vs humans
- Which models were used
- Links to source conversations

### 3.2 Core Schema

```json
{
  "version": "0.1.0",
  "id": "uuid",
  "timestamp": "RFC 3339",
  "vcs": { "type": "git|jj|hg|svn", "revision": "commit-sha" },
  "tool": { "name": "cursor", "version": "2.4.0" },
  "files": [{
    "path": "src/file.ts",
    "conversations": [{
      "url": "https://api.example.com/conversations/123",
      "contributor": { "type": "ai", "model_id": "anthropic/claude-opus-4-5" },
      "ranges": [{ "start_line": 10, "end_line": 25 }]
    }]
  }]
}
```

### 3.3 Key Concepts

| Concept | Description |
|---------|-------------|
| **Contributor Types** | `human`, `ai`, `mixed`, `unknown` |
| **Model IDs** | Follow models.dev convention: `provider/model-name` |
| **Content Hashes** | MurmurHash3 for position-independent tracking |
| **Line Tracking** | 1-indexed, tied to specific VCS revision |

### 3.4 Partners

Amp, Cloudflare, Cognition, git-ai, Jules (Google), OpenCode, Vercel

---

## 4. Existing Open-Source Solutions

### 4.1 Session Viewers

| Project | Stars | Scope | Tech |
|---------|-------|-------|------|
| [esc5221/claude-code-viewer](https://github.com/esc5221/claude-code-viewer) | 28 | Claude Code only | Electron, React |
| [tad-hq/universal-session-viewer](https://github.com/tad-hq/universal-session-viewer) | 8 | Claude Code only | TypeScript |
| [paulgb/claude-viewer](https://github.com/paulgb/claude-viewer) | 12 | Claude Code only | Rust CLI |
| [thomas-pedersen/cursor-chat-browser](https://github.com/thomas-pedersen/cursor-chat-browser) | 489 | Cursor only | Next.js |

### 4.2 LLM Observability Platforms

| Project | Stars | Description |
|---------|-------|-------------|
| [langfuse/langfuse](https://github.com/langfuse/langfuse) | 21.3k | Full observability platform, evals, prompts |
| [Arize-ai/phoenix](https://github.com/Arize-ai/phoenix) | 8.4k | OpenTelemetry-based AI observability |
| [openlit/openlit](https://github.com/openlit/openlit) | 2.2k | OpenTelemetry-native, GPU monitoring |

### 4.3 OpenTelemetry for LLM

| Project | Stars | Description |
|---------|-------|-------------|
| [traceloop/openllmetry](https://github.com/traceloop/openllmetry) | 6.8k | OpenTelemetry instrumentation for LLMs |
| [evilmartians/agent-prism](https://github.com/evilmartians/agent-prism) | 285 | React components for trace visualization |

### 4.4 Gap Analysis

| Capability | Existing Solution? |
|------------|-------------------|
| View Claude Code sessions | Yes (multiple) |
| View Cursor sessions | Yes (cursor-chat-browser) |
| View Codex sessions | No |
| View Antigravity sessions | No |
| Aggregate multiple tools | **No** |
| Convert to AgentTrace | **No** |
| Unified search across tools | **No** |

---

## 5. Technical Considerations

### 5.1 Format Conversion Complexity

| Source | Difficulty | Notes |
|--------|------------|-------|
| OpenCode → AgentTrace | Medium | Good structure, needs file diff extraction |
| Claude Code → AgentTrace | Medium | JSONL parsing, tool results contain file info |
| Codex → AgentTrace | Medium | Similar JSONL structure |
| Cursor → AgentTrace | Hard | SQLite, complex nested JSON, binary blobs |
| Antigravity → AgentTrace | Unknown | Format not publicly documented |

### 5.2 Metadata to Track

| Metadata | Source |
|----------|--------|
| Project path | All tools |
| Git branch/commit | All tools (if available) |
| Model used | All tools |
| Token usage | OpenCode, Claude Code, Codex |
| Tool calls | All tools |
| Duration | Timestamps |
| Files modified | Diff analysis |

### 5.3 Storage Options for Unified Data

| Option | Pros | Cons |
|--------|------|------|
| SQLite | Fast queries, single file | Schema migrations |
| JSONL | Simple, append-only | Slow full-text search |
| PostgreSQL | Full-text search, JSONB | Setup overhead |
| DuckDB | Analytics-optimized | Newer, less tooling |

---

## 6. Recommended Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Session Aggregator                       │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                     Collector Layer                          ││
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        ││
│  │  │ OpenCode │ │  Claude  │ │  Codex   │ │  Cursor  │        ││
│  │  │ Adapter  │ │  Adapter │ │  Adapter │ │  Adapter │        ││
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘        ││
│  └───────┼────────────┼────────────┼────────────┼──────────────┘│
│          │            │            │            │                │
│          └────────────┴─────┬──────┴────────────┘                │
│                             ▼                                    │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                  Unified Session Store                       ││
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          ││
│  │  │  Sessions   │  │   Messages  │  │  Metadata   │          ││
│  │  │  (SQLite)   │  │   (JSONL)   │  │   (JSON)    │          ││
│  │  └─────────────┘  └─────────────┘  └─────────────┘          ││
│  └─────────────────────────────────────────────────────────────┘│
│                             │                                    │
│                             ▼                                    │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                   AgentTrace Exporter                        ││
│  │         Converts unified format → AgentTrace JSON            ││
│  └─────────────────────────────────────────────────────────────┘│
│                             │                                    │
│                             ▼                                    │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                     Viewer Layer                             ││
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          ││
│  │  │ Session     │  │   Search    │  │  Analytics  │          ││
│  │  │ Browser     │  │   Index     │  │  Dashboard  │          ││
│  │  └─────────────┘  └─────────────┘  └─────────────┘          ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. Prior Art & Inspiration

### 7.1 cursor-chat-browser
- Best-in-class Cursor viewer
- Web-based, exports to Markdown
- Good reference for SQLite parsing

### 7.2 claude-code-viewer
- Electron app with timeline minimap
- Real-time updates via file watching
- Good UX reference

### 7.3 Agent Prism
- Reusable React components
- OpenTelemetry and Langfuse adapters
- Could be extended for our unified format

### 7.4 Langfuse
- Best open-source observability platform
- Good data model reference
- REST API for querying

---

## 8. Conclusions

1. **No existing unified solution** - This tool would fill a real gap
2. **AgentTrace is the right standard** - Backed by major players (Cursor, OpenCode, Google)
3. **Start with the big three** - OpenCode, Claude Code, Cursor cover most users
4. **Use existing components** - Agent Prism for visualization, SQLite for storage
5. **CLI-first** - Start with CLI tools for collection, add viewer later

---

## 9. References

- [AgentTrace Specification](https://agent-trace.dev)
- [AgentTrace GitHub](https://github.com/cursor/agent-trace)
- [Agent Prism](https://github.com/evilmartians/agent-prism)
- [Langfuse](https://github.com/langfuse/langfuse)
- [OpenLLMetry](https://github.com/traceloop/openllmetry)
- [cursor-chat-browser](https://github.com/thomas-pedersen/cursor-chat-browser)
- [claude-code-viewer](https://github.com/esc5221/claude-code-viewer)
