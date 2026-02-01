"""Analytics module for session data analysis."""

from sagg.analytics.heatmap import (
    get_activity_by_day,
    generate_heatmap_data,
    render_heatmap,
    calculate_intensity,
)
from sagg.analytics.similar import (
    SimilarityResult,
    find_similar_sessions,
    tokenize,
    compute_tfidf,
    cosine_similarity,
)
from sagg.analytics.oracle import (
    OracleResult,
    search_history,
    extract_snippet,
    format_result,
    format_results_rich,
)
from sagg.analytics.friction import (
    FrictionType,
    FrictionPoint,
    analyze_retries,
    analyze_error_rate,
    analyze_back_and_forth,
    calculate_friction_score,
    detect_friction_points,
)

__all__ = [
    "get_activity_by_day",
    "generate_heatmap_data",
    "render_heatmap",
    "calculate_intensity",
    "SimilarityResult",
    "find_similar_sessions",
    "tokenize",
    "compute_tfidf",
    "cosine_similarity",
    "OracleResult",
    "search_history",
    "extract_snippet",
    "format_result",
    "format_results_rich",
    # Friction
    "FrictionType",
    "FrictionPoint",
    "analyze_retries",
    "analyze_error_rate",
    "analyze_back_and_forth",
    "calculate_friction_score",
    "detect_friction_points",
]
