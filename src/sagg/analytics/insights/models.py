"""Data models for session insights and facet analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SessionFacet(BaseModel):
    """AI-extracted or heuristic-extracted analysis of a single session."""

    # Identity
    session_id: str
    source: str  # tool name (claude, cursor, opencode, etc.)
    analyzed_at: datetime

    # Goal classification
    underlying_goal: str
    goal_categories: dict[str, int] = Field(default_factory=dict)
    task_type: str  # bugfix | feature | refactor | docs | debug | config | exploration

    # Outcome
    outcome: str  # fully_achieved | partially_achieved | abandoned | unclear
    completion_confidence: float = 0.5

    # Session characteristics
    session_type: str  # quick_question | single_task | multi_task | iterative_refinement
    complexity_score: int = 3  # 1-5

    # Friction
    friction_counts: dict[str, int] = Field(default_factory=dict)
    friction_detail: str | None = None
    friction_score: float = 0.0

    # Tool effectiveness
    tools_that_helped: list[str] = Field(default_factory=list)
    tools_that_didnt: list[str] = Field(default_factory=list)
    tool_helpfulness: str = "moderately"  # unhelpful | slightly | moderately | very | extremely

    # Context
    primary_language: str | None = None
    files_pattern: str | None = None

    # Summary
    brief_summary: str = ""
    key_decisions: list[str] = Field(default_factory=list)


class AtAGlance(BaseModel):
    whats_working: str = ""
    whats_hindering: str = ""
    quick_wins: str = ""
    ambitious_workflows: str = ""


class ProjectArea(BaseModel):
    name: str
    session_count: int = 0
    description: str = ""
    primary_tools: list[str] = Field(default_factory=list)
    success_rate: float = 0.0
    avg_friction: float = 0.0


class InteractionStyle(BaseModel):
    narrative: str = ""
    key_pattern: str = ""


class Workflow(BaseModel):
    title: str
    description: str


class FrictionPattern(BaseModel):
    category: str
    count: int = 0
    description: str = ""
    affected_tools: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class FrictionAnalysis(BaseModel):
    total_friction_sessions: int = 0
    friction_by_category: dict[str, int] = Field(default_factory=dict)
    friction_by_tool: dict[str, float] = Field(default_factory=dict)
    top_friction_patterns: list[FrictionPattern] = Field(default_factory=list)
    narrative: str = ""


class ToolMetric(BaseModel):
    tool: str
    session_count: int = 0
    avg_turns: float = 0.0
    avg_duration_ms: int | None = None
    avg_friction_score: float = 0.0
    success_rate: float = 0.0
    avg_tokens: int = 0
    top_task_types: list[str] = Field(default_factory=list)
    helpfulness_distribution: dict[str, int] = Field(default_factory=dict)


class ToolComparison(BaseModel):
    tools_analyzed: list[str] = Field(default_factory=list)
    sessions_per_tool: dict[str, int] = Field(default_factory=dict)
    tool_metrics: list[ToolMetric] = Field(default_factory=list)
    best_for: dict[str, str] = Field(default_factory=dict)
    narrative: str = ""


class AgentsMdSuggestion(BaseModel):
    """Suggested addition to AGENTS.md, CLAUDE.md, .cursorrules, etc."""
    target_file: str  # "CLAUDE.md" | ".cursorrules" | "AGENTS.md" | "codex.md"
    target_tool: str
    addition: str
    why: str
    section_hint: str = ""


class UsagePattern(BaseModel):
    title: str
    suggestion: str
    detail: str = ""
    copyable_prompt: str | None = None


class ToolRecommendation(BaseModel):
    task_type: str
    recommended_tool: str
    reason: str = ""
    confidence: float = 0.0


class SuggestionsSection(BaseModel):
    agents_md_additions: list[AgentsMdSuggestion] = Field(default_factory=list)
    usage_patterns: list[UsagePattern] = Field(default_factory=list)
    tool_recommendations: list[ToolRecommendation] = Field(default_factory=list)


class TrendAnalysis(BaseModel):
    sessions_per_day: dict[str, int] = Field(default_factory=dict)
    friction_trend: str = "stable"  # improving | stable | worsening
    tool_adoption: dict[str, list[int]] = Field(default_factory=dict)
    productivity_trend: str = "stable"


class FunEnding(BaseModel):
    headline: str = ""
    detail: str = ""


class InsightsReport(BaseModel):
    """The complete insights report, aggregated from all session facets."""

    generated_at: datetime
    range_start: datetime
    range_end: datetime
    total_sessions: int = 0
    total_facets: int = 0

    at_a_glance: AtAGlance = Field(default_factory=AtAGlance)
    project_areas: list[ProjectArea] = Field(default_factory=list)
    interaction_style: InteractionStyle = Field(default_factory=InteractionStyle)
    impressive_workflows: list[Workflow] = Field(default_factory=list)
    friction_analysis: FrictionAnalysis = Field(default_factory=FrictionAnalysis)
    tool_comparison: ToolComparison = Field(default_factory=ToolComparison)
    suggestions: SuggestionsSection = Field(default_factory=SuggestionsSection)
    trends: TrendAnalysis = Field(default_factory=TrendAnalysis)
    fun_ending: FunEnding = Field(default_factory=FunEnding)
