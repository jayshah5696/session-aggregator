"""LLM analysis backend using CLI tools (claude -p, codex, gemini).

Instead of adding SDK dependencies, this module shells out to whichever
AI CLI tool the user already has installed. This is natural for sagg
since the user already has these tools (that's why they use sagg).
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagg.models import UnifiedSession

# CLI backends in detection order
BACKENDS = [
    {
        "name": "claude",
        "check_cmd": ["claude", "--version"],
        "run_cmd": ["claude", "-p"],
        "stdin_mode": True,
    },
    {
        "name": "codex",
        "check_cmd": ["codex", "--version"],
        "run_cmd": ["codex", "--quiet"],
        "stdin_mode": False,
    },
    {
        "name": "gemini",
        "check_cmd": ["gemini", "--version"],
        "run_cmd": ["gemini"],
        "stdin_mode": True,
    },
]

FACET_PROMPT_TEMPLATE = """Analyze this AI coding session and return ONLY valid JSON (no markdown fencing).

Session Info:
- Tool: {source}
- Project: {project_name}
- Turns: {turn_count}
- Files Modified: {file_count}

Transcript (condensed):
{transcript}

Return JSON with these exact fields:
{{
  "underlying_goal": "what the user was trying to accomplish",
  "goal_categories": {{"category_name": 1}},
  "task_type": "one of: bugfix, feature, refactor, docs, debug, config, exploration",
  "outcome": "one of: fully_achieved, partially_achieved, abandoned, unclear",
  "completion_confidence": 0.7,
  "session_type": "one of: quick_question, single_task, multi_task, iterative_refinement",
  "complexity_score": 3,
  "friction_counts": {{"friction_type": count}},
  "friction_detail": "description or null",
  "tool_helpfulness": "one of: unhelpful, slightly, moderately, very, extremely",
  "primary_language": "python or null",
  "files_pattern": "pattern or null",
  "brief_summary": "1-2 sentence summary",
  "key_decisions": ["decision1", "decision2"]
}}

friction_counts keys can be: wrong_approach, user_rejected_action, data_quality, incomplete_response, tool_error, context_loss, performance_issue
"""


def detect_available_backend() -> str | None:
    """Find the first available CLI tool.

    Returns:
        Backend name ('claude', 'codex', 'gemini') or None.
    """
    for backend in BACKENDS:
        try:
            subprocess.run(
                backend["check_cmd"],
                capture_output=True,
                timeout=10,
            )
            return backend["name"]
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    return None


def run_llm_prompt(prompt: str, backend_name: str | None = None) -> str:
    """Send a prompt to a CLI LLM tool and return the response.

    Args:
        prompt: The prompt text.
        backend_name: Which CLI to use. Auto-detects if None.

    Returns:
        The LLM's response text.

    Raises:
        RuntimeError: If no backend is available or the command fails.
    """
    if backend_name is None:
        backend_name = detect_available_backend()

    if backend_name is None:
        msg = "No LLM CLI tool found. Install claude, codex, or gemini CLI."
        raise RuntimeError(msg)

    backend = next((b for b in BACKENDS if b["name"] == backend_name), None)
    if backend is None:
        msg = f"Unknown backend: {backend_name}"
        raise RuntimeError(msg)

    try:
        if backend["stdin_mode"]:
            result = subprocess.run(
                backend["run_cmd"],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=120,
            )
        else:
            result = subprocess.run(
                backend["run_cmd"] + [prompt],
                capture_output=True,
                text=True,
                timeout=120,
            )
    except subprocess.TimeoutExpired:
        msg = f"LLM call timed out after 120s ({backend_name})"
        raise RuntimeError(msg)
    except FileNotFoundError:
        msg = f"CLI tool not found: {backend_name}"
        raise RuntimeError(msg)

    if result.returncode != 0:
        msg = f"LLM call failed ({backend_name}): {result.stderr[:200]}"
        raise RuntimeError(msg)

    return result.stdout.strip()


def condense_transcript(session: UnifiedSession, max_chars: int = 8000) -> str:
    """Reduce a session transcript for LLM analysis.

    Keeps all user messages, truncates assistant responses, keeps tool
    names but drops tool inputs/outputs.

    Args:
        session: Session to condense.
        max_chars: Maximum character budget.

    Returns:
        Condensed transcript string.
    """
    from sagg.models import TextPart, ToolCallPart, ToolResultPart

    lines: list[str] = []
    char_count = 0

    for turn in session.turns:
        for message in turn.messages:
            if char_count >= max_chars:
                break

            if message.role == "user":
                for part in message.parts:
                    if isinstance(part, TextPart) and part.content.strip():
                        line = f"USER: {part.content.strip()}"
                        lines.append(line)
                        char_count += len(line)

            elif message.role == "assistant":
                for part in message.parts:
                    if isinstance(part, TextPart) and part.content.strip():
                        text = part.content.strip()[:200]
                        line = f"ASSISTANT: {text}..."
                        lines.append(line)
                        char_count += len(line)
                    elif isinstance(part, ToolCallPart):
                        line = f"TOOL_CALL: {part.tool_name}"
                        lines.append(line)
                        char_count += len(line)
                    elif isinstance(part, ToolResultPart):
                        status = "ERROR" if part.is_error else "OK"
                        line = f"TOOL_RESULT: {status}"
                        lines.append(line)
                        char_count += len(line)

    return "\n".join(lines)


def analyze_session_llm(
    session: UnifiedSession,
    backend_name: str | None = None,
) -> dict:
    """Analyze a session using an LLM via CLI tool.

    Args:
        session: Session to analyze.
        backend_name: Which CLI to use. Auto-detects if None.

    Returns:
        Dictionary matching the session_facets schema.
    """
    import time

    transcript = condense_transcript(session)

    prompt = FACET_PROMPT_TEMPLATE.format(
        source=session.source.value,
        project_name=session.project_name or "unknown",
        turn_count=len(session.turns),
        file_count=len(session.stats.files_modified),
        transcript=transcript,
    )

    if backend_name is None:
        backend_name = detect_available_backend()

    response = run_llm_prompt(prompt, backend_name)

    # Parse JSON from response (handle potential markdown fencing)
    json_text = response
    if "```json" in json_text:
        json_text = json_text.split("```json")[1].split("```")[0]
    elif "```" in json_text:
        json_text = json_text.split("```")[1].split("```")[0]

    try:
        parsed = json.loads(json_text.strip())
    except json.JSONDecodeError:
        # Fallback: return minimal facet
        from sagg.analytics.insights.heuristic import analyze_session
        return analyze_session(session)

    # Merge LLM output with session metadata
    return {
        "session_id": session.id,
        "source": session.source.value,
        "analyzed_at": int(time.time()),
        "analyzer_version": "llm_v1",
        "analyzer_model": backend_name,
        "underlying_goal": parsed.get("underlying_goal", ""),
        "goal_categories": parsed.get("goal_categories", {}),
        "task_type": parsed.get("task_type", "exploration"),
        "outcome": parsed.get("outcome", "unclear"),
        "completion_confidence": parsed.get("completion_confidence", 0.5),
        "session_type": parsed.get("session_type", "single_task"),
        "complexity_score": parsed.get("complexity_score", 3),
        "friction_counts": parsed.get("friction_counts", {}),
        "friction_detail": parsed.get("friction_detail"),
        "friction_score": 0.0,  # Will be computed from friction.py
        "tools_that_helped": [],
        "tools_that_didnt": [],
        "tool_helpfulness": parsed.get("tool_helpfulness", "moderately"),
        "primary_language": parsed.get("primary_language"),
        "files_pattern": parsed.get("files_pattern"),
        "brief_summary": parsed.get("brief_summary", ""),
        "key_decisions": parsed.get("key_decisions", []),
    }
