"""Similarity analysis for finding related sessions.

This module provides lightweight TF-IDF based similarity search
for finding sessions related to a query or another session.
No external ML dependencies required.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from math import log, sqrt
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagg.storage import SessionStore

# Common English stopwords to filter out
STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "must", "shall",
    "can", "need", "dare", "ought", "used", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "each", "few", "more", "most", "other", "some", "such",
    "no", "nor", "not", "only", "own", "same", "so", "than", "too",
    "very", "just", "also", "now", "over", "it", "its", "this", "that",
    "these", "those", "i", "me", "my", "myself", "we", "our", "ours",
    "ourselves", "you", "your", "yours", "yourself", "yourselves", "he",
    "him", "his", "himself", "she", "her", "hers", "herself", "they",
    "them", "their", "theirs", "themselves", "what", "which", "who",
    "whom", "if", "because", "until", "while", "about", "against",
    "any", "both", "down", "up", "out", "off", "s", "t", "don", "didn",
    "doesn", "hadn", "hasn", "haven", "isn", "aren", "wasn", "weren",
    "won", "wouldn", "couldn", "shouldn", "ve", "re", "ll", "d", "m",
})


@dataclass
class SimilarityResult:
    """Result of a similarity search.

    Attributes:
        session_id: The ID of the similar session.
        title: The title of the session.
        score: Similarity score from 0.0 to 1.0.
        project: The project name of the session.
        matched_terms: List of terms that matched between query and session.
    """

    session_id: str
    title: str
    score: float
    project: str
    matched_terms: list[str]


def tokenize(text: str) -> list[str]:
    """Extract meaningful tokens from text.

    Converts text to lowercase, splits on whitespace and punctuation,
    removes stopwords, and returns a list of meaningful tokens.

    Args:
        text: The text to tokenize.

    Returns:
        List of lowercase tokens with stopwords removed.
    """
    if not text:
        return []

    # Convert to lowercase
    text = text.lower()

    # Split on non-alphanumeric characters (keeping numbers)
    tokens = re.findall(r"\b[a-z0-9]+\b", text)

    # Remove stopwords and very short tokens
    tokens = [t for t in tokens if t not in STOPWORDS and len(t) > 1]

    return tokens


def compute_tfidf(documents: dict[str, str]) -> dict[str, dict[str, float]]:
    """Compute TF-IDF vectors for a collection of documents.

    TF-IDF (Term Frequency-Inverse Document Frequency) weighs terms
    by how frequently they appear in a document relative to how
    common they are across all documents.

    Args:
        documents: Dictionary mapping document IDs to their text content.

    Returns:
        Dictionary mapping document IDs to their TF-IDF vectors.
        Each vector is a dict mapping terms to their TF-IDF scores.
    """
    if not documents:
        return {}

    # Tokenize all documents
    doc_tokens: dict[str, list[str]] = {}
    for doc_id, text in documents.items():
        doc_tokens[doc_id] = tokenize(text)

    # Count document frequency for each term
    doc_freq: Counter[str] = Counter()
    for tokens in doc_tokens.values():
        # Count each term once per document
        unique_terms = set(tokens)
        doc_freq.update(unique_terms)

    # Total number of documents
    num_docs = len(documents)

    # Compute TF-IDF for each document
    tfidf_vectors: dict[str, dict[str, float]] = {}

    for doc_id, tokens in doc_tokens.items():
        if not tokens:
            tfidf_vectors[doc_id] = {}
            continue

        # Term frequency in this document
        term_freq = Counter(tokens)
        total_terms = len(tokens)

        # Compute TF-IDF for each term
        tfidf: dict[str, float] = {}
        for term, count in term_freq.items():
            # TF: normalized term frequency
            tf = count / total_terms

            # IDF: inverse document frequency with smoothing
            # Add 1 to avoid division by zero and log(0)
            idf = log((num_docs + 1) / (doc_freq[term] + 1)) + 1

            tfidf[term] = tf * idf

        tfidf_vectors[doc_id] = tfidf

    return tfidf_vectors


def cosine_similarity(vec1: dict[str, float], vec2: dict[str, float]) -> float:
    """Compute cosine similarity between two TF-IDF vectors.

    Cosine similarity measures the cosine of the angle between two vectors,
    ranging from 0 (orthogonal/dissimilar) to 1 (identical direction).

    Args:
        vec1: First TF-IDF vector (term -> weight mapping).
        vec2: Second TF-IDF vector (term -> weight mapping).

    Returns:
        Cosine similarity score between 0.0 and 1.0.
    """
    if not vec1 or not vec2:
        return 0.0

    # Find common terms
    common_terms = set(vec1.keys()) & set(vec2.keys())

    if not common_terms:
        return 0.0

    # Compute dot product
    dot_product = sum(vec1[term] * vec2[term] for term in common_terms)

    # Compute magnitudes
    magnitude1 = sqrt(sum(v * v for v in vec1.values()))
    magnitude2 = sqrt(sum(v * v for v in vec2.values()))

    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0

    return dot_product / (magnitude1 * magnitude2)


def find_similar_sessions(
    store: SessionStore,
    query: str | None = None,
    session_id: str | None = None,
    limit: int = 10,
) -> list[SimilarityResult]:
    """Find sessions similar to a query or another session.

    Uses a lightweight TF-IDF approach for similarity computation.
    First retrieves candidates via FTS5 search, then re-ranks using
    cosine similarity of TF-IDF vectors.

    Args:
        store: The session store to search.
        query: Text query to find similar sessions for.
        session_id: ID of a session to find similar sessions to.
        limit: Maximum number of results to return.

    Returns:
        List of SimilarityResult objects sorted by similarity score.

    Raises:
        ValueError: If neither query nor session_id is provided.
    """
    if not query and not session_id:
        raise ValueError("Either query or session_id must be provided")

    # If session_id is provided, extract its content as the query
    source_session = None
    if session_id:
        source_session = store.get_session(session_id)
        if source_session is None:
            raise ValueError(f"Session '{session_id}' not found")
        # Extract text content from the session
        query = source_session.extract_text_content()[:2000]  # Limit length
        # Also include title
        if source_session.title:
            query = source_session.title + " " + query

    # Ensure query is not None at this point
    assert query is not None

    # If query is too short, try to use it directly
    if len(query.strip()) < 3:
        return []

    # Get candidate sessions via FTS5 search
    # Use first 100 chars of query for initial filtering
    fts_query = query[:100].strip()

    # Clean the query for FTS5 (remove special characters)
    fts_query = re.sub(r"[^\w\s]", " ", fts_query)
    fts_query = " ".join(fts_query.split())  # Normalize whitespace

    if not fts_query:
        return []

    try:
        candidates = store.search_sessions(fts_query, limit=limit * 3)
    except Exception:
        # FTS5 might fail on certain queries, fall back to listing
        candidates = store.list_sessions(limit=limit * 3)

    if not candidates:
        return []

    # Filter out the source session if we're finding similar to a session
    if source_session:
        candidates = [c for c in candidates if c.id != source_session.id]

    if not candidates:
        return []

    # Build document collection for TF-IDF
    documents: dict[str, str] = {"__query__": query}
    for candidate in candidates:
        # Combine title and content for matching
        content = candidate.extract_text_content()[:2000]
        if candidate.title:
            content = candidate.title + " " + content
        documents[candidate.id] = content

    # Compute TF-IDF vectors
    tfidf_vectors = compute_tfidf(documents)

    query_vector = tfidf_vectors.get("__query__", {})
    if not query_vector:
        return []

    # Tokenize query for matched terms detection
    query_tokens = set(tokenize(query))

    # Score and rank candidates
    results: list[SimilarityResult] = []

    for candidate in candidates:
        candidate_vector = tfidf_vectors.get(candidate.id, {})
        if not candidate_vector:
            continue

        score = cosine_similarity(query_vector, candidate_vector)

        # Find matched terms
        candidate_terms = set(candidate_vector.keys())
        matched_terms = list(query_tokens & candidate_terms)[:10]  # Limit to 10 terms

        results.append(
            SimilarityResult(
                session_id=candidate.id,
                title=candidate.title or "Untitled",
                score=score,
                project=candidate.project_name or "Unknown",
                matched_terms=matched_terms,
            )
        )

    # Sort by score descending
    results.sort(key=lambda r: r.score, reverse=True)

    # Return top results
    return results[:limit]
