"""Command-line interface for session-aggregator."""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from sagg.adapters import registry
from sagg.models import TextPart, ToolCallPart, ToolResultPart
from sagg.storage import SessionStore

if TYPE_CHECKING:
    from sagg.models import UnifiedSession

console = Console()
error_console = Console(stderr=True)


def parse_duration(s: str) -> timedelta:
    """Parse duration string like '7d', '2w', '1h' to timedelta.

    Supported units:
        h - hours
        d - days
        w - weeks

    Args:
        s: Duration string (e.g., '7d', '2w', '24h')

    Returns:
        timedelta object representing the duration.

    Raises:
        ValueError: If the duration string format is invalid.
    """
    match = re.match(r"^(\d+)([hdw])$", s.lower())
    if match is None:
        raise ValueError(f"Invalid duration format: '{s}'. Use format like '7d', '2w', or '24h'")

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)
    elif unit == "w":
        return timedelta(weeks=value)
    else:
        raise ValueError(f"Unknown unit: {unit}")


def format_age(dt: datetime) -> str:
    """Format a datetime as a human-readable age string.

    Args:
        dt: The datetime to format.

    Returns:
        Human-readable age like '2h ago', '3d ago', '1w ago'.
    """
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    delta = now - dt
    seconds = delta.total_seconds()

    if seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes}m ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours}h ago"
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f"{days}d ago"
    else:
        weeks = int(seconds / 604800)
        return f"{weeks}w ago"


def truncate_id(session_id: str, length: int = 8) -> str:
    """Truncate a session ID for display.

    Args:
        session_id: The full session ID.
        length: Number of characters to keep.

    Returns:
        Truncated ID with ellipsis.
    """
    if len(session_id) <= length:
        return session_id
    return session_id[:length] + "..."


def print_sessions_table(sessions: list[UnifiedSession]) -> None:
    """Print sessions in a formatted table.

    Args:
        sessions: List of sessions to display.
    """
    if not sessions:
        console.print("[dim]No sessions found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="cyan")
    table.add_column("Source", style="magenta")
    table.add_column("Title", style="white", max_width=40)
    table.add_column("Project", style="green")
    table.add_column("Age", style="yellow")

    for session in sessions:
        table.add_row(
            truncate_id(session.id, 12),
            session.source.value,
            (session.title or "[dim]Untitled[/dim]")[:40],
            session.project_name or "[dim]—[/dim]",
            format_age(session.created_at),
        )

    console.print(table)


def print_session_detail(session: UnifiedSession, as_json: bool = False) -> None:
    """Print detailed session information.

    Args:
        session: Session to display.
        as_json: If True, output as JSON instead of rich formatting.
    """
    if as_json:
        console.print(session.model_dump_json(indent=2))
        return

    # Session header panel
    header_content = f"""[bold]ID:[/bold] {session.id}
[bold]Source:[/bold] {session.source.value}
[bold]Source ID:[/bold] {session.source_id}
[bold]Title:[/bold] {session.title or "[dim]Untitled[/dim]"}
[bold]Project:[/bold] {session.project_name or "[dim]—[/dim]"} ({session.project_path or "[dim]—[/dim]"})
[bold]Created:[/bold] {session.created_at.isoformat()}
[bold]Updated:[/bold] {session.updated_at.isoformat()}
[bold]Duration:[/bold] {session.duration_ms or 0}ms"""

    if session.git:
        header_content += f"""
[bold]Git Branch:[/bold] {session.git.branch or "[dim]—[/dim]"}
[bold]Git Commit:[/bold] {session.git.commit or "[dim]—[/dim]"}"""

    console.print(Panel(header_content, title="Session Details", border_style="blue"))

    # Stats panel
    stats = session.stats
    stats_content = f"""[bold]Turns:[/bold] {stats.turn_count}
[bold]Messages:[/bold] {stats.message_count}
[bold]Input Tokens:[/bold] {stats.input_tokens:,}
[bold]Output Tokens:[/bold] {stats.output_tokens:,}
[bold]Tool Calls:[/bold] {stats.tool_call_count}
[bold]Files Modified:[/bold] {len(stats.files_modified)}"""

    if stats.files_modified:
        stats_content += "\n\n[bold]Modified Files:[/bold]"
        for f in stats.files_modified[:10]:
            stats_content += f"\n  • {f}"
        if len(stats.files_modified) > 10:
            stats_content += f"\n  [dim]... and {len(stats.files_modified) - 10} more[/dim]"

    console.print(Panel(stats_content, title="Statistics", border_style="green"))

    # Models panel
    if session.models:
        models_table = Table(show_header=True, header_style="bold")
        models_table.add_column("Model")
        models_table.add_column("Provider")
        models_table.add_column("Messages", justify="right")
        models_table.add_column("Input Tokens", justify="right")
        models_table.add_column("Output Tokens", justify="right")

        for model in session.models:
            models_table.add_row(
                model.model_id,
                model.provider,
                str(model.message_count),
                f"{model.input_tokens:,}",
                f"{model.output_tokens:,}",
            )

        console.print(Panel(models_table, title="Models Used", border_style="magenta"))

    # Messages (turns)
    if session.turns:
        console.print(Panel("[bold]Conversation[/bold]", border_style="yellow"))

        for turn in session.turns:
            for message in turn.messages:
                role_style = {
                    "user": "bold blue",
                    "assistant": "bold green",
                    "system": "bold yellow",
                    "tool": "bold magenta",
                }.get(message.role, "white")

                console.print(f"\n[{role_style}]{message.role.upper()}[/{role_style}]")

                for part in message.parts:
                    if isinstance(part, TextPart):
                        console.print(part.content)
                    elif isinstance(part, ToolCallPart):
                        console.print(f"[dim]→ Tool Call:[/dim] [cyan]{part.tool_name}[/cyan]")
                        if part.input:
                            if isinstance(part.input, str):
                                console.print(
                                    f"  [dim]{part.input[:200]}...[/dim]"
                                    if len(str(part.input)) > 200
                                    else f"  [dim]{part.input}[/dim]"
                                )
                    elif isinstance(part, ToolResultPart):
                        status = "[red]error[/red]" if part.is_error else "[green]success[/green]"
                        console.print(f"[dim]← Tool Result ({status}):[/dim]")
                        output_preview = (
                            part.output[:500] if len(part.output) > 500 else part.output
                        )
                        console.print(Syntax(output_preview, "text", line_numbers=False))


@click.group()
def cli() -> None:
    """Session Aggregator - Unified AI coding session management."""
    pass


@cli.command()
@click.option("--source", "-s", type=str, help="Collect from specific source only")
@click.option("--since", type=str, help="Only sessions from last N days (e.g., 7d, 2w)")
def collect(source: str | None, since: str | None) -> None:
    """Collect sessions from configured sources."""
    since_dt: datetime | None = None
    if since:
        try:
            delta = parse_duration(since)
            since_dt = datetime.now(timezone.utc) - delta
        except ValueError as e:
            error_console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)

    try:
        store = SessionStore()
    except Exception as e:
        error_console.print(f"[red]Error initializing store:[/red] {e}")
        sys.exit(1)

    try:
        if source:
            try:
                adapter = registry.get_adapter(source)
                adapters = [adapter]
            except KeyError as e:
                error_console.print(f"[red]Error:[/red] {e}")
                sys.exit(1)
        else:
            adapters = registry.get_available_adapters()

        if not adapters:
            console.print("[yellow]No available adapters found.[/yellow]")
            return

        total_collected = 0
        for adapter in adapters:
            if not adapter.is_available():
                console.print(f"[dim]Skipping {adapter.display_name} (not available)[/dim]")
                continue

            console.print(f"[bold]Collecting from {adapter.display_name}...[/bold]")

            try:
                refs = adapter.list_sessions(since=since_dt)
                collected = 0

                for ref in refs:
                    # Check if already imported
                    if store.session_exists(adapter.name, ref.id):
                        continue

                    try:
                        session = adapter.parse_session(ref)
                        store.save_session(session)
                        collected += 1
                    except Exception as e:
                        error_console.print(
                            f"[yellow]Warning: Failed to parse session {ref.id}: {e}[/yellow]"
                        )

                console.print(f"  Collected {collected} new session(s)")
                total_collected += collected

            except Exception as e:
                error_console.print(f"[red]Error collecting from {adapter.display_name}:[/red] {e}")

        console.print(f"\n[bold green]Total: {total_collected} session(s) collected[/bold green]")

    finally:
        store.close()


@cli.command("list")
@click.option("--source", "-s", type=str, help="Filter by source")
@click.option("--project", "-p", type=str, help="Filter by project name")
@click.option("--limit", "-l", type=int, default=20, help="Limit results")
def list_sessions(source: str | None, project: str | None, limit: int) -> None:
    """List recent sessions."""
    try:
        store = SessionStore()
    except Exception as e:
        error_console.print(f"[red]Error initializing store:[/red] {e}")
        sys.exit(1)

    try:
        sessions = store.list_sessions(source=source, project=project, limit=limit)
        print_sessions_table(sessions)
    finally:
        store.close()


@cli.command()
@click.argument("query")
@click.option("--limit", "-l", type=int, default=20, help="Limit results")
def search(query: str, limit: int) -> None:
    """Full-text search across sessions."""
    try:
        store = SessionStore()
    except Exception as e:
        error_console.print(f"[red]Error initializing store:[/red] {e}")
        sys.exit(1)

    try:
        sessions = store.search_sessions(query, limit=limit)
        if sessions:
            console.print(f"[bold]Found {len(sessions)} session(s) matching '{query}':[/bold]\n")
            print_sessions_table(sessions)
        else:
            console.print(f"[dim]No sessions found matching '{query}'[/dim]")
    except Exception as e:
        error_console.print(f"[red]Error searching:[/red] {e}")
        sys.exit(1)
    finally:
        store.close()


@cli.command()
@click.argument("session_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def show(session_id: str, as_json: bool) -> None:
    """Show session details."""
    try:
        store = SessionStore()
    except Exception as e:
        error_console.print(f"[red]Error initializing store:[/red] {e}")
        sys.exit(1)

    try:
        session = store.get_session(session_id)
        if session is None:
            # Try partial ID match
            sessions = store.list_sessions(limit=100)
            matches = [s for s in sessions if s.id.startswith(session_id)]
            if len(matches) == 1:
                session = store.get_session(matches[0].id)
            elif len(matches) > 1:
                error_console.print(
                    f"[red]Error:[/red] Ambiguous session ID. Multiple matches found:"
                )
                for s in matches[:5]:
                    error_console.print(f"  • {s.id}")
                sys.exit(1)

        if session is None:
            error_console.print(f"[red]Error:[/red] Session '{session_id}' not found")
            sys.exit(1)

        print_session_detail(session, as_json=as_json)

    finally:
        store.close()


@cli.command()
@click.argument("session_id", required=False)
@click.option("--all", "export_all", is_flag=True, help="Export all sessions")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option(
    "--format",
    "-f",
    type=click.Choice(["json", "agenttrace", "markdown"]),
    default="json",
    help="Export format (default: json)",
)
@click.option("--agenttrace", is_flag=True, help="Deprecated: use --format agenttrace")
@click.option("--scrub/--no-scrub", default=False, help="Scrub sensitive data (API keys, etc.)")
def export(
    session_id: str | None,
    export_all: bool,
    output: str | None,
    format: str,
    agenttrace: bool,
    scrub: bool,
) -> None:
    """Export sessions to JSON, AgentTrace, or Markdown format."""
    # Handle deprecated flag
    if agenttrace:
        format = "agenttrace"

    if not session_id and not export_all:
        error_console.print(
            "[red]Error:[/red] Provide a session ID or use --all to export all sessions"
        )
        sys.exit(1)

    try:
        store = SessionStore()
    except Exception as e:
        error_console.print(f"[red]Error initializing store:[/red] {e}")
        sys.exit(1)

    # Initialize scrubber if needed
    scrubber = None
    if scrub:
        from sagg.security import DataScrubber

        scrubber = DataScrubber()

    try:
        if export_all:
            sessions = store.list_sessions(limit=10000)
            if not sessions:
                console.print("[dim]No sessions to export.[/dim]")
                return

            # Apply scrubbing to all sessions if requested
            if scrubber:
                # We need to deeply scrub the session objects.
                # Since models are immutable/pydantic, simplest way is to dump to dict, scrub, then re-validate
                # OR just scrub the output string if it's JSON/Markdown.
                # However, for structured export (list of dicts), scrubbing the dicts is better.
                pass  # We'll handle this per-item below

            if format == "markdown":
                # Markdown export for multiple sessions is tricky (one huge file?)
                # We'll separate them with horizontal rules
                from sagg.export.markdown import MarkdownExporter

                exporter = MarkdownExporter()
                parts = []
                for s in sessions:
                    s_data = s
                    if scrubber:
                        # Scrubbing logic for object access is complex without serialization
                        # For now, let's serialize -> scrub -> deserialize or just scrub text output
                        # Strategy: Serialize to JSON, scrub, deserialize back
                        s_json = s.model_dump_json()
                        s_scrubbed_json = scrubber.scrub(s_json)
                        s_data = s.model_validate_json(s_scrubbed_json)

                    parts.append(exporter.export_session(s_data))

                output_content = "\n\n".join(parts)

            elif format == "agenttrace":
                from sagg.export import AgentTraceExporter

                exporter = AgentTraceExporter()
                export_data = []
                for s in sessions:
                    s_data = s
                    if scrubber:
                        s_json = s.model_dump_json()
                        s_scrubbed_json = scrubber.scrub(s_json)
                        s_data = s.model_validate_json(s_scrubbed_json)

                    export_data.append(exporter.export_session(s_data).model_dump(mode="json"))

                import json

                output_content = json.dumps(export_data, indent=2)

            else:  # json
                import json

                export_data = []
                for s in sessions:
                    data = s.model_dump(mode="json")
                    if scrubber:
                        data = scrubber.scrub_object(data)
                    export_data.append(data)

                output_content = json.dumps(export_data, indent=2)

            if output:
                with open(output, "w") as f:
                    f.write(output_content)
                console.print(f"[green]Exported {len(sessions)} session(s) to {output}[/green]")
            else:
                console.print(output_content)

        else:
            # Single session export
            # Try to get session with partial ID matching
            session = store.get_session(session_id)  # type: ignore[arg-type]
            if session is None:
                # Try partial ID match
                sessions = store.list_sessions(limit=1000)
                matches = [s for s in sessions if s.id.startswith(session_id)]  # type: ignore[arg-type]
                if len(matches) == 1:
                    session = store.get_session(matches[0].id)
                elif len(matches) > 1:
                    error_console.print(
                        f"[red]Error:[/red] Ambiguous session ID. Multiple matches found:"
                    )
                    for s in matches[:5]:
                        error_console.print(f"  - {s.id}")
                    sys.exit(1)

            if session is None:
                error_console.print(f"[red]Error:[/red] Session '{session_id}' not found")
                sys.exit(1)

            # Scrubbing for single session
            if scrubber:
                # Serialize -> Scrub -> Deserialize
                s_json = session.model_dump_json()
                s_scrubbed_json = scrubber.scrub(s_json)
                # Re-validate to ensure integrity, or just use the JSON if output is JSON
                session = session.model_validate_json(s_scrubbed_json)

            if format == "markdown":
                from sagg.export.markdown import MarkdownExporter

                exporter = MarkdownExporter()
                output_content = exporter.export_session(session)

            elif format == "agenttrace":
                from sagg.export import AgentTraceExporter

                exporter = AgentTraceExporter()
                # We use export_to_json method or model_dump logic
                # The existing cli used export_to_json which returns string
                # But since we might have scrubbed the session object, better to use the object
                record = exporter.export_session(session)
                output_content = record.model_dump_json(indent=2)

            else:  # json
                output_content = session.model_dump_json(indent=2)

            if output:
                with open(output, "w") as f:
                    f.write(output_content)
                console.print(f"[green]Exported session to {output} ({format})[/green]")
            else:
                console.print(output_content)

    finally:
        store.close()


@cli.command()
@click.option(
    "--by", "group_by", type=click.Choice(["model", "source"]), help="Group statistics by"
)
def stats(group_by: str | None) -> None:
    """Show usage statistics."""
    try:
        store = SessionStore()
    except Exception as e:
        error_console.print(f"[red]Error initializing store:[/red] {e}")
        sys.exit(1)

    try:
        stats_data = store.get_stats()

        # Summary panel
        summary = f"""[bold]Total Sessions:[/bold] {stats_data["total_sessions"]:,}
[bold]Total Turns:[/bold] {stats_data["total_turns"]:,}
[bold]Total Tokens:[/bold] {stats_data["total_tokens"]:,}
  [dim]Input:[/dim] {stats_data["total_input_tokens"]:,}
  [dim]Output:[/dim] {stats_data["total_output_tokens"]:,}"""

        console.print(Panel(summary, title="Summary", border_style="blue"))

        if group_by == "source" or group_by is None:
            # Sessions by source
            if stats_data["sessions_by_source"]:
                source_table = Table(show_header=True, header_style="bold")
                source_table.add_column("Source")
                source_table.add_column("Sessions", justify="right")

                for source_name, count in sorted(
                    stats_data["sessions_by_source"].items(),
                    key=lambda x: x[1],
                    reverse=True,
                ):
                    source_table.add_row(source_name, str(count))

                console.print(
                    Panel(source_table, title="Sessions by Source", border_style="magenta")
                )

        if group_by == "model" or group_by is None:
            # Models used
            if stats_data["models_used"]:
                model_table = Table(show_header=True, header_style="bold")
                model_table.add_column("Model")
                model_table.add_column("Provider")
                model_table.add_column("Messages", justify="right")
                model_table.add_column("Tokens", justify="right")

                for model in stats_data["models_used"][:10]:
                    total_tokens = model["input_tokens"] + model["output_tokens"]
                    model_table.add_row(
                        model["model_id"],
                        model["provider"] or "[dim]—[/dim]",
                        str(model["message_count"]),
                        f"{total_tokens:,}",
                    )

                console.print(Panel(model_table, title="Models Used", border_style="green"))

        # Tools used
        if stats_data["tools_used"] and group_by is None:
            tools_table = Table(show_header=True, header_style="bold")
            tools_table.add_column("Tool")
            tools_table.add_column("Calls", justify="right")

            for tool_name, count in sorted(
                stats_data["tools_used"].items(),
                key=lambda x: x[1],
                reverse=True,
            )[:15]:
                tools_table.add_row(tool_name, f"{count:,}")

            console.print(Panel(tools_table, title="Top Tools", border_style="yellow"))

    finally:
        store.close()


@cli.command()
def sources() -> None:
    """List configured sources and their availability."""
    adapters = registry.list_adapters()

    if not adapters:
        console.print("[dim]No adapters configured.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Display Name")
    table.add_column("Status")
    table.add_column("Path")

    for adapter in adapters:
        available = adapter.is_available()
        status = "[green]Available[/green]" if available else "[red]Not Found[/red]"
        path = str(adapter.get_default_path())

        table.add_row(
            adapter.name,
            adapter.display_name,
            status,
            path,
        )

    console.print(table)


@cli.command()
def tui() -> None:
    """Launch the interactive terminal UI."""
    try:
        from sagg.tui import SaggApp
    except ImportError as e:
        error_console.print(f"[red]Error:[/red] TUI dependencies not installed: {e}")
        error_console.print("Install with: uv add textual")
        sys.exit(1)

    app = SaggApp()
    app.run()


@cli.command()
@click.argument("days", type=int, default=1)
@click.option("--project", "-p", type=str, help="Filter to specific project")
@click.option("--detailed", is_flag=True, help="Include detailed file lists")
def summarize(days: int, project: str | None, detailed: bool) -> None:
    """Summarize work progress for the last N days."""
    try:
        store = SessionStore()
    except Exception as e:
        error_console.print(f"[red]Error initializing store:[/red] {e}")
        sys.exit(1)

    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    
    try:
        # Fetch sessions (limit to 1000 to be safe)
        sessions = store.list_sessions(project=project, since=since_dt, limit=1000)
        
        if not sessions:
            console.print(f"[yellow]No sessions found in the last {days} day(s).[/yellow]")
            return

        # Group by Project -> Date
        grouped: dict[str, dict[str, list[UnifiedSession]]] = {}
        
        for session in sessions:
            proj = session.project_name or "Unknown Project"
            date_str = session.updated_at.strftime("%Y-%m-%d")
            
            if proj not in grouped:
                grouped[proj] = {}
            if date_str not in grouped[proj]:
                grouped[proj][date_str] = []
                
            grouped[proj][date_str].append(session)

        # Render Markdown
        console.print(f"# Work Summary (Last {days} Days)\n")
        
        for proj, dates in sorted(grouped.items()):
            console.print(f"## Project: [cyan]{proj}[/cyan]")
            
            for date_str, sess_list in sorted(dates.items(), reverse=True):
                console.print(f"### {date_str}")
                
                for s in sess_list:
                    duration_mins = (s.duration_ms or 0) // 60000
                    duration_str = f"{duration_mins}m" if duration_mins > 0 else "<1m"
                    
                    # Heuristic for title if generic
                    title = s.title or "Untitled Session"
                    
                    console.print(f"- **{title}** ({duration_str})")
                    
                    if detailed and s.stats.files_modified:
                        files_str = ", ".join(f"`{f}`" for f in s.stats.files_modified[:5])
                        if len(s.stats.files_modified) > 5:
                            files_str += f" and {len(s.stats.files_modified) - 5} more"
                        console.print(f"  - Modified: {files_str}")
                
                console.print("") # spacing

    finally:
        store.close()


def main() -> None:
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
