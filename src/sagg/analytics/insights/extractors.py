"""V2 feature extractor pipeline for session facet extraction.

Extensible registry of extractors that each take a UnifiedSession and
return a dict of computed attributes. Adding a new signal means writing
one class and appending it to EXTRACTORS.

Re-run `sagg analyze-sessions --force` to recompute all facets with new
extractors — no schema migration needed.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sagg.models import TextPart, ToolCallPart, ToolResultPart

if TYPE_CHECKING:
    from sagg.models import UnifiedSession


# ---------------------------------------------------------------------------
# File extension → language mapping (shared)
# ---------------------------------------------------------------------------

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".md": "markdown",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".toml": "toml",
}

# Read-class and write-class tool names for ratio computation
READ_TOOLS = {"Read", "Grep", "Glob", "Search", "Find", "Ls", "Cat"}
WRITE_TOOLS = {"Edit", "Write", "Bash", "Run", "Execute"}

# Correction keywords for intervention detection
CORRECTION_KEYWORDS = {
    "no", "don't", "dont", "instead", "wrong", "stop", "actually",
    "rather", "not that", "use", "wait", "hold on", "nope", "undo",
    "revert", "try", "should be", "change",
}

# Satisfaction / frustration keywords for outcome detection
SATISFACTION_WORDS = {
    "thanks", "thank you", "perfect", "great", "awesome", "looks good",
    "nice", "wonderful", "excellent", "good job", "well done", "love it",
    "exactly", "that's it", "thats it",
}
FRUSTRATION_WORDS = {
    "wrong", "stop", "no", "ugh", "broken", "doesn't work", "doesnt work",
    "not what i", "that's not", "thats not", "terrible", "useless",
    "you keep", "still wrong", "again",
}

KEYWORD_TO_CATEGORY: dict[str, list[str]] = {
    "bugfix": ["fix", "bug", "error", "broken", "crash", "fail", "issue"],
    "feature": ["add", "create", "implement", "build", "new"],
    "refactor": ["refactor", "clean", "reorganize", "restructure", "rename"],
    "docs": ["document", "readme", "docs", "comment", "spec"],
    "debug": ["debug", "investigate", "why", "trace", "log"],
    "config": ["config", "setup", "install", "deploy", "ci", "yaml"],
    "testing": ["test", "coverage", "assert", "mock"],
}

BACKEND_LANGUAGES = {"python", "go", "rust", "java", "c", "cpp", "csharp", "ruby", "php", "kotlin"}


# ===================================================================
# Base extractor protocol
# ===================================================================


class BaseExtractor:
    """Base for all feature extractors."""

    name: str = ""
    version: str = "1.0"

    def extract(self, session: UnifiedSession) -> dict:
        raise NotImplementedError


# ===================================================================
# 1. ToolCallStatsExtractor
# ===================================================================


class ToolCallStatsExtractor(BaseExtractor):
    name = "tool_call_stats"
    version = "1.0"

    def extract(self, session: UnifiedSession) -> dict:
        calls_by_name: Counter[str] = Counter()
        sequence: list[str] = []

        for turn in session.turns:
            for message in turn.messages:
                for part in message.parts:
                    if isinstance(part, ToolCallPart):
                        calls_by_name[part.tool_name] += 1
                        sequence.append(part.tool_name)

        total = sum(calls_by_name.values())
        unique = len(calls_by_name)

        read_count = sum(calls_by_name.get(t, 0) for t in READ_TOOLS)
        write_count = sum(calls_by_name.get(t, 0) for t in WRITE_TOOLS)

        if write_count > 0:
            rw_ratio: float | None = read_count / write_count
        elif read_count > 0:
            rw_ratio = None  # Infinite — all reads, no writes
        else:
            rw_ratio = None

        return {
            "tool_calls_total": total,
            "tool_calls_by_name": dict(calls_by_name),
            "tool_call_sequence": sequence,
            "unique_tools_used": unique,
            "most_used_tool": calls_by_name.most_common(1)[0][0] if calls_by_name else None,
            "tool_diversity_ratio": unique / total if total > 0 else 0.0,
            "read_write_ratio": rw_ratio,
        }


# ===================================================================
# 2. ErrorAnalysisExtractor
# ===================================================================


class ErrorAnalysisExtractor(BaseExtractor):
    name = "error_analysis"
    version = "1.0"

    def extract(self, session: UnifiedSession) -> dict:
        # Build tool_id → tool_name map, and ordered list of results
        tool_id_to_name: dict[str, str] = {}
        tool_id_to_input: dict[str, str] = {}
        results_ordered: list[dict] = []  # {tool_id, is_error, output, turn_index}

        for turn in session.turns:
            for message in turn.messages:
                for part in message.parts:
                    if isinstance(part, ToolCallPart):
                        tool_id_to_name[part.tool_id] = part.tool_name
                        inp = str(part.input)[:100] if part.input else ""
                        tool_id_to_input[part.tool_id] = inp
                    elif isinstance(part, ToolResultPart):
                        results_ordered.append({
                            "tool_id": part.tool_id,
                            "is_error": part.is_error,
                            "output": part.output,
                            "turn_index": turn.index,
                        })

        total_results = len(results_ordered)
        error_results = [r for r in results_ordered if r["is_error"]]
        total_errors = len(error_results)
        error_rate = total_errors / total_results if total_results > 0 else 0.0

        # Per-tool error counts
        errors_by_tool: Counter[str] = Counter()
        for r in error_results:
            name = tool_id_to_name.get(r["tool_id"], "unknown")
            errors_by_tool[name] += 1

        # Error details (capped at 10)
        error_details = []
        for r in error_results[:10]:
            tid = r["tool_id"]
            tool_name = tool_id_to_name.get(tid, "unknown")
            # Check recovery: same tool succeeds later
            recovered = any(
                r2["tool_id"] != tid
                and tool_id_to_name.get(r2["tool_id"]) == tool_name
                and not r2["is_error"]
                for r2 in results_ordered[results_ordered.index(r) + 1:]
            )
            error_details.append({
                "tool_name": tool_name,
                "tool_id": tid,
                "input_preview": tool_id_to_input.get(tid, ""),
                "error_preview": r["output"][:200] if r["output"] else "",
                "turn_index": r["turn_index"],
                "recovered": recovered,
            })

        # First error turn index
        first_error_turn_index = error_results[0]["turn_index"] if error_results else None

        # Error-free streak
        max_streak = 0
        current_streak = 0
        for r in results_ordered:
            if not r["is_error"]:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0

        # Error clustering
        error_clustering = self._compute_clustering(results_ordered, error_results)

        # Error recovery rate
        if total_errors > 0:
            recovered_count = 0
            errored_tools: set[str] = set()
            for r in error_results:
                tool_name = tool_id_to_name.get(r["tool_id"], "unknown")
                errored_tools.add(tool_name)

            for tool_name in errored_tools:
                # Check if this tool was called successfully after erroring
                tool_errored = False
                tool_recovered = False
                for r in results_ordered:
                    rname = tool_id_to_name.get(r["tool_id"], "unknown")
                    if rname == tool_name:
                        if r["is_error"]:
                            tool_errored = True
                        elif tool_errored:
                            tool_recovered = True
                            break

                if tool_recovered:
                    recovered_count += 1

            recovery_rate: float | None = recovered_count / len(errored_tools)
        else:
            recovery_rate = None

        return {
            "tool_results_total": total_results,
            "tool_errors_total": total_errors,
            "error_rate": round(error_rate, 4),
            "errors_by_tool": dict(errors_by_tool),
            "error_details": error_details,
            "first_error_turn_index": first_error_turn_index,
            "error_free_streak_max": max_streak,
            "error_clustering": error_clustering,
            "error_recovery_rate": round(recovery_rate, 4) if recovery_rate is not None else None,
        }

    @staticmethod
    def _compute_clustering(
        results_ordered: list[dict],
        error_results: list[dict],
    ) -> str:
        if not error_results or not results_ordered:
            return "none"

        total = len(results_ordered)
        if total < 4:
            return "scattered"

        # Find positions of errors
        error_positions: list[int] = []
        for i, r in enumerate(results_ordered):
            if r["is_error"]:
                error_positions.append(i)

        avg_pos = sum(error_positions) / len(error_positions)
        relative = avg_pos / total

        if relative < 0.33:
            return "early"
        elif relative > 0.66:
            return "late"
        elif max(error_positions) - min(error_positions) > total * 0.5:
            return "scattered"
        else:
            return "middle"


# ===================================================================
# 3. InterventionExtractor
# ===================================================================


class InterventionExtractor(BaseExtractor):
    name = "intervention"
    version = "1.0"

    def extract(self, session: UnifiedSession) -> dict:
        interventions: list[dict] = []
        user_msg_count = 0
        post_error_count = 0
        proactive_count = 0

        # Flatten all messages across turns, tracking turn index
        flat_messages: list[tuple[int, object]] = []  # (turn_index, Message)
        for turn in session.turns:
            for message in turn.messages:
                flat_messages.append((turn.index, message))

        # Walk through messages looking for intervention patterns
        last_had_error = False
        last_assistant_tool: str | None = None
        saw_assistant = False

        for i, (turn_idx, msg) in enumerate(flat_messages):
            if msg.role == "assistant":
                saw_assistant = True
                # Track last tool used by assistant
                for part in msg.parts:
                    if isinstance(part, ToolCallPart):
                        last_assistant_tool = part.tool_name

            elif msg.role == "tool":
                for part in msg.parts:
                    if isinstance(part, ToolResultPart) and part.is_error:
                        last_had_error = True

            elif msg.role == "user":
                user_msg_count += 1
                if not saw_assistant:
                    # First user message — not an intervention
                    last_had_error = False
                    continue

                text = self._get_text(msg).lower().strip()
                is_short = len(text) < 100
                has_correction_word = any(kw in text for kw in CORRECTION_KEYWORDS)

                is_intervention = False
                trigger = "proactive"

                if last_had_error and is_short:
                    is_intervention = True
                    trigger = "post_error"
                    post_error_count += 1
                elif is_short and has_correction_word:
                    is_intervention = True
                    trigger = "rejection"
                    proactive_count += 1

                if is_intervention:
                    # Find the next tool used after this message
                    following_tool = None
                    for j in range(i + 1, len(flat_messages)):
                        _, next_msg = flat_messages[j]
                        if next_msg.role == "assistant":
                            for part in next_msg.parts:
                                if isinstance(part, ToolCallPart):
                                    following_tool = part.tool_name
                                    break
                            if following_tool:
                                break

                    interventions.append({
                        "turn_index": turn_idx,
                        "user_text": self._get_text(msg),
                        "trigger": trigger,
                        "preceding_tool": last_assistant_tool,
                        "following_tool": following_tool,
                    })

                last_had_error = False

        rate = len(interventions) / user_msg_count if user_msg_count > 0 else 0.0

        return {
            "intervention_count": len(interventions),
            "intervention_details": interventions[:10],
            "intervention_rate": round(rate, 4),
            "post_error_interventions": post_error_count,
            "proactive_redirections": proactive_count,
        }

    @staticmethod
    def _get_text(msg) -> str:
        parts_text = []
        for part in msg.parts:
            if isinstance(part, TextPart):
                parts_text.append(part.content)
        return " ".join(parts_text)


# ===================================================================
# 4. TimingExtractor
# ===================================================================


class TimingExtractor(BaseExtractor):
    name = "timing"
    version = "1.0"

    def extract(self, session: UnifiedSession) -> dict:
        # Session duration
        session_duration_ms = session.duration_ms

        if session_duration_ms is None and session.turns:
            first_turn = session.turns[0]
            last_turn = session.turns[-1]
            if first_turn.started_at and last_turn.ended_at:
                delta = last_turn.ended_at - first_turn.started_at
                session_duration_ms = int(delta.total_seconds() * 1000)

        # Turn durations
        turn_durations_ms: list[int] = []
        for turn in session.turns:
            if turn.started_at and turn.ended_at:
                delta = turn.ended_at - turn.started_at
                turn_durations_ms.append(int(delta.total_seconds() * 1000))

        avg_turn = (
            sum(turn_durations_ms) / len(turn_durations_ms)
            if turn_durations_ms
            else None
        )
        max_turn = max(turn_durations_ms) if turn_durations_ms else None

        # Time to first tool call and first error
        first_msg_ts: datetime | None = None
        first_tool_call_ts: datetime | None = None
        first_error_ts: datetime | None = None

        for turn in session.turns:
            for message in turn.messages:
                if first_msg_ts is None:
                    first_msg_ts = message.timestamp

                for part in message.parts:
                    if isinstance(part, ToolCallPart) and first_tool_call_ts is None:
                        first_tool_call_ts = message.timestamp
                    if isinstance(part, ToolResultPart) and part.is_error and first_error_ts is None:
                        first_error_ts = message.timestamp

        time_to_first_tool = None
        if first_msg_ts and first_tool_call_ts:
            delta = first_tool_call_ts - first_msg_ts
            time_to_first_tool = delta.total_seconds() * 1000

        time_to_first_error = None
        if first_msg_ts and first_error_ts:
            delta = first_error_ts - first_msg_ts
            time_to_first_error = delta.total_seconds() * 1000

        # Active time ratio
        active_time_ratio = None
        if session_duration_ms and session_duration_ms > 0 and turn_durations_ms:
            total_turn_time = sum(turn_durations_ms)
            active_time_ratio = round(total_turn_time / session_duration_ms, 4)

        return {
            "session_duration_ms": session_duration_ms,
            "avg_turn_duration_ms": round(avg_turn, 2) if avg_turn is not None else None,
            "max_turn_duration_ms": max_turn,
            "time_to_first_tool_call_ms": round(time_to_first_tool, 2) if time_to_first_tool is not None else None,
            "time_to_first_error_ms": round(time_to_first_error, 2) if time_to_first_error is not None else None,
            "active_time_ratio": active_time_ratio,
        }


# ===================================================================
# 5. FilePatternExtractor
# ===================================================================


class FilePatternExtractor(BaseExtractor):
    name = "file_patterns"
    version = "1.0"

    def extract(self, session: UnifiedSession) -> dict:
        files_modified = list(session.stats.files_modified)
        files_read: list[str] = []

        # Extract files read from tool call inputs (Read, Grep, Glob)
        for turn in session.turns:
            for message in turn.messages:
                for part in message.parts:
                    if isinstance(part, ToolCallPart) and part.tool_name in ("Read", "Grep", "Glob"):
                        if isinstance(part.input, dict):
                            fp = part.input.get("filePath") or part.input.get("path") or part.input.get("file")
                            if fp and isinstance(fp, str):
                                files_read.append(fp)
                    # Also detect Write/Edit targets as modified
                    if isinstance(part, ToolCallPart) and part.tool_name in ("Edit", "Write"):
                        if isinstance(part.input, dict):
                            fp = part.input.get("filePath") or part.input.get("path") or part.input.get("file")
                            if fp and isinstance(fp, str) and fp not in files_modified:
                                files_modified.append(fp)

        files_read_only = [f for f in files_read if f not in files_modified]
        all_files = set(files_modified) | set(files_read)

        # Language detection
        lang_counts: Counter[str] = Counter()
        for filepath in all_files:
            dot_idx = filepath.rfind(".")
            if dot_idx >= 0:
                ext = filepath[dot_idx:].lower()
                lang = EXTENSION_TO_LANGUAGE.get(ext)
                if lang:
                    lang_counts[lang] += 1

        primary_language = lang_counts.most_common(1)[0][0] if lang_counts else None

        # File pattern classification
        has_test = any("test" in f.lower() for f in all_files)
        has_config = any(
            f.endswith((".yml", ".yaml", ".toml", ".json", ".env"))
            for f in all_files
        )
        has_docs = any(f.endswith((".md", ".rst", ".txt")) for f in all_files)

        if not all_files:
            files_pattern = None
        elif has_docs and not has_test and not has_config:
            files_pattern = "docs"
        elif has_config and len(all_files) <= 3:
            files_pattern = "config"
        elif has_test:
            files_pattern = f"{primary_language}_testing" if primary_language else "testing"
        elif primary_language:
            if primary_language in BACKEND_LANGUAGES:
                files_pattern = f"{primary_language}_backend"
            else:
                files_pattern = f"{primary_language}_frontend"
        else:
            files_pattern = "mixed"

        # Scope detection
        if not files_modified:
            scope = None
        elif len(files_modified) == 1:
            scope = "single_file"
        else:
            dirs = set()
            for f in files_modified:
                slash = f.rfind("/")
                if slash >= 0:
                    dirs.add(f[:slash])
                else:
                    dirs.add(".")
            if len(dirs) <= 1:
                scope = "single_dir"
            else:
                scope = "multi_dir"

        return {
            "files_modified": files_modified,
            "files_read": files_read,
            "files_read_only": files_read_only,
            "file_count_modified": len(files_modified),
            "file_count_read": len(files_read),
            "languages_touched": dict(lang_counts),
            "primary_language": primary_language,
            "files_pattern": files_pattern,
            "test_files_touched": has_test,
            "config_files_touched": has_config,
            "scope": scope,
        }


# ===================================================================
# 6. TokenUsageExtractor
# ===================================================================


class TokenUsageExtractor(BaseExtractor):
    name = "token_usage"
    version = "1.0"

    def extract(self, session: UnifiedSession) -> dict:
        total_input = 0
        total_output = 0
        total_cached = 0
        model_counts: Counter[str] = Counter()

        for turn in session.turns:
            for message in turn.messages:
                if message.usage:
                    total_input += message.usage.input_tokens
                    total_output += message.usage.output_tokens
                    if message.usage.cached_tokens:
                        total_cached += message.usage.cached_tokens
                if message.model:
                    model_counts[message.model] += 1

        total_tokens = total_input + total_output
        turn_count = len(session.turns)

        # Also check session-level stats if per-message is zero
        if total_input == 0 and session.stats.input_tokens > 0:
            total_input = session.stats.input_tokens
        if total_output == 0 and session.stats.output_tokens > 0:
            total_output = session.stats.output_tokens
        if total_input + total_output > total_tokens:
            total_tokens = total_input + total_output

        models_used = sorted(model_counts.keys())
        primary_model = model_counts.most_common(1)[0][0] if model_counts else None

        return {
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_tokens,
            "cached_tokens": total_cached,
            "cache_hit_ratio": round(total_cached / total_input, 4) if total_input > 0 else 0.0,
            "tokens_per_turn": round(total_tokens / turn_count, 2) if turn_count > 0 else 0.0,
            "models_used": models_used,
            "primary_model": primary_model,
            "cost_estimate_usd": None,  # Future: add pricing data
        }


# ===================================================================
# 7. ConversationFlowExtractor
# ===================================================================


class ConversationFlowExtractor(BaseExtractor):
    name = "conversation_flow"
    version = "1.0"

    def extract(self, session: UnifiedSession) -> dict:
        user_lengths: list[int] = []
        assistant_lengths: list[int] = []
        back_and_forth = 0
        saw_assistant = False

        for turn in session.turns:
            for message in turn.messages:
                text = self._get_text(message)
                if message.role == "user":
                    user_lengths.append(len(text))
                    if saw_assistant and len(text.strip()) < 50:
                        back_and_forth += 1
                elif message.role == "assistant":
                    saw_assistant = True
                    assistant_lengths.append(len(text))

        user_count = len(user_lengths)
        assistant_count = len(assistant_lengths)
        turn_count = len(session.turns)

        avg_user_len = sum(user_lengths) / user_count if user_count > 0 else 0.0
        avg_assistant_len = sum(assistant_lengths) / assistant_count if assistant_count > 0 else 0.0
        max_user_len = max(user_lengths) if user_lengths else 0
        first_user_len = user_lengths[0] if user_lengths else 0

        # Conversation pattern classification
        pattern = self._classify_pattern(
            turn_count, user_lengths, avg_user_len, first_user_len
        )

        return {
            "user_messages_count": user_count,
            "assistant_messages_count": assistant_count,
            "avg_user_message_length": round(avg_user_len, 2),
            "avg_assistant_message_length": round(avg_assistant_len, 2),
            "max_user_message_length": max_user_len,
            "user_message_lengths": user_lengths,
            "turn_count": turn_count,
            "back_and_forth_count": back_and_forth,
            "conversation_pattern": pattern,
            "first_user_message_length": first_user_len,
        }

    @staticmethod
    def _classify_pattern(
        turn_count: int,
        user_lengths: list[int],
        avg_user_len: float,
        first_user_len: int,
    ) -> str:
        # Detailed briefing: long first message, few follow-ups (check before single_shot)
        if first_user_len > 200 and turn_count <= 5:
            return "detailed_briefing"

        if turn_count <= 2:
            return "single_shot"

        # Iterative: many turns with short messages
        if turn_count >= 6 and avg_user_len < 80:
            return "iterative"

        # Evolving: messages get longer over time
        if len(user_lengths) >= 4:
            first_half = user_lengths[: len(user_lengths) // 2]
            second_half = user_lengths[len(user_lengths) // 2 :]
            avg_first = sum(first_half) / len(first_half) if first_half else 0
            avg_second = sum(second_half) / len(second_half) if second_half else 0
            if avg_second > avg_first * 1.5:
                return "evolving"

        if turn_count >= 6:
            return "iterative"

        return "single_shot"

    @staticmethod
    def _get_text(msg) -> str:
        parts_text = []
        for part in msg.parts:
            if isinstance(part, TextPart):
                parts_text.append(part.content)
        return " ".join(parts_text)


# ===================================================================
# 8. OutcomeSignalsExtractor
# ===================================================================


class OutcomeSignalsExtractor(BaseExtractor):
    name = "outcome_signals"
    version = "1.0"

    def extract(self, session: UnifiedSession) -> dict:
        turn_count = len(session.turns)
        signals: list[str] = []

        # Basic checks
        if turn_count == 0:
            return {
                "outcome": "abandoned",
                "completion_confidence": 0.7,
                "outcome_signals": ["no_turns"],
                "last_message_role": None,
                "session_ended_cleanly": False,
                "had_late_errors": False,
                "user_expressed_satisfaction": None,
                "user_expressed_frustration": None,
            }

        if turn_count <= 1:
            signals.append("single_turn")
            return {
                "outcome": "abandoned",
                "completion_confidence": 0.7,
                "outcome_signals": signals,
                "last_message_role": self._last_role(session),
                "session_ended_cleanly": False,
                "had_late_errors": False,
                "user_expressed_satisfaction": None,
                "user_expressed_frustration": None,
            }

        # Check last few user messages for satisfaction/frustration
        satisfaction = False
        frustration = False
        last_user_texts = self._last_n_user_texts(session, 3)
        for text in last_user_texts:
            lower = text.lower()
            if any(w in lower for w in SATISFACTION_WORDS):
                satisfaction = True
            if any(w in lower for w in FRUSTRATION_WORDS):
                frustration = True

        # Last message role
        last_role = self._last_role(session)
        ended_cleanly = last_role == "assistant"

        # Late errors (in final 20% of tool results)
        had_late_errors = self._check_late_errors(session)

        # Error rate and intervention signals (lightweight re-check)
        error_rate = self._quick_error_rate(session)
        intervention_rate = self._quick_intervention_rate(session)

        # Determine outcome
        if satisfaction:
            outcome = "fully_achieved"
            confidence = 0.8
            signals.append("user_satisfaction_detected")
        elif frustration:
            outcome = "partially_achieved"
            confidence = 0.7
            signals.append("user_frustration_detected")
        elif ended_cleanly and not had_late_errors and error_rate < 0.2:
            outcome = "fully_achieved"
            confidence = 0.6 + min(turn_count / 20.0, 0.3)
            signals.append("clean_ending")
            signals.append("low_error_rate")
        elif error_rate > 0.4 or intervention_rate > 0.3:
            outcome = "partially_achieved"
            confidence = 0.5
            if error_rate > 0.4:
                signals.append("high_error_rate")
            if intervention_rate > 0.3:
                signals.append("high_intervention_rate")
        else:
            outcome = "unclear"
            confidence = 0.3
            signals.append("insufficient_signals")

        return {
            "outcome": outcome,
            "completion_confidence": round(confidence, 2),
            "outcome_signals": signals,
            "last_message_role": last_role,
            "session_ended_cleanly": ended_cleanly,
            "had_late_errors": had_late_errors,
            "user_expressed_satisfaction": satisfaction if satisfaction else None,
            "user_expressed_frustration": frustration if frustration else None,
        }

    @staticmethod
    def _last_role(session: UnifiedSession) -> str | None:
        for turn in reversed(session.turns):
            for msg in reversed(turn.messages):
                return msg.role
        return None

    @staticmethod
    def _last_n_user_texts(session: UnifiedSession, n: int) -> list[str]:
        texts = []
        for turn in reversed(session.turns):
            for msg in reversed(turn.messages):
                if msg.role == "user":
                    text_parts = [p.content for p in msg.parts if isinstance(p, TextPart)]
                    if text_parts:
                        texts.append(" ".join(text_parts))
                    if len(texts) >= n:
                        return texts
        return texts

    @staticmethod
    def _check_late_errors(session: UnifiedSession) -> bool:
        all_results: list[bool] = []
        for turn in session.turns:
            for msg in turn.messages:
                for part in msg.parts:
                    if isinstance(part, ToolResultPart):
                        all_results.append(part.is_error)

        if not all_results:
            return False

        cutoff = max(1, int(len(all_results) * 0.8))
        late_results = all_results[cutoff:]
        return any(late_results)

    @staticmethod
    def _quick_error_rate(session: UnifiedSession) -> float:
        total = 0
        errors = 0
        for turn in session.turns:
            for msg in turn.messages:
                for part in msg.parts:
                    if isinstance(part, ToolResultPart):
                        total += 1
                        if part.is_error:
                            errors += 1
        return errors / total if total > 0 else 0.0

    @staticmethod
    def _quick_intervention_rate(session: UnifiedSession) -> float:
        user_count = 0
        interventions = 0
        saw_assistant = False
        for turn in session.turns:
            for msg in turn.messages:
                if msg.role == "assistant":
                    saw_assistant = True
                elif msg.role == "user":
                    user_count += 1
                    if saw_assistant:
                        text = " ".join(
                            p.content for p in msg.parts if isinstance(p, TextPart)
                        ).lower()
                        if len(text) < 100 and any(kw in text for kw in CORRECTION_KEYWORDS):
                            interventions += 1
        return interventions / user_count if user_count > 0 else 0.0


# ===================================================================
# 9. GoalClassificationExtractor
# ===================================================================


class GoalClassificationExtractor(BaseExtractor):
    name = "goal_classification"
    version = "1.0"

    def extract(self, session: UnifiedSession) -> dict:
        goal = self._extract_goal(session)
        all_user_texts = self._all_user_texts(session)

        # Goal categories from ALL user messages
        categories: dict[str, int] = {}
        for text in all_user_texts:
            lower = text.lower()
            for category, keywords in KEYWORD_TO_CATEGORY.items():
                for keyword in keywords:
                    if keyword in lower:
                        categories[category] = categories.get(category, 0) + 1
                        break

        if not categories:
            categories["general"] = 1

        # Task type from first message
        task_type = self._classify_task_type(session, goal)

        # Session type from turn count
        turn_count = len(session.turns)
        if turn_count <= 2:
            session_type = "quick_question"
        elif turn_count <= 5:
            session_type = "single_task"
        elif turn_count <= 15:
            session_type = "multi_task"
        else:
            session_type = "iterative_refinement"

        # Goal evolution: check if new categories appear in later messages
        first_msg_cats = set()
        if all_user_texts:
            first_lower = all_user_texts[0].lower()
            for category, keywords in KEYWORD_TO_CATEGORY.items():
                for keyword in keywords:
                    if keyword in first_lower:
                        first_msg_cats.add(category)
                        break

        later_cats = set(categories.keys()) - first_msg_cats - {"general"}
        goal_evolution = len(later_cats) > 0 and len(all_user_texts) > 1

        multi_goal = len([c for c in categories if c != "general"]) > 1

        return {
            "underlying_goal": goal,
            "goal_categories": categories,
            "task_type": task_type,
            "session_type": session_type,
            "goal_evolution": goal_evolution,
            "multi_goal": multi_goal,
        }

    @staticmethod
    def _extract_goal(session: UnifiedSession) -> str:
        for turn in session.turns:
            for message in turn.messages:
                if message.role == "user":
                    for part in message.parts:
                        if isinstance(part, TextPart) and part.content.strip():
                            text = part.content.strip()
                            if len(text) > 200:
                                return text[:200] + "..."
                            return text
        return session.title or "Unknown goal"

    @staticmethod
    def _all_user_texts(session: UnifiedSession) -> list[str]:
        texts = []
        for turn in session.turns:
            for message in turn.messages:
                if message.role == "user":
                    parts = [
                        p.content for p in message.parts if isinstance(p, TextPart)
                    ]
                    if parts:
                        texts.append(" ".join(parts))
        return texts

    @staticmethod
    def _classify_task_type(session: UnifiedSession, goal: str) -> str:
        lower = goal.lower()

        # Check keywords (debug before bugfix since "bug" is substring of "debug")
        if any(w in lower for w in ["debug", "investigate"]):
            return "debug"
        if any(w in lower for w in ["fix", "bug", "error", "broken"]):
            return "bugfix"
        if any(w in lower for w in ["refactor", "clean", "reorganize"]):
            return "refactor"
        if any(w in lower for w in ["doc", "readme", "spec", "comment"]):
            return "docs"
        if any(w in lower for w in ["config", "setup", "install", "deploy"]):
            return "config"
        if any(w in lower for w in ["test", "coverage"]):
            return "feature"

        # Infer from tool usage
        tool_counts = session.get_tool_counts()
        read_heavy = sum(tool_counts.get(t, 0) for t in READ_TOOLS)
        write_heavy = sum(tool_counts.get(t, 0) for t in WRITE_TOOLS)

        if read_heavy > write_heavy * 2:
            return "exploration"
        if write_heavy > 0:
            return "feature"

        return "exploration"


# ===================================================================
# 10. ComplexityExtractor
# ===================================================================


class ComplexityExtractor(BaseExtractor):
    name = "complexity"
    version = "1.0"

    def extract(self, session: UnifiedSession) -> dict:
        turn_count = len(session.turns)
        tool_count = session.stats.tool_call_count
        file_count = len(session.stats.files_modified)

        # Count unique tools and errors for v2 scoring
        unique_tools = len(session.get_tool_counts())
        error_count = 0
        intervention_count = 0
        saw_assistant = False

        for turn in session.turns:
            for msg in turn.messages:
                if msg.role == "assistant":
                    saw_assistant = True
                elif msg.role == "user" and saw_assistant:
                    text = " ".join(
                        p.content for p in msg.parts if isinstance(p, TextPart)
                    ).lower()
                    if len(text) < 100 and any(kw in text for kw in CORRECTION_KEYWORDS):
                        intervention_count += 1
                for part in msg.parts:
                    if isinstance(part, ToolResultPart) and part.is_error:
                        error_count += 1

        total_results = sum(
            1 for turn in session.turns
            for msg in turn.messages
            for part in msg.parts
            if isinstance(part, ToolResultPart)
        )
        error_rate = error_count / total_results if total_results > 0 else 0.0

        factors: dict[str, int] = {}
        score = 1

        if turn_count > 5:
            score += 1
            factors["turns_gt5"] = 1
        if turn_count > 15:
            score += 1
            factors["turns_gt15"] = 1
        if tool_count > 20 or unique_tools > 5:
            score += 1
            factors["tools"] = 1
        if file_count > 5:
            score += 1
            factors["files"] = 1
        if error_rate > 0.3 or intervention_count > 3:
            score += 1
            factors["errors_or_interventions"] = 1

        score = min(score, 5)

        # Brief summary
        summary = self._make_summary(session)

        return {
            "complexity_score": score,
            "complexity_factors": factors,
            "brief_summary": summary,
        }

    @staticmethod
    def _make_summary(session: UnifiedSession) -> str:
        # Goal text
        goal = ""
        for turn in session.turns:
            for msg in turn.messages:
                if msg.role == "user":
                    for part in msg.parts:
                        if isinstance(part, TextPart) and part.content.strip():
                            goal = part.content.strip()[:100]
                            break
                    if goal:
                        break
            if goal:
                break

        if session.title and session.title != goal:
            base = session.title
        elif goal:
            base = goal + ("..." if len(goal) >= 100 else "")
        else:
            base = "Unknown"

        stats_parts = []
        if session.stats.turn_count > 0:
            stats_parts.append(f"{session.stats.turn_count} turns")
        if len(session.stats.files_modified) > 0:
            stats_parts.append(f"{len(session.stats.files_modified)} files")
        if session.stats.tool_call_count > 0:
            stats_parts.append(f"{session.stats.tool_call_count} tool calls")

        if stats_parts:
            return f"{base} ({', '.join(stats_parts)})"
        return base


# ===================================================================
# Extractor Registry + Pipeline
# ===================================================================


EXTRACTORS: list[BaseExtractor] = [
    ToolCallStatsExtractor(),
    ErrorAnalysisExtractor(),
    InterventionExtractor(),
    TimingExtractor(),
    FilePatternExtractor(),
    TokenUsageExtractor(),
    ConversationFlowExtractor(),
    OutcomeSignalsExtractor(),
    GoalClassificationExtractor(),
    ComplexityExtractor(),
]


def extract_facet(session: UnifiedSession) -> dict:
    """Run all extractors and merge into a single facet dict.

    The returned dict contains:
    - Identity fields (session_id, source, analyzer_version, etc.)
    - All fields from each extractor
    - Backward-compatible keys for the existing session_facets table
    - extractor_versions tracking which version of each extractor ran
    """
    facet: dict = {
        "session_id": session.id,
        "source": session.source.value,
        "analyzed_at": int(time.time()),
        "analyzer_version": "heuristic_v2",
        "analyzer_model": None,
    }

    for extractor in EXTRACTORS:
        facet.update(extractor.extract(session))

    # Track which version of each extractor ran
    facet["extractor_versions"] = {e.name: e.version for e in EXTRACTORS}

    # Backward compatibility: produce keys expected by session_facets table
    # These are already produced by the extractors, but some need aliasing
    _ensure_backward_compat(facet, session)

    return facet


def _ensure_backward_compat(facet: dict, session: UnifiedSession) -> None:
    """Ensure v1-compatible keys exist in the facet dict.

    The existing session_facets table and store.upsert_facet() expect certain
    keys. Some are produced by extractors under different names. This function
    ensures all required keys are present.
    """
    # Friction fields from error_analysis + intervention
    error_rate = facet.get("error_rate", 0.0)
    intervention_count = facet.get("intervention_count", 0)
    back_and_forth = facet.get("back_and_forth_count", 0)

    # Compute friction_score (reuse v1 weighting)
    from sagg.analytics.friction import calculate_friction_score, analyze_retries
    retries, retry_tools = analyze_retries(session)
    friction_score = calculate_friction_score(retries, error_rate, back_and_forth)

    friction_counts: dict[str, int] = {}
    if retries >= 3:
        friction_counts["wrong_approach"] = retries
    if error_rate >= 0.3:
        friction_counts["tool_error"] = int(error_rate * 100)
    if back_and_forth >= 5:
        friction_counts["user_rejected_action"] = back_and_forth
    if intervention_count >= 2:
        friction_counts["manual_intervention"] = intervention_count

    friction_detail = None
    if friction_counts:
        parts = []
        if "wrong_approach" in friction_counts:
            parts.append(f"{retries} sequential retries")
        if "tool_error" in friction_counts:
            parts.append(f"{int(error_rate * 100)}% error rate")
        if "user_rejected_action" in friction_counts:
            parts.append(f"{back_and_forth} short corrections")
        if "manual_intervention" in friction_counts:
            parts.append(f"{intervention_count} manual interventions")
        friction_detail = "; ".join(parts)

    facet["friction_counts"] = friction_counts
    facet["friction_detail"] = friction_detail
    facet["friction_score"] = round(friction_score, 3)

    # Tool effectiveness
    tool_counts = session.get_tool_counts()
    facet["tools_that_helped"] = [
        t for t, c in sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    ]
    facet["tools_that_didnt"] = [
        d["tool_name"] for d in facet.get("error_details", [])[:3]
    ]

    # Helpfulness from friction
    if friction_score < 0.2:
        facet["tool_helpfulness"] = "very"
    elif friction_score < 0.4:
        facet["tool_helpfulness"] = "moderately"
    elif friction_score < 0.6:
        facet["tool_helpfulness"] = "slightly"
    else:
        facet["tool_helpfulness"] = "unhelpful"

    # key_decisions — empty for heuristic, LLM fills these
    if "key_decisions" not in facet:
        facet["key_decisions"] = []
