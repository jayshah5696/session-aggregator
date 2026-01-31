# Session Aggregator UI Plan v2

## Executive Summary

After comprehensive research into TUI frameworks (Textual, Ratatui, Bubbletea, Ink, OpenTUI) and Web UI options (FastAPI+HTMX, NiceGUI), here's the refined plan.

---

## Framework Comparison Matrix

### TUI Frameworks

| Framework | Language | Stars | Python Native | Widgets | Effort |
|-----------|----------|-------|---------------|---------|--------|
| **Textual** | Python | 33.9k | Yes | Excellent | Low |
| **Ratatui** | Rust | 17.9k | No (FFI) | Good | High |
| **Bubbletea** | Go | 38.9k | No | Great (Bubbles) | High |
| **Ink** | JS/React | 34.4k | No (IPC) | Growing | Medium |
| **OpenTUI** | TS/Bun | 8.1k | No (IPC) | Growing | Medium |

### Web Frameworks

| Framework | Bundle Size | Setup | Best For |
|-----------|-------------|-------|----------|
| **FastAPI + HTMX** | 16KB (htmx) | Low | Maximum control |
| **NiceGUI** | ~5MB | Very Low | Rapid prototyping |
| **Streamlit** | ~50MB | Very Low | Data apps (too heavy) |

---

## Recommended Approach: Hybrid Architecture

Build **both** interfaces sharing the same backend:

```
┌─────────────────────────────────────────────────────────────────┐
│                      SessionStore (SQLite)                       │
│                    (Already implemented)                         │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
  ┌───────────┐        ┌───────────────┐     ┌───────────────┐
  │    CLI    │        │   Web Viewer  │     │      TUI      │
  │  (Click)  │        │ (FastAPI+HTMX)│     │   (Textual)   │
  │  existing │        │   `sagg serve`│     │   `sagg tui`  │
  └───────────┘        └───────────────┘     └───────────────┘
```

### Commands

```bash
sagg serve                # Web UI on http://localhost:8642
sagg serve --port 9000    # Custom port
sagg tui                  # Terminal UI
```

---

## Phase 1: TUI with Textual (Priority)

### Why TUI First?

1. **Fits CLI-first philosophy** - Users already run `sagg` in terminal
2. **No context switch** - Stay in terminal, no browser tab
3. **SSH/remote friendly** - Works over SSH, in tmux/screen
4. **Faster iteration** - Textual hot-reload for development
5. **Web fallback built-in** - `textual-web` can serve TUI in browser

### Design Inspiration

Inspired by **lazygit**, **k9s**, **Posting**, and **Harlequin**:

```
┌────────────────────┬─────────────────────────────────────────────┐
│ Sessions           │ Messages                          Filter: _ │
│ ─────────────────  │ ─────────────────────────────────────────── │
│ 📁 ai_experiments  │ #  Role       Content             Tokens    │
│   ▼ Today          │ ─────────────────────────────────────────── │
│     ▶ abc123 10:23 │ 1  👤 user    What files exist?   125       │
│       claude-opus  │ 2  🤖 asst    I'll check using... 450       │
│       12.5k tokens │ 3  🔧 tool    glob: ["*.py"...]   89        │
│     ▶ def456 14:15 │ 4  🤖 asst    Found 3 files:      234       │
│   ▶ Yesterday      │ ─────────────────────────────────────────── │
│   ▶ This Week      │ Message Detail                              │
│                    │ ─────────────────────────────────────────── │
├────────────────────┤ I'll check the files using the glob tool:   │
│ Stats              │                                             │
│ ──────────────────▶│ ```python                                   │
│ Total: 7.5M tokens │ files = glob("*.py")                        │
│ Sessions: 187      │ ```                                         │
│ Sources: 4         │                                             │
│                    │ ┌─ Tool: glob ─────────────────────────────┐│
│ Models:            │ │ pattern: "*.py"                          ││
│ ▓▓▓▓▓▓░░ opus 65%  │ │ result: ["main.py", "utils.py"]         ││
│ ▓▓░░░░░░ sonnet 25%│ └──────────────────────────────────────────┘│
└────────────────────┴─────────────────────────────────────────────┘
│ j/k navigate  / filter  Enter expand  e export  ? help  q quit  │
```

### Aesthetic Direction

Following the **frontend-design skill** principles:

**Tone**: Industrial/Utilitarian meets Editorial
- Clean, dense information display
- Monospace typography (terminal-native)
- Muted color palette with semantic highlights
- Minimal chrome, maximum content

**Color Scheme** (Dark theme):
```css
/* CSS-like Textual styling */
$background: #0d1117;      /* GitHub dark */
$surface: #161b22;
$border: #30363d;
$text: #c9d1d9;
$text-muted: #8b949e;

/* Semantic colors */
$user: #58a6ff;            /* Blue - human */
$assistant: #7ee787;       /* Green - AI */
$tool: #d29922;            /* Amber - tools */
$error: #f85149;           /* Red - errors */

/* Source badges */
$opencode: #58a6ff;
$claude: #a855f7;
$codex: #22c55e;
$cursor: #f97316;
```

### Key UX Patterns (from research)

| Pattern | Source | Implementation |
|---------|--------|----------------|
| Vim navigation | lazygit, k9s | `j/k`, `g/G`, `Ctrl+d/u` |
| Filter with `/` | lazygit | Inline search in current panel |
| Command palette | Posting | `Ctrl+P` for fuzzy actions |
| Panel switching | lazygit | `Tab` or `1/2/3` keys |
| Context help | All | `?` shows relevant keybindings |
| Breadcrumb nav | k9s | Show: Project > Session > Message |

### File Structure

```
src/sagg/tui/
├── __init__.py
├── app.py                 # Main Textual App
├── styles.tcss            # Textual CSS
├── screens/
│   ├── __init__.py
│   ├── main.py            # Main three-panel screen
│   └── help.py            # Help overlay
├── widgets/
│   ├── __init__.py
│   ├── session_tree.py    # Left panel - session hierarchy
│   ├── message_table.py   # Top-right - message list
│   ├── detail_view.py     # Bottom-right - message detail
│   ├── stats_panel.py     # Stats sidebar
│   └── search_bar.py      # Search input
└── components/
    ├── __init__.py
    ├── tool_call.py       # Tool call display
    └── code_block.py      # Syntax-highlighted code
```

### Implementation Priorities

| Priority | Feature | Description |
|----------|---------|-------------|
| P0 | Session tree | Hierarchical view by project/date |
| P0 | Message list | Table with role, preview, tokens |
| P0 | Message detail | Full content with tool calls |
| P0 | Navigation | vim keys, panel switching |
| P1 | Search/filter | `/` to filter, `Ctrl+P` palette |
| P1 | Stats panel | Token usage, model distribution |
| P1 | Syntax highlighting | Code blocks in messages |
| P2 | Export | `e` to export current session |
| P2 | Copy | `y` to copy content |
| P2 | Theme toggle | Light/dark mode |

### Effort: 3-4 days

---

## Phase 2: Web UI with FastAPI + HTMX

### Why Web Second?

1. **Richer display** - Proper markdown, images, complex layouts
2. **Sharing** - Copy URL to share specific session
3. **No terminal required** - Works for non-CLI users
4. **Future-proof** - Could deploy as hosted service

### Design Direction

**Tone**: Editorial/Magazine meets Data Dashboard

**NOT generic AI aesthetics** - avoid:
- Purple gradients on white
- Inter/Roboto fonts
- Cookie-cutter card layouts

**Instead**:
- **Typography**: IBM Plex Mono for code, Source Serif for prose
- **Color**: Dark theme with amber accents (like terminal)
- **Layout**: Dense data tables with generous whitespace in details
- **Motion**: Subtle HTMX transitions, no flashy animations

### Mockup - Session List

```html
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│   S A G G                                    [Search sessions...]   │
│   Session Aggregator                                                │
│                                                                     │
│   ┌─────────┬─────────┬─────────┬─────────┐                        │
│   │ All     │ OpenCode│ Claude  │ Cursor  │  187 sessions          │
│   │ (187)   │ (172)   │ (3)     │ (8)     │  7.5M tokens           │
│   └─────────┴─────────┴─────────┴─────────┘                        │
│                                                                     │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │ ● abc123  Implement authentication      ai_experiments      │  │
│   │   claude-opus-4 · 45.2k tokens · 2 hours ago                │  │
│   ├─────────────────────────────────────────────────────────────┤  │
│   │ ● def456  Fix database connection       backend-api         │  │
│   │   claude-sonnet-4 · 12.8k tokens · 5 hours ago              │  │
│   ├─────────────────────────────────────────────────────────────┤  │
│   │ ● ghi789  Add API endpoint              service             │  │
│   │   gpt-4o · 8.3k tokens · 1 day ago                          │  │
│   └─────────────────────────────────────────────────────────────┘  │
│                                                                     │
│   ─────────────────────────────────────────────────────────────    │
│   1 of 12                                            ← Previous    │
│                                                         Next →     │
└─────────────────────────────────────────────────────────────────────┘
```

### File Structure

```
src/sagg/viewer/
├── __init__.py
├── server.py              # FastAPI app
├── routes/
│   ├── __init__.py
│   ├── sessions.py        # Session CRUD
│   ├── search.py          # Search endpoint
│   └── stats.py           # Analytics
├── templates/
│   ├── base.html          # Layout with nav
│   ├── index.html         # Dashboard
│   ├── sessions/
│   │   ├── list.html
│   │   └── detail.html
│   ├── stats.html
│   └── partials/
│       ├── session_card.html
│       ├── message.html
│       └── tool_call.html
└── static/
    ├── htmx.min.js        # 16KB
    ├── styles.css         # Custom (no framework)
    └── app.js             # Minimal JS helpers
```

### Effort: 3-4 days

---

## Technology Decisions

### TUI Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Framework | **Textual** | Python-native, Rich-compatible, 33.9k stars |
| Styling | TCSS | CSS-like, themeable |
| Widgets | Built-in | Tree, DataTable, TextArea |
| Navigation | Custom | Vim-style keybindings |

**Why not Ratatui/Bubbletea/Ink?**
- All require language switch or complex IPC
- No Python bindings exist
- Textual is excellent and Python-native

### Web Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Framework | **FastAPI** | Async, OpenAPI, popular |
| Server | uvicorn | Standard ASGI |
| Templates | Jinja2 | Built-in |
| Interactivity | **HTMX** | 16KB, no build step |
| CSS | **Custom** | Avoid generic frameworks |
| Syntax | Pygments | Already in stack via Rich |

**Why not NiceGUI/Streamlit?**
- Too heavy for a CLI tool
- Less control over styling
- HTMX is simpler and smaller

---

## Dependencies to Add

```toml
# pyproject.toml
dependencies = [
    # ... existing ...
    # TUI
    "textual>=0.89.0",
    # Web
    "fastapi>=0.115.0",
    "uvicorn>=0.32.0",
    "jinja2>=3.1.0",
]
```

---

## Implementation Status

### Phase 1: TUI with Textual - COMPLETED (v1.1)

**Files Created:**
```
src/sagg/tui/
├── __init__.py                 # Module exports SaggApp
├── app.py                      # Main Textual App with three-panel layout
├── styles.tcss                 # Dark industrial theme CSS
└── widgets/
    ├── __init__.py             # Widget exports
    ├── session_tree.py         # Left panel - session hierarchy
    ├── message_table.py        # Top-right - message list with virtual scrolling
    └── detail_view.py          # Bottom-right - syntax-highlighted detail view
```

**Features Implemented:**
- Three-panel layout (sessions tree, message table, detail view)
- **Always-visible search bar** at top (live filtering as you type)
- Virtual scrolling for large session/message lists
- **Auto-expand** first 3 projects on load with first session selected
- **Wider sidebar** (35% width) to show full session titles
- Vim-style keybindings (j/k, g/G, Enter, Tab, /, e, ?, q)
- Session grouping by project and date
- Syntax highlighting for code blocks
- Tool call visualization with input/output
- Dark industrial theme
- Lazy loading of session content
- Auto-preview messages on navigation

**Layout (v1.2 - Scrollable Chat):**
```
┌───────────────────────────┬─────────────────────────────────────────┐
│ [Search...              ] │ Conversation (18 messages)              │
├───────────────────────────┤─────────────────────────────────────────│
│ ▼ ai_experiments 2.6M     │ Fix authentication bug                  │
│   ▼ This Week (18)        │ opencode · ai_experiments · 2026-01-29  │
│     ▶ Fix auth bug...     │ 18 messages · 45.2k tokens              │
│     ▶ Add API endpt...    │                                         │
│   ▶ This Month (5)        │ ┃ USER  14:30:22                        │
│ ▼ backend-api 1.3M        │ ┃ The auth is failing with JWT error    │
│   ▼ Today (2)             │                                         │
│     ▶ Quick fix...        │ ┃ ASSISTANT  14:30:25  2.5k             │
│ ▶ frontend 800k           │ ┃ I'll investigate the JWT validation.  │
│                           │ ┃ Let me check the auth handler...      │
│                           │                                         │
│                           │ ┌─ → read ──────────────────────────────┐
│                           │ │ {"path": "src/auth/handler.ts"}       │
│                           │ └───────────────────────────────────────┘
│                           │                                         │
│                           │ ┌─ ← result ────────────────────────────┐
│                           │ │ export function validateJWT(...) {    │
│                           │ │   // Token validation logic           │
├───────────────────────────┤ │ }                                     │
│ Total: 187 · 7.5M tokens  │ └───────────────────────────────────────┘
└───────────────────────────┴─────────────────────────────────────────┘
│ / search  Tab switch  j/k scroll  e export  ? help  q quit         │
```

**Key Design Changes (v1.2):**
- **Scrollable chat view** - All messages visible, scroll to browse
- **Two-panel layout** - Simpler: sessions left, conversation right
- **Message bubbles** - Color-coded left border (blue=user, green=assistant, amber=tool)
- **Inline tool calls** - Tool inputs/outputs shown inline with collapsible panels
- **Session header** - Shows title, metadata, and stats at top of conversation
- **Live preview** - Conversation loads on hover (no click required)

**Launch:** `sagg tui`

---

### Phase 2: Web UI with FastAPI + HTMX - FUTURE WORK

**Priority:** Medium (TUI covers primary use case)

**Rationale for deferring:**
- TUI satisfies CLI-first workflow
- Web UI adds complexity (server, templates, static files)
- Can use `textual-web` to serve TUI in browser as interim solution

**When to implement:**
- When sharing sessions with non-terminal users
- When building a hosted/team version
- When rich visualization is needed (graphs, timelines)

**Implementation Plan:**

| Task | Effort | Description |
|------|--------|-------------|
| FastAPI routes | 1 day | Session CRUD, search, stats endpoints |
| Jinja2 templates | 1 day | Base layout, session list, detail pages |
| HTMX integration | 1 day | Partial updates, infinite scroll, live search |
| CSS styling | 1 day | Dark theme matching TUI, responsive design |

**File Structure (when implemented):**
```
src/sagg/viewer/
├── __init__.py
├── server.py              # FastAPI app
├── routes/
│   ├── sessions.py        # Session CRUD
│   ├── search.py          # Search endpoint
│   └── stats.py           # Analytics
├── templates/
│   ├── base.html          # Layout with nav
│   ├── index.html         # Dashboard
│   ├── sessions/
│   │   ├── list.html
│   │   └── detail.html
│   └── partials/
│       ├── session_card.html
│       ├── message.html
│       └── tool_call.html
└── static/
    ├── htmx.min.js        # 16KB
    ├── styles.css         # Custom (no framework)
    └── app.js             # Minimal JS helpers
```

**Dependencies to add:**
```toml
# When implementing Phase 2
"fastapi>=0.115.0",
"uvicorn>=0.32.0",
"jinja2>=3.1.0",
```

**Performance considerations (from research):**
- Use cursor-based pagination (not offset) for message lists
- Enable Jinja2 bytecode caching in production
- Use `hx-trigger="input changed delay:500ms"` for search debouncing
- Implement infinite scroll with `hx-trigger="revealed"`
- SQLite FTS5 already in place for fast full-text search

---

## Keybindings Reference (TUI)

| Key | Action |
|-----|--------|
| `j` / `↓` | Move down |
| `k` / `↑` | Move up |
| `g` | Go to top |
| `G` | Go to bottom |
| `Enter` | Expand / select |
| `Esc` | Back / close |
| `Tab` / `Shift+Tab` | Switch panel |
| `1` / `2` / `3` | Jump to panel |
| `/` | Filter current view |
| `e` | Export session |
| `r` | Refresh sessions |
| `?` | Show help |
| `q` | Quit |

---

## Success Criteria

### TUI - COMPLETED
- [x] Can browse all sessions with virtual scrolling
- [x] Can view message details with tool calls
- [x] Filter works with `/`
- [x] Vim navigation implemented
- [x] Dark industrial theme
- [ ] Startup time <500ms (to verify)

### Web - FUTURE
- [ ] Session list with cursor-based pagination
- [ ] Session detail with message thread
- [ ] Search with live results (debounced)
- [ ] Responsive on mobile
- [ ] Loads in <1s

---

## References

- [Textual Documentation](https://textual.textualize.io/)
- [HTMX Documentation](https://htmx.org/)
- [lazygit](https://github.com/jesseduffield/lazygit) - UX inspiration
- [Posting](https://github.com/darrenburns/posting) - Textual example
- [Harlequin](https://github.com/tconbeer/harlequin) - Textual example
