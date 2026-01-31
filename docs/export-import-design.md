# Export/Import Design for sagg

**Version**: 0.1.0  
**Date**: January 30, 2026  
**Status**: Design Document

---

## Table of Contents

1. [Overview](#1-overview)
2. [Export Format Design](#2-export-format-design)
3. [CLI Interface Design](#3-cli-interface-design)
4. [Merge Strategy](#4-merge-strategy)
5. [Example Workflows](#5-example-workflows)
6. [Future Considerations](#6-future-considerations)

---

## 1. Overview

### 1.1 Problem Statement

Users need to:
1. Export sessions from their work machine
2. Import them on their personal machine (or vice versa)
3. Merge session histories from multiple machines
4. Share specific sessions with teammates

### 1.2 Design Principles

1. **Self-contained archives**: Export files should be portable and verifiable
2. **Incremental by default**: Support exporting only new sessions since last export
3. **Conflict-safe**: Never lose data during merges
4. **Human-readable**: Format should be inspectable with standard tools
5. **Cross-platform**: Handle path differences between machines

### 1.3 Non-Goals

- Real-time sync (use git or Syncthing for that)
- Cloud storage integration
- MCP servers
- Encryption (users can pipe through gpg if needed)

---

## 2. Export Format Design

### 2.1 Format Choice: JSONL Archive (`.sagg`)

After evaluating options, the recommended format is a **gzip-compressed JSONL file** with a header:

| Format | Pros | Cons | Verdict |
|--------|------|------|---------|
| **JSON** | Human readable, universal | Large files, no streaming | Poor for 1000+ sessions |
| **JSONL** | Streaming, appendable | No schema in file | Good, needs header |
| **SQLite** | Query-able, self-contained | Binary, version issues | Overkill for export |
| **tar.gz** | Standard, preserves structure | Complex to parse | Too heavy |
| **JSONL.gz** | Compact, streamable, standard | Needs gunzip to read | **Best balance** |

**Why JSONL.gz?**
- Streaming read/write for large archives
- Each line is independent (parallel processing possible)
- gzip is universal and well-supported
- 5-10x compression ratio on session data
- Can use `zcat file.sagg | head` to peek

### 2.2 Archive Schema

```
<archive>.sagg (gzip-compressed JSONL)
├── Line 1: Header (metadata about the export)
├── Line 2-N: Session records
└── Line N+1: Footer (optional, checksums)
```

#### 2.2.1 Header Record

```json
{
  "type": "header",
  "version": "1.0.0",
  "created_at": "2026-01-30T14:30:00Z",
  "source_machine": "work-macbook",
  "source_machine_id": "a1b2c3d4-...",
  "sagg_version": "0.2.0",
  "session_count": 150,
  "filters": {
    "since": "2026-01-01T00:00:00Z",
    "until": null,
    "sources": ["opencode", "claude"],
    "projects": ["myapp", "backend-api"]
  },
  "checksum_algorithm": "sha256"
}
```

Fields:
- `version`: Archive format version (semver)
- `source_machine`: Human-readable hostname
- `source_machine_id`: UUID for collision detection (generated once per machine, stored in `~/.sagg/machine_id`)
- `filters`: What was included in this export (for documentation)
- `checksum_algorithm`: Algorithm used for integrity verification

#### 2.2.2 Session Record

```json
{
  "type": "session",
  "id": "0195abc...",
  "source_machine_id": "a1b2c3d4-...",
  "source": "opencode",
  "source_id": "ses_abc123",
  "source_path": "/Users/jshah/.local/share/opencode/...",
  "title": "Fix authentication bug",
  "project_path": "/Users/jshah/projects/myapp",
  "project_name": "myapp",
  "git": {"branch": "main", "commit": "abc123"},
  "created_at": "2026-01-30T10:00:00Z",
  "updated_at": "2026-01-30T10:45:00Z",
  "duration_ms": 2700000,
  "stats": {...},
  "models": [...],
  "turns": [...]
}
```

**Key additions for export:**
- `source_machine_id`: Tracks origin machine for deduplication
- Full `turns` array included (unlike DB queries that exclude content by default)

#### 2.2.3 Footer Record (Optional)

```json
{
  "type": "footer",
  "session_count": 150,
  "checksum": "sha256:abc123...",
  "total_bytes_uncompressed": 15728640
}
```

### 2.3 File Naming Convention

```
sagg-export-{date}-{machine}-{filter}.sagg

Examples:
sagg-export-2026-01-30-work-macbook.sagg
sagg-export-2026-01-30-work-macbook-myapp.sagg
sagg-export-2026-01-30-work-macbook-since-7d.sagg
```

Default: `sagg-export-{YYYY-MM-DD}-{hostname}.sagg`

### 2.4 Path Normalization

Absolute paths are stored but normalized during import:

**Export (source machine):**
```json
{
  "project_path": "/Users/jshah/projects/myapp",
  "source_path": "/Users/jshah/.local/share/opencode/..."
}
```

**Import behavior:**
- `project_path`: Stored as-is (informational only, not used for file operations)
- `project_name`: Extracted and used for grouping
- `source_path`: Stored as-is (original location, may not exist on target)

**No path rewriting**: The import machine doesn't need these paths to exist. They're metadata about where the session originated.

### 2.5 Timestamp Handling

All timestamps are stored in **ISO 8601 with timezone** (RFC 3339):

```json
"created_at": "2026-01-30T10:00:00-08:00"
```

On import:
- Timestamps are parsed and stored as UTC epoch in SQLite
- Display uses local timezone
- No conversion issues across machines

### 2.6 Size Estimation

For 1000 sessions with average 20 turns each:
- Uncompressed JSONL: ~50-100 MB
- Compressed (.sagg): ~5-15 MB

Well within reasonable transfer sizes.

---

## 3. CLI Interface Design

### 3.1 Export Command

```bash
sagg export [OPTIONS] [OUTPUT]

Arguments:
  OUTPUT               Output file path (default: sagg-export-{date}-{hostname}.sagg)

Options:
  # Filtering
  -s, --source TEXT    Export only from specific source (opencode, claude, etc.)
  -p, --project TEXT   Export only sessions matching project name
  --since DURATION     Export sessions from last N (e.g., 7d, 2w, 30d)
  --until DATE         Export sessions until date (YYYY-MM-DD)
  --id TEXT            Export specific session ID(s), comma-separated
  
  # Output control
  -f, --format FORMAT  Output format: sagg (default), json, jsonl
  --no-content         Export metadata only, exclude conversation turns
  --pretty             Pretty-print JSON (only for json format)
  
  # Behavior
  --dry-run            Show what would be exported without creating file
  --force              Overwrite output file if it exists
  --quiet              Suppress progress output
  
Examples:
  sagg export                                    # Export all sessions
  sagg export -o backup.sagg                     # Export to specific file
  sagg export --since 7d                         # Last 7 days
  sagg export --project myapp --since 30d       # Filter by project and time
  sagg export --source opencode --source claude  # Multiple sources
  sagg export --dry-run                          # Preview what would be exported
```

### 3.2 Import Command

```bash
sagg import [OPTIONS] FILE

Arguments:
  FILE                 Import file (.sagg, .json, or .jsonl)

Options:
  # Filtering
  -s, --source TEXT    Import only from specific source
  -p, --project TEXT   Import only sessions matching project name
  --since DURATION     Import only sessions from last N
  --id TEXT            Import specific session ID(s)
  
  # Conflict handling
  --strategy STRATEGY  Merge strategy: skip (default), replace, rename
  --dry-run            Show what would be imported without making changes
  
  # Behavior
  --quiet              Suppress progress output
  --verify             Verify checksums before importing
  
Strategies:
  skip     Skip sessions that already exist (by source+source_id)
  replace  Replace existing sessions with imported versions
  rename   Import with new ID if collision detected
  
Examples:
  sagg import backup.sagg                        # Import with default (skip conflicts)
  sagg import backup.sagg --strategy replace     # Overwrite existing
  sagg import backup.sagg --dry-run              # Preview changes
  sagg import backup.sagg --project myapp        # Import only myapp sessions
```

### 3.3 Verify Command

```bash
sagg verify FILE

Arguments:
  FILE                 Archive file to verify

Options:
  --verbose            Show detailed information about each session
  
Output:
  Archive: backup.sagg
  Format version: 1.0.0
  Created: 2026-01-30 14:30:00
  Source machine: work-macbook
  Sessions: 150
  Sources: opencode (80), claude (50), cursor (20)
  Date range: 2026-01-01 to 2026-01-30
  Checksum: VALID
```

### 3.4 Progress Indication

For large exports/imports, show progress:

```
Exporting sessions...
[========================================] 100% (150/150 sessions)
Compressing archive...
[========================================] 100%

Exported 150 sessions to sagg-export-2026-01-30-work-macbook.sagg (12.5 MB)
```

For imports:

```
Verifying archive...
[========================================] 100%

Importing sessions...
[========================================] 100% (150/150 sessions)

Import complete:
  - Imported: 142 new sessions
  - Skipped: 8 (already exist)
  - Errors: 0
```

---

## 4. Merge Strategy

### 4.1 Identity Model

Sessions are uniquely identified by the tuple:
```
(source, source_id)
```

For example:
- `(opencode, ses_abc123)`
- `(claude, 0195def...)`

This is the same identity model used internally by sagg.

### 4.2 Collision Detection

**Same session from same machine:** 
- Detected by matching `(source, source_id)`
- Behavior depends on `--strategy`

**Same source_id from different machines:**
- This shouldn't happen (source_ids are UUIDs generated by tools)
- If it does, treat as collision

### 4.3 Merge Strategies

#### 4.3.1 Skip (Default)

```
If session exists:
  Skip import, keep existing
Else:
  Import new session
```

Safe, non-destructive. Best for incremental imports.

#### 4.3.2 Replace

```
If session exists:
  Delete existing, import new
Else:
  Import new session
```

Use when source machine has the authoritative version.

#### 4.3.3 Rename

```
If session exists:
  Generate new sagg ID, import as new session
  Add metadata: "imported_from": original_id
Else:
  Import with original ID
```

Use for keeping both versions (rare).

### 4.4 Deduplication

Sessions are compared by `(source, source_id)` only. We don't attempt content-based deduplication because:
1. Same session can have different content if collected at different times
2. Content comparison is expensive
3. ID-based dedup is sufficient for the use case

### 4.5 Multi-Machine Scenario

**Scenario**: User has sessions on work-macbook and personal-imac, wants unified history.

```bash
# On work-macbook
sagg export -o work-sessions.sagg

# Transfer file to personal-imac (USB, rsync, whatever)

# On personal-imac
sagg export -o personal-sessions.sagg  # Backup first!
sagg import work-sessions.sagg --dry-run  # Preview
sagg import work-sessions.sagg  # Import with skip strategy

# Result: personal-imac has sessions from both machines
# No duplicates (skip strategy handles it)
```

### 4.6 Machine ID Tracking

To help users understand where sessions came from:

```bash
# Generate machine ID on first run, store in ~/.sagg/machine_id
$ cat ~/.sagg/machine_id
a1b2c3d4-e5f6-7890-abcd-ef1234567890

# Sessions track their origin
{
  "id": "0195abc...",
  "source_machine_id": "a1b2c3d4-...",  # Added during collection
  ...
}
```

This allows:
- Filtering by origin machine
- Understanding session provenance
- Debugging merge issues

---

## 5. Example Workflows

### 5.1 Daily Backup

```bash
# Create a backup of today's sessions
sagg export --since 1d -o ~/backups/sagg-$(date +%Y-%m-%d).sagg
```

### 5.2 Export from Work, Import to Personal

```bash
# On work machine
sagg export --since 30d -o /tmp/work-sessions.sagg

# Transfer (USB, email, cloud drive, etc.)
# ...

# On personal machine
sagg import /tmp/work-sessions.sagg --dry-run
# Looks good?
sagg import /tmp/work-sessions.sagg
```

### 5.3 Share Specific Sessions with Teammate

```bash
# Export specific sessions by ID
sagg export --id 0195abc,0195def,0195ghi -o auth-sessions.sagg

# Or by project
sagg export --project auth-service --since 7d -o auth-sessions.sagg

# Share file via Slack, email, etc.
```

### 5.4 Merge Two Machines

```bash
# Machine A: Export everything
sagg export -o machine-a.sagg

# Machine B: Export everything
sagg export -o machine-b.sagg

# On new machine (or either existing)
sagg import machine-a.sagg
sagg import machine-b.sagg
# Skip strategy handles duplicates automatically
```

### 5.5 Periodic Sync Between Machines

```bash
# Weekly sync script on work machine
#!/bin/bash
LAST_SYNC=$(cat ~/.sagg/last_sync_to_personal || echo "1970-01-01")
sagg export --since-date "$LAST_SYNC" -o /shared/work-sessions.sagg
date +%Y-%m-%d > ~/.sagg/last_sync_to_personal
```

```bash
# On personal machine
sagg import /shared/work-sessions.sagg
```

### 5.6 Verify Before Import

```bash
# Always verify untrusted archives
sagg verify colleague-sessions.sagg
# Archive: colleague-sessions.sagg
# ...
# Checksum: VALID

sagg import colleague-sessions.sagg --dry-run
# Shows what would be imported

sagg import colleague-sessions.sagg
```

---

## 6. Future Considerations

### 6.1 Team Sharing Features (v2)

**Redaction options:**
```bash
sagg export --redact-pii           # Remove emails, names, etc.
sagg export --redact-secrets       # Remove API keys, passwords
sagg export --redact-paths         # Anonymize file paths
sagg export --anonymize            # All of the above
```

**Selective content export:**
```bash
sagg export --metadata-only        # No conversation content
sagg export --summary-only         # Titles and stats only
```

### 6.2 Encryption (v2)

Not implementing in v1, but design for it:
```bash
sagg export -o backup.sagg.gpg --encrypt
# Uses gpg with user's default key

sagg import backup.sagg.gpg --decrypt
# Decrypts with gpg, then imports
```

Alternative: Users can pipe through gpg themselves:
```bash
sagg export | gpg -c > backup.sagg.gpg
gpg -d backup.sagg.gpg | sagg import -
```

### 6.3 Incremental Exports (v2)

```bash
# Store cursor for incremental exports
sagg export --incremental -o ~/backups/
# Creates ~/backups/sagg-export-2026-01-30.sagg
# Stores cursor in ~/.sagg/export_cursor

# Next export only includes new sessions
sagg export --incremental -o ~/backups/
# Creates ~/backups/sagg-export-2026-02-06.sagg (only new sessions)
```

### 6.4 Archive Splitting (v2)

For very large exports:
```bash
sagg export --split-size 50M -o backup
# Creates backup.001.sagg, backup.002.sagg, etc.
```

### 6.5 Compression Options (v2)

```bash
sagg export --compress zstd       # Faster, better compression
sagg export --compress none       # Uncompressed JSONL
sagg export --compress gzip       # Default
```

### 6.6 Remote Import (v2)

```bash
# Import from URL
sagg import https://example.com/sessions.sagg

# Import from S3
sagg import s3://bucket/path/sessions.sagg
```

---

## 7. Implementation Notes

### 7.1 Dependencies

No new dependencies required for v1:
- `gzip` module (stdlib)
- `json` module (stdlib)
- `hashlib` module (stdlib, for checksums)

### 7.2 Performance Considerations

**Export:**
- Stream sessions from DB, write directly to gzip stream
- No full materialization in memory
- Memory usage: O(1) per session

**Import:**
- Read gzip stream line-by-line
- Batch inserts to DB (500 sessions per transaction)
- Memory usage: O(1) per session

**Verification:**
- Single pass through file
- Compute checksum while reading
- Memory usage: O(1)

### 7.3 Error Handling

**Export errors:**
- DB read errors: Log warning, skip session, continue
- File write errors: Abort with clear message
- Keyboard interrupt: Clean up partial file

**Import errors:**
- Invalid header: Abort with clear message
- Malformed session: Log warning, skip, continue
- DB write errors: Log warning, skip, continue
- Checksum mismatch: Warn, prompt to continue

### 7.4 Testing Strategy

1. **Unit tests**: Header/footer parsing, path normalization
2. **Integration tests**: Full export/import cycle
3. **Roundtrip tests**: Export -> Import -> Export, compare
4. **Large file tests**: 1000+ sessions
5. **Cross-platform tests**: Export on macOS, import on Linux

---

## 8. Summary

### Recommended Format
- **JSONL with gzip compression** (`.sagg` extension)
- Header with metadata, footer with checksum
- Full session content included by default

### CLI Design
- `sagg export` - Create portable archives
- `sagg import` - Import with merge strategies
- `sagg verify` - Validate archive integrity

### Merge Strategy
- **Skip** (default): Safe, non-destructive
- **Replace**: For authoritative updates
- **Rename**: For keeping both versions

### Key Features
- Filtering by source, project, date range
- Dry-run mode for preview
- Progress indication
- Checksum verification
- Machine ID tracking for provenance

This design balances simplicity with robustness, using well-understood patterns from git, SQLite, and rsync while remaining specific to sagg's needs.
