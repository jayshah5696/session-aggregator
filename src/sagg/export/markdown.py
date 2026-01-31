"""Markdown exporter for sessions."""

from __future__ import annotations

from sagg.models import UnifiedSession, TextPart, ToolCallPart, ToolResultPart, FileChangePart


class MarkdownExporter:
    """Export sessions to formatted Markdown."""

    def export_session(self, session: UnifiedSession) -> str:
        """Convert a session to a Markdown string.

        Args:
            session: The unified session object.

        Returns:
            Formatted Markdown string.
        """
        lines = []

        # Header
        lines.append(f"# {session.title or 'Untitled Session'}")
        lines.append(f"**ID**: `{session.id}`")
        lines.append(
            f"**Source**: {session.source.value} | **Project**: {session.project_name or 'Unknown'}"
        )
        lines.append(f"**Date**: {session.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append(
            f"**Stats**: {session.stats.turn_count} turns, {session.stats.message_count} messages, {session.stats.input_tokens + session.stats.output_tokens} tokens"
        )
        lines.append("")
        lines.append("---")
        lines.append("")

        # Conversation
        for turn in session.turns:
            for message in turn.messages:
                role_icon = {"user": "👤", "assistant": "🤖", "system": "⚙️", "tool": "🛠️"}.get(
                    message.role, "❓"
                )

                lines.append(f"### {role_icon} {message.role.title()}")
                lines.append("")

                for part in message.parts:
                    if isinstance(part, TextPart):
                        lines.append(part.content)
                        lines.append("")

                    elif isinstance(part, ToolCallPart):
                        lines.append(f"> **Tool Call**: `{part.tool_name}`")
                        lines.append("```json")
                        lines.append(str(part.input))
                        lines.append("```")
                        lines.append("")

                    elif isinstance(part, ToolResultPart):
                        status = "Error" if part.is_error else "Success"
                        lines.append(f"> **Tool Result** ({status})")
                        if len(part.output) > 1000:
                            lines.append("```")
                            lines.append(part.output[:1000] + "\n... (truncated)")
                            lines.append("```")
                        else:
                            lines.append("```")
                            lines.append(part.output)
                            lines.append("```")
                        lines.append("")

                    elif isinstance(part, FileChangePart):
                        lines.append(f"> **File Modified**: `{part.path}`")
                        if part.diff:
                            lines.append("```diff")
                            lines.append(part.diff)
                            lines.append("```")
                        lines.append("")

                lines.append("---")
                lines.append("")

        return "\n".join(lines)
