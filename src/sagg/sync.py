"""Session sync module for incremental collection with watch mode support."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from sagg.adapters.base import SessionAdapter
    from sagg.storage.store import SessionStore

logger = logging.getLogger(__name__)


class SyncEvent:
    """Represents a sync event from watch mode."""

    def __init__(
        self,
        source: str,
        new_count: int,
        skipped_count: int,
        timestamp: datetime | None = None,
    ):
        self.source = source
        self.new_count = new_count
        self.skipped_count = skipped_count
        self.timestamp = timestamp or datetime.now(timezone.utc)


class SessionSyncer:
    """Handles incremental session syncing with optional watch mode."""

    def __init__(
        self,
        store: SessionStore,
        adapters: list[SessionAdapter],
    ):
        """Initialize the session syncer.

        Args:
            store: SessionStore instance for persistence.
            adapters: List of session adapters to sync from.
        """
        self.store = store
        self.adapters = adapters
        self._adapters_by_name = {a.name: a for a in adapters}

    def sync_once(
        self,
        source: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, dict[str, int]]:
        """Perform one-time incremental sync.

        Args:
            source: Optional source filter (e.g., 'opencode').
            dry_run: If True, don't actually save sessions or update state.

        Returns:
            Dictionary mapping source names to sync results:
            {source: {'new': N, 'skipped': M}}
        """
        results: dict[str, dict[str, int]] = {}

        for adapter in self._get_adapters(source):
            if not adapter.is_available():
                logger.debug("Skipping unavailable adapter: %s", adapter.name)
                continue

            result = self._sync_adapter(adapter, dry_run=dry_run)
            results[adapter.name] = result

        return results

    def _sync_adapter(
        self,
        adapter: SessionAdapter,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Sync sessions from a single adapter.

        Args:
            adapter: The adapter to sync from.
            dry_run: If True, don't save sessions or update state.

        Returns:
            Dictionary with 'new' and 'skipped' counts.
        """
        new_count = 0
        skipped_count = 0

        # Get last sync time for incremental sync
        sync_state = self.store.get_sync_state(adapter.name)
        since: datetime | None = None
        if sync_state is not None:
            since = datetime.fromtimestamp(sync_state["last_sync_at"], tz=timezone.utc)

        try:
            refs = adapter.list_sessions(since=since)
        except Exception as e:
            logger.error("Failed to list sessions from %s: %s", adapter.name, e)
            return {"new": 0, "skipped": 0, "error": 1}

        for ref in refs:
            # Check if already imported
            if self.store.session_exists(adapter.name, ref.id):
                skipped_count += 1
                continue

            try:
                session = adapter.parse_session(ref)

                if not dry_run:
                    self.store.save_session(session)

                new_count += 1
            except Exception as e:
                logger.warning(
                    "Failed to parse session %s from %s: %s",
                    ref.id,
                    adapter.name,
                    e,
                )

        # Update sync state (only if not dry run and we processed something)
        if not dry_run:
            current_time = int(time.time())
            total_count = (sync_state["session_count"] if sync_state else 0) + new_count
            self.store.update_sync_state(adapter.name, current_time, total_count)

        return {"new": new_count, "skipped": skipped_count}

    def get_watch_paths(self, source: str | None = None) -> list[Path]:
        """Get paths to watch for file changes.

        Args:
            source: Optional source filter.

        Returns:
            List of paths to watch.
        """
        paths: list[Path] = []

        for adapter in self._get_adapters(source):
            if not adapter.is_available():
                continue
            paths.append(adapter.get_default_path())

        return paths

    def watch(
        self,
        source: str | None = None,
        debounce_ms: int = 2000,
    ) -> Iterator[SyncEvent]:
        """Watch for changes and sync continuously.

        Uses the watchfiles library for filesystem monitoring.
        Yields SyncEvent objects when syncs complete.

        Args:
            source: Optional source filter.
            debounce_ms: Debounce interval in milliseconds.

        Yields:
            SyncEvent objects on each sync.
        """
        try:
            from watchfiles import watch as watch_files
        except ImportError as e:
            raise ImportError(
                "watchfiles is required for watch mode. "
                "Install it with: uv add watchfiles"
            ) from e

        paths = self.get_watch_paths(source)
        if not paths:
            logger.warning("No paths to watch - no available adapters")
            return

        # Convert paths to strings for watchfiles
        watch_paths = [str(p) for p in paths if p.exists()]
        if not watch_paths:
            logger.warning("No existing paths to watch")
            return

        logger.info("Watching paths: %s", watch_paths)

        # watchfiles handles debouncing internally
        debounce_seconds = debounce_ms / 1000.0

        for changes in watch_files(*watch_paths, debounce=debounce_seconds):
            # Determine which sources had changes
            changed_sources = self._identify_changed_sources(changes, paths)

            for src in changed_sources:
                adapter = self._adapters_by_name.get(src)
                if adapter is None:
                    continue

                result = self._sync_adapter(adapter, dry_run=False)
                yield SyncEvent(
                    source=src,
                    new_count=result["new"],
                    skipped_count=result["skipped"],
                )

    def _get_adapters(self, source: str | None = None) -> list[SessionAdapter]:
        """Get adapters, optionally filtered by source name.

        Args:
            source: Optional source name filter.

        Returns:
            List of matching adapters.
        """
        if source is None:
            return self.adapters

        adapter = self._adapters_by_name.get(source)
        if adapter is not None:
            return [adapter]

        return []

    def _identify_changed_sources(
        self,
        changes: set[tuple],
        watch_paths: list[Path],
    ) -> list[str]:
        """Identify which sources had file changes.

        Args:
            changes: Set of (change_type, path) tuples from watchfiles.
            watch_paths: List of paths being watched.

        Returns:
            List of source names that had changes.
        """
        changed_sources: set[str] = set()

        for _change_type, changed_path in changes:
            changed_path = Path(changed_path)

            for adapter in self.adapters:
                adapter_path = adapter.get_default_path()
                try:
                    # Check if the changed path is under this adapter's path
                    changed_path.relative_to(adapter_path)
                    changed_sources.add(adapter.name)
                    break
                except ValueError:
                    # Not under this path
                    continue

        return list(changed_sources)
