"""Tests for facet storage methods and schema v4 migration."""

import json
import time

import pytest
from datetime import datetime, timezone, timedelta

from sagg.storage.db import SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_facet(
    session_id,
    source="claude",
    task_type="feature",
    outcome="fully_achieved",
    friction_score=0.0,
):
    """Build a sample facet dict suitable for ``SessionStore.upsert_facet``."""
    return {
        "session_id": session_id,
        "source": source,
        "analyzed_at": int(time.time()),
        "analyzer_version": "heuristic_v1",
        "analyzer_model": None,
        "underlying_goal": "Test goal",
        "goal_categories": {"feature": 1},
        "task_type": task_type,
        "outcome": outcome,
        "completion_confidence": 0.7,
        "session_type": "single_task",
        "complexity_score": 3,
        "friction_counts": {},
        "friction_detail": None,
        "friction_score": friction_score,
        "tools_that_helped": ["Read", "Edit"],
        "tools_that_didnt": [],
        "tool_helpfulness": "very",
        "primary_language": "python",
        "files_pattern": "python_backend",
        "brief_summary": "Test session",
        "key_decisions": [],
    }


# ---------------------------------------------------------------------------
# 1. Schema / migration
# ---------------------------------------------------------------------------

class TestSchemaVersion:
    """Verify the v5 migration creates expected tables and indexes."""

    def test_schema_version_is_5(self):
        assert SCHEMA_VERSION == 5

    def test_migration_creates_facets_table(self, session_store):
        cursor = session_store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_facets'"
        )
        assert cursor.fetchone() is not None

    def test_migration_creates_cache_table(self, session_store):
        cursor = session_store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='insights_cache'"
        )
        assert cursor.fetchone() is not None

    def test_facets_indexes_exist(self, session_store):
        cursor = session_store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_facets_%'"
        )
        index_names = {row["name"] for row in cursor}
        expected = {
            "idx_facets_source",
            "idx_facets_task_type",
            "idx_facets_outcome",
            "idx_facets_analyzed",
            "idx_facets_language",
        }
        assert expected.issubset(index_names), f"Missing indexes: {expected - index_names}"


# ---------------------------------------------------------------------------
# 2. upsert_facet
# ---------------------------------------------------------------------------

class TestUpsertFacet:
    """Test inserting and updating facets."""

    def test_insert_facet(self, session_store, sample_session):
        session_store.save_session(sample_session)
        facet = make_facet(sample_session.id)
        session_store.upsert_facet(facet)

        retrieved = session_store.get_facet(sample_session.id)
        assert retrieved is not None
        assert retrieved["session_id"] == sample_session.id
        assert retrieved["task_type"] == "feature"
        assert retrieved["outcome"] == "fully_achieved"
        assert retrieved["brief_summary"] == "Test session"

    def test_update_facet(self, session_store, sample_session):
        session_store.save_session(sample_session)
        facet = make_facet(sample_session.id, task_type="bugfix")
        session_store.upsert_facet(facet)

        # Upsert again with different values
        updated = make_facet(sample_session.id, task_type="refactor", outcome="partial")
        session_store.upsert_facet(updated)

        retrieved = session_store.get_facet(sample_session.id)
        assert retrieved is not None
        assert retrieved["task_type"] == "refactor"
        assert retrieved["outcome"] == "partial"

    def test_facet_json_fields_serialized(self, session_store, sample_session):
        """goal_categories and friction_counts are stored as JSON text in DB."""
        session_store.save_session(sample_session)
        facet = make_facet(sample_session.id)
        facet["goal_categories"] = {"feature": 2, "debugging": 1}
        facet["friction_counts"] = {"tool_error": 3, "context_loss": 1}
        session_store.upsert_facet(facet)

        # Read raw row to verify JSON serialisation
        cursor = session_store._db.execute(
            "SELECT goal_categories_json, friction_counts_json FROM session_facets WHERE session_id = ?",
            (sample_session.id,),
        )
        row = cursor.fetchone()
        assert row is not None

        parsed_gc = json.loads(row["goal_categories_json"])
        assert parsed_gc == {"feature": 2, "debugging": 1}

        parsed_fc = json.loads(row["friction_counts_json"])
        assert parsed_fc == {"tool_error": 3, "context_loss": 1}


# ---------------------------------------------------------------------------
# 3. get_facet
# ---------------------------------------------------------------------------

class TestGetFacet:
    """Test single-facet retrieval."""

    def test_get_existing_facet(self, session_store, sample_session):
        session_store.save_session(sample_session)
        facet = make_facet(sample_session.id)
        session_store.upsert_facet(facet)

        result = session_store.get_facet(sample_session.id)
        assert result is not None
        assert result["session_id"] == sample_session.id
        assert result["analyzer_version"] == "heuristic_v1"

    def test_get_nonexistent_facet_returns_none(self, session_store):
        result = session_store.get_facet("nonexistent-session-id")
        assert result is None

    def test_facet_json_fields_deserialized(self, session_store, sample_session):
        """JSON columns are parsed back into Python dicts/lists."""
        session_store.save_session(sample_session)
        facet = make_facet(sample_session.id)
        facet["goal_categories"] = {"exploration": 5}
        facet["friction_counts"] = {"compile_error": 2}
        facet["tools_that_helped"] = ["Read", "Grep"]
        facet["tools_that_didnt"] = ["WebFetch"]
        facet["key_decisions"] = ["Used grep instead of find"]
        session_store.upsert_facet(facet)

        result = session_store.get_facet(sample_session.id)
        assert result is not None

        # dicts
        assert isinstance(result["goal_categories"], dict)
        assert result["goal_categories"] == {"exploration": 5}
        assert isinstance(result["friction_counts"], dict)
        assert result["friction_counts"] == {"compile_error": 2}

        # lists
        assert isinstance(result["tools_that_helped"], list)
        assert result["tools_that_helped"] == ["Read", "Grep"]
        assert isinstance(result["tools_that_didnt"], list)
        assert result["tools_that_didnt"] == ["WebFetch"]
        assert isinstance(result["key_decisions"], list)
        assert result["key_decisions"] == ["Used grep instead of find"]


# ---------------------------------------------------------------------------
# 4. get_facets (multi-facet retrieval with filters)
# ---------------------------------------------------------------------------

class TestGetFacets:
    """Test filtered multi-facet queries."""

    def _save_two_sessions(self, session_store, sample_session):
        """Save two sessions (different sources) and attach facets."""
        from sagg.models import generate_session_id, UnifiedSession, SourceTool, SessionStats

        session_store.save_session(sample_session)

        second = UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.CLAUDE,
            source_id="test-session-2",
            source_path="/tmp/test/session2.json",
            title="Second Session",
            project_name="other-project",
            project_path="/tmp/other-project",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            stats=SessionStats(turn_count=1, message_count=1, input_tokens=50, output_tokens=25),
            turns=[],
        )
        session_store.save_session(second)

        # Facet for first session (source matches sample_session.source, "opencode")
        session_store.upsert_facet(make_facet(sample_session.id, source="opencode"))
        # Facet for second session
        session_store.upsert_facet(make_facet(second.id, source="claude", task_type="debugging"))

        return second

    def test_get_all_facets(self, session_store, sample_session):
        self._save_two_sessions(session_store, sample_session)
        facets = session_store.get_facets()
        assert len(facets) == 2

    def test_filter_by_source(self, session_store, sample_session):
        self._save_two_sessions(session_store, sample_session)
        facets = session_store.get_facets(source="claude")
        assert len(facets) == 1
        assert facets[0]["source"] == "claude"

    def test_filter_by_since(self, session_store, sample_session):
        self._save_two_sessions(session_store, sample_session)
        # All sessions were just created, so a "since" in the far past returns all
        long_ago = datetime.now(timezone.utc) - timedelta(days=365)
        facets = session_store.get_facets(since=long_ago)
        assert len(facets) == 2

        # A "since" in the future returns none
        future = datetime.now(timezone.utc) + timedelta(days=1)
        facets = session_store.get_facets(since=future)
        assert len(facets) == 0

    def test_filter_by_project(self, session_store, sample_session):
        self._save_two_sessions(session_store, sample_session)
        facets = session_store.get_facets(project="test-project")
        assert len(facets) == 1
        assert facets[0]["session_id"] == sample_session.id

    def test_limit(self, session_store, sample_session):
        self._save_two_sessions(session_store, sample_session)
        facets = session_store.get_facets(limit=1)
        assert len(facets) == 1


# ---------------------------------------------------------------------------
# 5. get_unfaceted_sessions
# ---------------------------------------------------------------------------

class TestGetUnfacetedSessions:
    """Test discovery of sessions without facets."""

    def test_all_sessions_unfaceted(self, session_store, sample_session):
        session_store.save_session(sample_session)
        unfaceted = session_store.get_unfaceted_sessions()
        assert len(unfaceted) == 1
        assert unfaceted[0].id == sample_session.id

    def test_excludes_faceted_sessions(self, session_store, sample_session):
        session_store.save_session(sample_session)
        session_store.upsert_facet(make_facet(sample_session.id, source="opencode"))

        unfaceted = session_store.get_unfaceted_sessions()
        assert len(unfaceted) == 0

    def test_filter_by_source(self, session_store, sample_session):
        from sagg.models import generate_session_id, UnifiedSession, SourceTool, SessionStats

        session_store.save_session(sample_session)

        second = UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.CLAUDE,
            source_id="test-session-unfacet-2",
            source_path="/tmp/test/session3.json",
            title="Claude Session",
            project_name="proj",
            project_path="/tmp/proj",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            stats=SessionStats(turn_count=0, message_count=0, input_tokens=0, output_tokens=0),
            turns=[],
        )
        session_store.save_session(second)

        unfaceted = session_store.get_unfaceted_sessions(source="claude")
        assert len(unfaceted) == 1
        assert unfaceted[0].id == second.id

    def test_filter_by_since(self, session_store, sample_session):
        session_store.save_session(sample_session)

        future = datetime.now(timezone.utc) + timedelta(days=1)
        unfaceted = session_store.get_unfaceted_sessions(since=future)
        assert len(unfaceted) == 0

        past = datetime.now(timezone.utc) - timedelta(days=1)
        unfaceted = session_store.get_unfaceted_sessions(since=past)
        assert len(unfaceted) == 1

    def test_filter_by_project(self, session_store, sample_session):
        from sagg.models import generate_session_id, UnifiedSession, SourceTool, SessionStats

        session_store.save_session(sample_session)

        second = UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.CLAUDE,
            source_id="test-session-unfacet-project",
            source_path="/tmp/test/session-project.json",
            title="Claude Session",
            project_name="other-project",
            project_path="/tmp/other-project",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            stats=SessionStats(turn_count=0, message_count=0, input_tokens=0, output_tokens=0),
            turns=[],
        )
        session_store.save_session(second)

        unfaceted = session_store.get_unfaceted_sessions(project="test-project")
        assert len(unfaceted) == 1
        assert unfaceted[0].id == sample_session.id


# ---------------------------------------------------------------------------
# 6. get_facet_stats
# ---------------------------------------------------------------------------

class TestGetFacetStats:
    """Test aggregated statistics."""

    def test_empty_stats(self, session_store):
        stats = session_store.get_facet_stats()
        assert stats["total_facets"] == 0
        assert stats["facets_by_source"] == {}
        assert stats["facets_by_task_type"] == {}
        assert stats["facets_by_outcome"] == {}

    def test_counts_by_source(self, session_store, sample_session):
        from sagg.models import generate_session_id, UnifiedSession, SourceTool, SessionStats

        session_store.save_session(sample_session)

        second = UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.CLAUDE,
            source_id="test-stats-2",
            source_path="/tmp/test/s2.json",
            title="S2",
            project_name="p",
            project_path="/tmp/p",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            stats=SessionStats(turn_count=0, message_count=0, input_tokens=0, output_tokens=0),
            turns=[],
        )
        session_store.save_session(second)

        session_store.upsert_facet(make_facet(sample_session.id, source="opencode"))
        session_store.upsert_facet(make_facet(second.id, source="claude"))

        stats = session_store.get_facet_stats()
        assert stats["total_facets"] == 2
        assert stats["facets_by_source"]["opencode"] == 1
        assert stats["facets_by_source"]["claude"] == 1

    def test_counts_by_task_type(self, session_store, sample_session):
        from sagg.models import generate_session_id, UnifiedSession, SourceTool, SessionStats

        session_store.save_session(sample_session)

        second = UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.CLAUDE,
            source_id="test-stats-tt",
            source_path="/tmp/test/stt.json",
            title="S-TT",
            project_name="p",
            project_path="/tmp/p",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            stats=SessionStats(turn_count=0, message_count=0, input_tokens=0, output_tokens=0),
            turns=[],
        )
        session_store.save_session(second)

        session_store.upsert_facet(make_facet(sample_session.id, source="opencode", task_type="feature"))
        session_store.upsert_facet(make_facet(second.id, source="claude", task_type="debugging"))

        stats = session_store.get_facet_stats()
        assert stats["facets_by_task_type"]["feature"] == 1
        assert stats["facets_by_task_type"]["debugging"] == 1

    def test_counts_by_outcome(self, session_store, sample_session):
        from sagg.models import generate_session_id, UnifiedSession, SourceTool, SessionStats

        session_store.save_session(sample_session)

        second = UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.CLAUDE,
            source_id="test-stats-oc",
            source_path="/tmp/test/soc.json",
            title="S-OC",
            project_name="p",
            project_path="/tmp/p",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            stats=SessionStats(turn_count=0, message_count=0, input_tokens=0, output_tokens=0),
            turns=[],
        )
        session_store.save_session(second)

        session_store.upsert_facet(make_facet(sample_session.id, source="opencode", outcome="fully_achieved"))
        session_store.upsert_facet(make_facet(second.id, source="claude", outcome="abandoned"))

        stats = session_store.get_facet_stats()
        assert stats["facets_by_outcome"]["fully_achieved"] == 1
        assert stats["facets_by_outcome"]["abandoned"] == 1


# ---------------------------------------------------------------------------
# 7. Cascade delete
# ---------------------------------------------------------------------------

class TestFacetCascadeDelete:
    """Verify ON DELETE CASCADE from sessions -> session_facets."""

    def test_deleting_session_deletes_facet(self, session_store, sample_session):
        session_store.save_session(sample_session)
        session_store.upsert_facet(make_facet(sample_session.id, source="opencode"))

        # Confirm facet exists
        assert session_store.get_facet(sample_session.id) is not None

        # Delete the parent session
        deleted = session_store.delete_session(sample_session.id)
        assert deleted is True

        # Facet should be gone
        assert session_store.get_facet(sample_session.id) is None


# ---------------------------------------------------------------------------
# 8. facet_json column (v5 migration)
# ---------------------------------------------------------------------------

class TestFacetJsonColumn:
    """Verify the v5 migration adds facet_json and it round-trips correctly."""

    def test_facet_json_column_exists(self, session_store):
        cursor = session_store._db.execute("PRAGMA table_info(session_facets)")
        columns = {row["name"] for row in cursor}
        assert "facet_json" in columns

    def test_upsert_stores_facet_json(self, session_store, sample_session):
        session_store.save_session(sample_session)
        facet = make_facet(sample_session.id)
        facet["tool_calls_total"] = 42
        facet["error_rate"] = 0.15
        session_store.upsert_facet(facet)

        cursor = session_store._db.execute(
            "SELECT facet_json FROM session_facets WHERE session_id = ?",
            (sample_session.id,),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["facet_json"] is not None

        parsed = json.loads(row["facet_json"])
        assert parsed["tool_calls_total"] == 42
        assert parsed["error_rate"] == 0.15

    def test_get_facet_includes_facet_json(self, session_store, sample_session):
        session_store.save_session(sample_session)
        facet = make_facet(sample_session.id)
        facet["intervention_count"] = 5
        session_store.upsert_facet(facet)

        result = session_store.get_facet(sample_session.id)
        assert result is not None
        assert "facet_json" in result
        assert isinstance(result["facet_json"], dict)
        assert result["facet_json"]["intervention_count"] == 5
