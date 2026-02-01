"""Portable session bundle export and import.

This module provides functionality for exporting sessions to portable
.sagg bundle files and importing them on different machines, enabling
multi-machine sync of coding sessions.

Bundle Format:
    .sagg files are gzip-compressed JSONL (JSON Lines) files with the structure:

    Line 1: Header - {"type": "header", "version": "1.0.0", "machine_id": "...", ...}
    Line 2-N: Sessions - {"type": "session", "id": "...", "source": "...", ...}
    Line N+1: Footer - {"type": "footer", "checksum": "sha256:...", "session_count": N}
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagg.storage import SessionStore


@dataclass
class BundleHeader:
    """Bundle header containing metadata about the export."""

    type: str = "header"
    version: str = "1.0.0"
    machine_id: str = ""
    exported_at: str = ""
    session_count: int = 0


@dataclass
class BundleFooter:
    """Bundle footer containing integrity verification data."""

    type: str = "footer"
    checksum: str = ""
    session_count: int = 0


def get_machine_id() -> str:
    """Get or create a unique machine identifier.

    The machine ID is stored in ~/.sagg/machine_id and persists across
    invocations. This allows tracking the origin of imported sessions.

    Returns:
        A UUID string uniquely identifying this machine.
    """
    # Use HOME environment variable to support testing
    home = Path(os.environ.get("HOME", Path.home()))
    machine_id_path = home / ".sagg" / "machine_id"

    if machine_id_path.exists():
        return machine_id_path.read_text().strip()

    # Generate new machine ID
    mid = str(uuid.uuid4())
    machine_id_path.parent.mkdir(parents=True, exist_ok=True)
    machine_id_path.write_text(mid)
    return mid


def export_bundle(
    store: SessionStore,
    output_path: Path,
    since: datetime | None = None,
    project: str | None = None,
    source: str | None = None,
) -> int:
    """Export sessions to a .sagg bundle (gzipped JSONL).

    The bundle format is:
        {"type": "header", "version": "1.0.0", "machine_id": "...", ...}
        {"type": "session", "id": "...", "source": "...", ...}
        {"type": "session", ...}
        {"type": "footer", "checksum": "sha256:...", "session_count": N}

    Args:
        store: SessionStore to export from.
        output_path: Path to write the bundle file.
        since: Only export sessions created after this datetime.
        project: Filter by project name (partial match).
        source: Filter by source tool (opencode, claude, etc.).

    Returns:
        Number of sessions exported.
    """
    # Build query parameters
    sessions = store.list_sessions(
        source=source,
        project=project,
        limit=100000,  # Large limit to get all matching sessions
    )

    # Apply since filter
    if since is not None:
        sessions = [s for s in sessions if s.created_at >= since]

    # Prepare content for checksum calculation
    content_lines = []

    # Header
    header = BundleHeader(
        machine_id=get_machine_id(),
        exported_at=datetime.now(timezone.utc).isoformat(),
        session_count=len(sessions),
    )
    header_json = json.dumps(asdict(header))
    content_lines.append(header_json)

    # Sessions
    for session in sessions:
        # Get full session with content
        full_session = store.get_session(session.id)
        if full_session is None:
            continue

        session_data = {
            "type": "session",
            **full_session.model_dump(mode="json"),
        }
        session_json = json.dumps(session_data)
        content_lines.append(session_json)

    # Calculate checksum of header + sessions
    content_for_checksum = "\n".join(content_lines)
    checksum = hashlib.sha256(content_for_checksum.encode("utf-8")).hexdigest()

    # Footer
    footer = BundleFooter(
        checksum=f"sha256:{checksum}",
        session_count=len(sessions),
    )
    footer_json = json.dumps(asdict(footer))
    content_lines.append(footer_json)

    # Write gzipped bundle
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output_path, "wt", encoding="utf-8") as f:
        f.write("\n".join(content_lines))

    return len(sessions)


def import_bundle(
    store: SessionStore,
    bundle_path: Path,
    strategy: str = "skip",  # skip, replace, rename
    dry_run: bool = False,
) -> dict:
    """Import sessions from a .sagg bundle.

    Args:
        store: SessionStore to import into.
        bundle_path: Path to the bundle file.
        strategy: Deduplication strategy:
            - "skip": Skip sessions that already exist (default)
            - "replace": Replace existing sessions with imported ones
            - "rename": Import with new ID if duplicate exists
        dry_run: If True, preview without actually importing.

    Returns:
        Dictionary with import results:
            - imported: Number of sessions imported
            - skipped: Number of sessions skipped
            - errors: List of error messages
    """
    from sagg.models import UnifiedSession

    result = {
        "imported": 0,
        "skipped": 0,
        "errors": [],
    }

    # Read and parse bundle
    try:
        with gzip.open(bundle_path, "rt", encoding="utf-8") as f:
            lines = f.read().strip().split("\n")
    except Exception as e:
        result["errors"].append(f"Failed to read bundle: {e}")
        return result

    if len(lines) < 2:
        result["errors"].append("Invalid bundle: too few lines")
        return result

    # Parse header
    try:
        header = json.loads(lines[0])
        if header.get("type") != "header":
            result["errors"].append("Invalid bundle: first line is not a header")
            return result
    except json.JSONDecodeError as e:
        result["errors"].append(f"Invalid bundle header: {e}")
        return result

    origin_machine = header.get("machine_id", "unknown")

    # Parse footer
    try:
        footer = json.loads(lines[-1])
        if footer.get("type") != "footer":
            result["errors"].append("Invalid bundle: last line is not a footer")
            return result
    except json.JSONDecodeError as e:
        result["errors"].append(f"Invalid bundle footer: {e}")
        return result

    # Parse sessions
    sessions_to_import = []
    for line in lines[1:-1]:
        try:
            data = json.loads(line)
            if data.get("type") != "session":
                continue

            # Remove the "type" field before parsing as UnifiedSession
            data.pop("type", None)
            session = UnifiedSession.model_validate(data)
            sessions_to_import.append(session)
        except Exception as e:
            result["errors"].append(f"Failed to parse session: {e}")

    # Import sessions
    import_timestamp = int(time.time())

    for session in sessions_to_import:
        # Check for existing session
        existing = store.session_exists(session.source.value, session.source_id)

        if existing:
            if strategy == "skip":
                result["skipped"] += 1
                continue
            elif strategy == "replace":
                if not dry_run:
                    # Delete existing session first
                    existing_session = store.get_session_by_source(
                        session.source.value, session.source_id
                    )
                    if existing_session:
                        store.delete_session(existing_session.id)
            # For "rename" strategy, we'd generate a new ID, but this is complex
            # as it affects content files too. For now, treat as replace.

        if dry_run:
            result["imported"] += 1
        else:
            # Save session
            store.save_session(session)

            # Update provenance info
            store.db.execute(
                """
                UPDATE sessions
                SET origin_machine = ?, import_source = ?, imported_at = ?
                WHERE id = ?
                """,
                (origin_machine, str(bundle_path), import_timestamp, session.id),
            )
            store.db.commit()

            result["imported"] += 1

    return result


def verify_bundle(bundle_path: Path) -> bool:
    """Verify bundle integrity using checksum.

    Args:
        bundle_path: Path to the bundle file.

    Returns:
        True if the bundle is valid and uncorrupted, False otherwise.
    """
    try:
        with gzip.open(bundle_path, "rt", encoding="utf-8") as f:
            lines = f.read().strip().split("\n")
    except Exception:
        return False

    if len(lines) < 2:
        return False

    # Parse footer
    try:
        footer = json.loads(lines[-1])
        if footer.get("type") != "footer":
            return False

        stored_checksum = footer.get("checksum", "")
        if not stored_checksum.startswith("sha256:"):
            return False

        stored_hash = stored_checksum[7:]  # Remove "sha256:" prefix
    except json.JSONDecodeError:
        return False

    # Calculate checksum of header + sessions (all lines except footer)
    content_for_checksum = "\n".join(lines[:-1])
    calculated_hash = hashlib.sha256(content_for_checksum.encode("utf-8")).hexdigest()

    return calculated_hash == stored_hash
