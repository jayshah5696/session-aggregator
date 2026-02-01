"""Tests for the similarity module."""

import pytest
from datetime import datetime, timezone

from sagg.analytics.similar import (
    tokenize,
    compute_tfidf,
    cosine_similarity,
    find_similar_sessions,
    SimilarityResult,
    STOPWORDS,
)
from sagg.models import (
    UnifiedSession,
    Turn,
    Message,
    TextPart,
    SessionStats,
    SourceTool,
    generate_session_id,
)


class TestTokenize:
    """Tests for the tokenize function."""

    def test_basic_tokenization(self):
        """Test that basic text is tokenized correctly."""
        tokens = tokenize("Hello World")
        assert "hello" in tokens
        assert "world" in tokens

    def test_removes_punctuation(self):
        """Test that punctuation is removed."""
        tokens = tokenize("Hello, World! How are you?")
        # Should not have punctuation
        assert "," not in tokens
        assert "!" not in tokens
        assert "?" not in tokens

    def test_removes_stopwords(self):
        """Test that common stopwords are removed."""
        tokens = tokenize("the quick brown fox jumps over the lazy dog")
        assert "the" not in tokens
        assert "over" not in tokens
        assert "quick" in tokens
        assert "brown" in tokens
        assert "fox" in tokens

    def test_handles_code_identifiers(self):
        """Test that code-like identifiers are preserved."""
        tokens = tokenize("implement authentication using JWT tokens")
        assert "implement" in tokens
        assert "authentication" in tokens
        assert "jwt" in tokens
        assert "tokens" in tokens

    def test_handles_empty_string(self):
        """Test that empty string returns empty list."""
        tokens = tokenize("")
        assert tokens == []

    def test_handles_only_stopwords(self):
        """Test that a string of only stopwords returns empty list."""
        tokens = tokenize("the a an is are was were")
        assert tokens == []

    def test_handles_mixed_case(self):
        """Test that text is lowercased."""
        tokens = tokenize("HELLO World HeLLo")
        # All should be lowercased
        assert all(t.islower() or not t.isalpha() for t in tokens)

    def test_handles_numbers(self):
        """Test that numbers are handled appropriately."""
        tokens = tokenize("version 2 is better than version 1")
        # Numbers should be kept if meaningful
        assert "version" in tokens
        assert "better" in tokens

    def test_handles_special_characters(self):
        """Test handling of special characters in code."""
        tokens = tokenize("file.py function_name class-name")
        # Should split on special chars but preserve meaningful parts
        assert "file" in tokens or "py" in tokens


class TestComputeTFIDF:
    """Tests for TF-IDF computation."""

    def test_basic_tfidf(self):
        """Test basic TF-IDF computation."""
        documents = {
            "doc1": "the quick brown fox",
            "doc2": "the lazy brown dog",
            "doc3": "the quick dog jumps",
        }
        tfidf = compute_tfidf(documents)

        assert "doc1" in tfidf
        assert "doc2" in tfidf
        assert "doc3" in tfidf

        # Each document should have a vector
        assert isinstance(tfidf["doc1"], dict)

    def test_unique_terms_have_higher_weight(self):
        """Test that unique terms have higher TF-IDF scores."""
        documents = {
            "doc1": "fox fox fox common",
            "doc2": "dog dog dog common",
            "doc3": "cat cat cat common",
        }
        tfidf = compute_tfidf(documents)

        # 'common' appears in all docs, should have lower weight than unique terms
        # 'fox' only appears in doc1, should have higher weight there
        if "common" in tfidf["doc1"] and "fox" in tfidf["doc1"]:
            assert tfidf["doc1"]["fox"] > tfidf["doc1"]["common"]

    def test_empty_documents(self):
        """Test handling of empty documents dict."""
        tfidf = compute_tfidf({})
        assert tfidf == {}

    def test_single_document(self):
        """Test TF-IDF with a single document."""
        documents = {"doc1": "hello world hello"}
        tfidf = compute_tfidf(documents)
        assert "doc1" in tfidf
        # With single doc, IDF is less meaningful but TF should work


class TestCosineSimilarity:
    """Tests for cosine similarity computation."""

    def test_identical_vectors(self):
        """Test that identical vectors have similarity of 1.0."""
        vec = {"a": 1.0, "b": 2.0, "c": 3.0}
        similarity = cosine_similarity(vec, vec)
        assert abs(similarity - 1.0) < 0.0001

    def test_orthogonal_vectors(self):
        """Test that orthogonal vectors have similarity of 0.0."""
        vec1 = {"a": 1.0, "b": 0.0}
        vec2 = {"c": 1.0, "d": 0.0}
        similarity = cosine_similarity(vec1, vec2)
        assert abs(similarity - 0.0) < 0.0001

    def test_similar_vectors(self):
        """Test that similar vectors have high similarity."""
        vec1 = {"a": 1.0, "b": 2.0, "c": 3.0}
        vec2 = {"a": 1.0, "b": 2.0, "c": 2.8}
        similarity = cosine_similarity(vec1, vec2)
        assert similarity > 0.9

    def test_dissimilar_vectors(self):
        """Test that dissimilar vectors have low similarity."""
        vec1 = {"a": 1.0, "b": 0.0, "c": 0.0}
        vec2 = {"a": 0.0, "b": 0.0, "c": 1.0}
        similarity = cosine_similarity(vec1, vec2)
        assert similarity < 0.1

    def test_empty_vectors(self):
        """Test that empty vectors return 0.0 similarity."""
        vec1: dict[str, float] = {}
        vec2: dict[str, float] = {}
        similarity = cosine_similarity(vec1, vec2)
        assert similarity == 0.0

    def test_one_empty_vector(self):
        """Test that one empty vector returns 0.0 similarity."""
        vec1 = {"a": 1.0}
        vec2: dict[str, float] = {}
        similarity = cosine_similarity(vec1, vec2)
        assert similarity == 0.0


class TestFindSimilarSessions:
    """Tests for finding similar sessions."""

    def create_session(
        self,
        title: str,
        content: str,
        project_name: str = "test-project",
    ) -> UnifiedSession:
        """Helper to create a test session."""
        return UnifiedSession(
            id=generate_session_id(),
            source=SourceTool.OPENCODE,
            source_id=f"test-{title.replace(' ', '-')}",
            source_path="/tmp/test/session.json",
            title=title,
            project_name=project_name,
            project_path="/tmp/test-project",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            stats=SessionStats(turn_count=1, message_count=2),
            turns=[
                Turn(
                    id="turn-1",
                    index=0,
                    started_at=datetime.now(timezone.utc),
                    messages=[
                        Message(
                            id="msg-1",
                            role="user",
                            timestamp=datetime.now(timezone.utc),
                            parts=[TextPart(content=content)],
                        ),
                    ],
                )
            ],
        )

    def test_find_similar_by_query(self, session_store):
        """Test finding similar sessions by query string."""
        # Create sessions with different content
        auth_session = self.create_session(
            "Implement JWT authentication",
            "We need to add JWT token based authentication with refresh tokens",
            "backend-api",
        )
        login_session = self.create_session(
            "Fix login session handling",
            "Debug the authentication flow and fix session cookie issues",
            "frontend",
        )
        database_session = self.create_session(
            "Database migrations",
            "Create database migrations for the new user schema",
            "backend",
        )

        session_store.save_session(auth_session)
        session_store.save_session(login_session)
        session_store.save_session(database_session)

        # Search for authentication-related sessions
        results = find_similar_sessions(
            session_store,
            query="implement authentication",
            limit=5,
        )

        assert len(results) > 0
        # The auth session should be in results
        result_ids = [r.session_id for r in results]
        assert auth_session.id in result_ids

    def test_find_similar_to_session(self, session_store):
        """Test finding sessions similar to an existing session."""
        auth_session = self.create_session(
            "Add JWT authentication",
            "Implement JWT token authentication with middleware",
            "backend-api",
        )
        oauth_session = self.create_session(
            "Implement OAuth2 flow",
            "Add OAuth2 authentication support with token refresh",
            "api-gateway",
        )
        unrelated_session = self.create_session(
            "Fix CSS styling",
            "Update the button colors and fix responsive layout issues",
            "frontend",
        )

        session_store.save_session(auth_session)
        session_store.save_session(oauth_session)
        session_store.save_session(unrelated_session)

        # Find sessions similar to auth_session
        results = find_similar_sessions(
            session_store,
            session_id=auth_session.id,
            limit=5,
        )

        # The search should not include the session itself
        result_ids = [r.session_id for r in results]
        assert auth_session.id not in result_ids

        # OAuth session should be more similar than CSS session
        if len(results) >= 2:
            oauth_result = next((r for r in results if r.session_id == oauth_session.id), None)
            css_result = next((r for r in results if r.session_id == unrelated_session.id), None)
            if oauth_result and css_result:
                assert oauth_result.score > css_result.score

    def test_result_ranking(self, session_store):
        """Test that results are ranked by similarity score."""
        # Create sessions with varying similarity to a query
        exact_match = self.create_session(
            "Implement user authentication",
            "Implement user authentication with JWT tokens",
            "auth-service",
        )
        partial_match = self.create_session(
            "Fix auth bugs",
            "Fix authentication related bugs in the login flow",
            "frontend",
        )
        no_match = self.create_session(
            "Update database schema",
            "Create new tables for storing product inventory",
            "inventory",
        )

        session_store.save_session(exact_match)
        session_store.save_session(partial_match)
        session_store.save_session(no_match)

        results = find_similar_sessions(
            session_store,
            query="implement authentication",
            limit=10,
        )

        # Results should be sorted by score descending
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score

    def test_limit_results(self, session_store):
        """Test that limit parameter works correctly."""
        # Create multiple sessions
        for i in range(10):
            session = self.create_session(
                f"Authentication session {i}",
                "Implement authentication features",
                f"project-{i}",
            )
            session_store.save_session(session)

        results = find_similar_sessions(
            session_store,
            query="authentication",
            limit=3,
        )

        assert len(results) <= 3

    def test_matched_terms_populated(self, session_store):
        """Test that matched_terms field is populated in results."""
        session = self.create_session(
            "JWT authentication",
            "Implement JWT token authentication with refresh tokens",
            "backend",
        )
        session_store.save_session(session)

        results = find_similar_sessions(
            session_store,
            query="JWT authentication token",
            limit=5,
        )

        if results:
            # Should have some matched terms
            assert len(results[0].matched_terms) > 0

    def test_no_results_for_unmatched_query(self, session_store):
        """Test that no results are returned for completely unmatched query."""
        session = self.create_session(
            "Database optimization",
            "Optimize database queries for better performance",
            "backend",
        )
        session_store.save_session(session)

        results = find_similar_sessions(
            session_store,
            query="xyzzy12345nonsense",
            limit=5,
        )

        # Should return empty or very low scoring results
        assert len(results) == 0 or all(r.score < 0.1 for r in results)


class TestSimilarityResult:
    """Tests for SimilarityResult dataclass."""

    def test_create_result(self):
        """Test creating a SimilarityResult."""
        result = SimilarityResult(
            session_id="test-123",
            title="Test Session",
            score=0.85,
            project="test-project",
            matched_terms=["authentication", "jwt", "token"],
        )

        assert result.session_id == "test-123"
        assert result.title == "Test Session"
        assert result.score == 0.85
        assert result.project == "test-project"
        assert len(result.matched_terms) == 3

    def test_result_ordering(self):
        """Test that results can be sorted by score."""
        results = [
            SimilarityResult("a", "A", 0.5, "p1", []),
            SimilarityResult("b", "B", 0.9, "p2", []),
            SimilarityResult("c", "C", 0.7, "p3", []),
        ]

        sorted_results = sorted(results, key=lambda r: r.score, reverse=True)
        assert sorted_results[0].session_id == "b"
        assert sorted_results[1].session_id == "c"
        assert sorted_results[2].session_id == "a"
