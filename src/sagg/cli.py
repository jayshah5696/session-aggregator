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


def parse_token_amount(s: str) -> int:
    """Parse token amount string like '500k', '1M', '100000' to integer.

    Supported formats:
        Plain number: 100000 -> 100000
        k/K suffix: 500k -> 500000
        M/m suffix: 1M -> 1000000
        Decimals: 2.5M -> 2500000

    Args:
        s: Token amount string (e.g., '500k', '1M', '100000')

    Returns:
        Integer token count.

    Raises:
        ValueError: If the format is invalid.
    """
    s = s.strip()
    if not s:
        raise ValueError("Empty token amount")

    # Try matching with suffix (k, K, m, M)
    match = re.match(r"^(\d+(?:\.\d+)?)([kKmM])$", s)
    if match:
        value = float(match.group(1))
        suffix = match.group(2).lower()

        if suffix == "k":
            return int(value * 1000)
        elif suffix == "m":
            return int(value * 1000000)

    # Try plain integer
    try:
        return int(s)
    except ValueError:
        pass

    raise ValueError(f"Invalid token amount format: '{s}'. Use format like '500k', '1M', or '100000'")


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
@click.option("--force", is_flag=True, help="Overwrite existing configuration")
@click.option("--dry-run", is_flag=True, help="Preview without making changes")
def init(force: bool, dry_run: bool) -> None:
    """Setup wizard that auto-detects installed AI tools.

    Scans your system for known AI coding tools (Claude Code, OpenCode, Cursor, etc.),
    generates a configuration file, and initializes the database.
    """
    from pathlib import Path
    from rich.prompt import Confirm
    from sagg.adapters import registry
    from sagg.storage import SessionStore

    config_path = Path.home() / ".sagg" / "config.toml"

    if config_path.exists() and not force and not dry_run:
        console.print(f"[yellow]Configuration file already exists at {config_path}[/yellow]")
        if not Confirm.ask("Do you want to overwrite it?"):
            console.print("[dim]Aborted.[/dim]")
            return

    console.print("[bold]Looking for AI tools...[/bold]\n")

    found_tools = []
    adapters = registry.list_adapters()

    for adapter in adapters:
        if adapter.is_available():
            default_path = adapter.get_default_path()

            # Count sessions (with spinner as it might take time)
            session_count: int | str = 0
            with console.status(f"Scanning {adapter.display_name} sessions..."):
                try:
                    sessions = adapter.list_sessions()
                    session_count = len(sessions)
                except Exception as e:
                    # Fallback if scanning fails but folder exists
                    session_count = "?"
                    error_console.print(f"[dim]Error scanning {adapter.name}: {e}[/dim]")

            console.print(
                f"✅ Found [cyan]{adapter.display_name}[/cyan]: {default_path} ({session_count} sessions)"
            )
            found_tools.append((adapter, default_path, session_count))
        else:
            console.print(
                f"❌ [dim]{adapter.display_name}: not installed (or not in default location)[/dim]"
            )

    console.print()

    if not found_tools:
        console.print("[yellow]No AI tools found in default locations.[/yellow]")
        if not dry_run and not Confirm.ask("Do you want to create a configuration file anyway?"):
            return

    # Ask which ones to enable
    enabled_sources = {}

    # Pre-populate with found tools
    for adapter, path, _ in found_tools:
        if dry_run or Confirm.ask(f"Enable {adapter.display_name}?", default=True):
            enabled_sources[adapter.name] = {"enabled": True, "path": str(path)}
        else:
            enabled_sources[adapter.name] = {"enabled": False, "path": str(path)}

    # Add disabled entries for not found tools (so they appear in config but disabled)
    found_names = {a.name for a, _, _ in found_tools}
    for adapter in adapters:
        if adapter.name not in found_names:
            enabled_sources[adapter.name] = {
                "enabled": False,
                "path": str(adapter.get_default_path()),
            }

    # Generate config content
    config_lines = []
    for source_name, config in enabled_sources.items():
        config_lines.append(f"[sources.{source_name}]")
        config_lines.append(f"enabled = {str(config['enabled']).lower()}")
        # Escape path for TOML (basic escaping)
        path_str = config["path"].replace("\\", "\\\\").replace('"', '\\"')
        config_lines.append(f'path = "{path_str}"')
        config_lines.append("")

    # Add default sections
    config_lines.append("[viewer]")
    config_lines.append("port = 3000")
    config_lines.append("open_browser = true")
    config_lines.append("")

    config_lines.append("[export]")
    config_lines.append('default_format = "agenttrace"')
    config_lines.append('output_dir = "~/.sagg/exports"')

    config_content = "\n".join(config_lines)

    if dry_run:
        console.print("\n[bold]Generated Configuration (Dry Run):[/bold]")
        syntax = Syntax(config_content, "toml", theme="monokai", line_numbers=False)
        console.print(Panel(syntax, title="config.toml", border_style="blue"))
        console.print("[dim]Skipping file write and database initialization.[/dim]")
    else:
        # Create directory
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Write config
        config_path.write_text(config_content)
        console.print(f"\n[green]Created {config_path}[/green]")

        # Initialize database
        with console.status("Initializing database..."):
            try:
                # Just instantiating the store initializes the DB
                store = SessionStore()
                store.close()
            except Exception as e:
                error_console.print(f"[red]Error initializing database:[/red] {e}")

        console.print("[green]Database initialized successfully[/green]")

        console.print("\n[bold]Setup complete![/bold]")
        console.print("Run 'sagg collect' to import your sessions.")


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
@click.option("--weeks", "-w", type=int, default=12, help="Number of weeks to show")
@click.option(
    "--by",
    "metric",
    type=click.Choice(["sessions", "tokens"]),
    default="sessions",
    help="Metric to display (sessions or tokens)",
)
def heatmap(weeks: int, metric: str) -> None:
    """Show activity heatmap (GitHub-style contributions)."""
    from sagg.analytics.heatmap import (
        get_activity_by_day,
        generate_heatmap_data,
        render_heatmap,
        get_month_labels,
    )

    try:
        store = SessionStore()
    except Exception as e:
        error_console.print(f"[red]Error initializing store:[/red] {e}")
        sys.exit(1)

    try:
        # Get activity data
        activity = get_activity_by_day(store, weeks=weeks, metric=metric)

        # Generate heatmap grid
        data = generate_heatmap_data(activity, weeks=weeks)

        # Get month labels for header
        month_labels = get_month_labels(weeks)

        # Build month header line
        label_width = 6  # "  Sun " width
        month_header = " " * label_width
        prev_pos = 0
        for pos, label in month_labels:
            spaces_needed = pos - prev_pos
            month_header += " " * spaces_needed + label
            prev_pos = pos + len(label)

        # Render heatmap
        heatmap_output = render_heatmap(data, legend=True)

        # Calculate summary stats
        total_sessions = sum(activity.values()) if metric == "sessions" else 0
        total_tokens = sum(activity.values()) if metric == "tokens" else 0
        active_days = len(activity)

        # Build title
        metric_label = "sessions" if metric == "sessions" else "tokens"
        title = f"Activity Heatmap (last {weeks} weeks, by {metric_label})"

        # Create output with Rich
        output_lines = [month_header, heatmap_output]

        # Add summary
        if metric == "sessions":
            summary = f"\n  {total_sessions:,} sessions across {active_days} active days"
        else:
            summary = f"\n  {total_tokens:,} tokens across {active_days} active days"

        output_lines.append(summary)

        console.print(Panel("\n".join(output_lines), title=title, border_style="green"))

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


@cli.command("git-link")
@click.option("--project", "-p", type=str, help="Filter by project")
@click.option("--update", "do_update", is_flag=True, help="Update session git info")
@click.option("--since", type=str, help="Only sessions from last N days (e.g., 7d, 2w)")
def git_link(project: str | None, do_update: bool, since: str | None) -> None:
    """Associate sessions with git commits by timestamp proximity."""
    from pathlib import Path

    from sagg.git_utils import find_closest_commit, get_repo_info, is_git_repo
    from sagg.models import GitContext

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
        # Get sessions
        sessions = store.list_sessions(project=project, limit=500)

        # Filter by since if provided
        if since_dt:
            sessions = [s for s in sessions if s.updated_at >= since_dt]

        if not sessions:
            console.print("[dim]No sessions found.[/dim]")
            return

        # Build table
        table = Table(show_header=True, header_style="bold")
        table.add_column("Session", style="cyan", max_width=30)
        table.add_column("Time", style="yellow")
        table.add_column("Commit", style="green")
        table.add_column("Message", style="white", max_width=40)

        updated_count = 0

        for session in sessions:
            session_title = (session.title or "Untitled")[:30]
            session_time = format_age(session.updated_at)

            commit_sha = "[dim]---[/dim]"
            commit_msg = "[dim]No project path[/dim]"

            if session.project_path:
                project_path = Path(session.project_path)

                if project_path.exists() and is_git_repo(project_path):
                    commit = find_closest_commit(project_path, session.updated_at)

                    if commit:
                        commit_sha = commit["sha"][:7]
                        commit_msg = (commit["message"] or "")[:40]

                        # Update session if requested
                        if do_update and commit:
                            # Get full session and update git context
                            full_session = store.get_session(session.id)
                            if full_session:
                                repo_info = get_repo_info(project_path)
                                full_session.git = GitContext(
                                    branch=repo_info["branch"] if repo_info else None,
                                    commit=commit["sha"],
                                    remote=repo_info["remote"] if repo_info else None,
                                )
                                store.save_session(full_session)
                                updated_count += 1
                    else:
                        commit_msg = "[dim]No matching commit[/dim]"
                else:
                    commit_msg = "[dim]Not a git repo[/dim]"

            table.add_row(session_title, session_time, commit_sha, commit_msg)

        console.print(table)

        if do_update and updated_count > 0:
            console.print(f"\n[green]Updated git info for {updated_count} session(s)[/green]")

    finally:
        store.close()


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


@cli.command()
@click.argument("query", required=False)
@click.option("--session", "-s", type=str, help="Find sessions similar to this session ID")
@click.option("--top", "-n", type=int, default=5, help="Number of results to show")
def similar(query: str | None, session: str | None, top: int) -> None:
    """Find similar sessions.

    Find sessions similar to a query string or an existing session.

    Examples:
        sagg similar "implement authentication"
        sagg similar --session abc123
        sagg similar "fix login" --top 10
    """
    if not query and not session:
        error_console.print("[red]Error:[/red] Provide a query or --session ID")
        sys.exit(1)

    try:
        store = SessionStore()
    except Exception as e:
        error_console.print(f"[red]Error initializing store:[/red] {e}")
        sys.exit(1)

    try:
        from sagg.analytics.similar import find_similar_sessions

        try:
            results = find_similar_sessions(
                store,
                query=query,
                session_id=session,
                limit=top,
            )
        except ValueError as e:
            error_console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)

        if not results:
            if query:
                console.print(f"[dim]No similar sessions found for '{query}'[/dim]")
            else:
                console.print(f"[dim]No similar sessions found for session '{session}'[/dim]")
            return

        # Build the display title
        if query:
            display_title = f'Similar Sessions to "{query[:50]}{"..." if len(query) > 50 else ""}"'
        else:
            # Get the source session title
            source_session = store.get_session(session)  # type: ignore[arg-type]
            if source_session and source_session.title:
                display_title = f'Similar Sessions to "{source_session.title[:50]}"'
            else:
                display_title = f"Similar Sessions to {session}"

        console.print(f"\n[bold]{display_title}[/bold]\n")

        # Create a table for results
        table = Table(
            show_header=False,
            box=None,
            padding=(0, 1),
            collapse_padding=True,
        )
        table.add_column("Rank", style="dim", width=4)
        table.add_column("Details", style="white")

        for i, result in enumerate(results, 1):
            # Format similarity percentage
            similarity_pct = int(result.score * 100)
            if similarity_pct >= 70:
                score_style = "green"
            elif similarity_pct >= 40:
                score_style = "yellow"
            else:
                score_style = "dim"

            # Format matched terms
            matched_terms_str = ", ".join(result.matched_terms[:5])
            if len(result.matched_terms) > 5:
                matched_terms_str += f" (+{len(result.matched_terms) - 5} more)"

            # Build the detail lines
            title_line = f"[bold]{result.title}[/bold] ([{score_style}]{similarity_pct}% similar[/{score_style}])"
            project_line = f"[cyan]{result.project}[/cyan] [dim]•[/dim] [dim]{truncate_id(result.session_id, 12)}[/dim]"

            details = f"{title_line}\n{project_line}"
            if matched_terms_str:
                details += f"\n[dim]Matched: {matched_terms_str}[/dim]"

            table.add_row(f"{i}.", details)

            # Add a blank row between results (except after the last one)
            if i < len(results):
                table.add_row("", "")

        console.print(table)

    finally:
        store.close()


@cli.command()
@click.argument("query")
@click.option("--top", "-n", type=int, default=5, help="Number of results to show")
@click.option("--verbose", "-v", is_flag=True, help="Show full snippets")
def oracle(query: str, top: int, verbose: bool) -> None:
    """Search your history: 'Have I solved this before?'

    Semantic search over your session history to find past solutions.

    Examples:
        sagg oracle "rate limiting"
        sagg oracle "fix TypeError"
        sagg oracle "authentication" --top 10
    """
    try:
        store = SessionStore()
    except Exception as e:
        error_console.print(f"[red]Error initializing store:[/red] {e}")
        sys.exit(1)

    try:
        from sagg.analytics.oracle import search_history

        results = search_history(store, query, limit=top)

        if not results:
            console.print(f"[dim]No sessions found matching '{query}'[/dim]")
            return

        from rich.text import Text

        console.print(f'[bold]Oracle: "{query}"[/bold]')
        console.print(f"Found {len(results)} relevant session(s):\n")

        for result in results:
            # Calculate time ago
            now = datetime.now(timezone.utc)
            if result.timestamp.tzinfo is None:
                timestamp = result.timestamp.replace(tzinfo=timezone.utc)
            else:
                timestamp = result.timestamp

            delta = now - timestamp
            seconds = delta.total_seconds()

            if seconds < 3600:
                time_ago = f"{int(seconds / 60)}m ago"
            elif seconds < 86400:
                time_ago = f"{int(seconds / 3600)}h ago"
            elif seconds < 604800:
                time_ago = f"{int(seconds / 86400)} days ago"
            else:
                time_ago = f"{int(seconds / 604800)} weeks ago"

            # Format relevance as percentage
            relevance_pct = int(result.relevance_score * 100)

            # Build panel content
            panel_content = Text()
            panel_content.append(f"Project: {result.project}", style="green")
            panel_content.append(" - ", style="dim")
            panel_content.append(time_ago, style="yellow")
            panel_content.append("\n\n")

            # Truncate snippet for non-verbose mode
            snippet = result.matched_text
            if not verbose and len(snippet) > 150:
                snippet = snippet[:150] + "..."

            panel_content.append(f'"{snippet}"', style="italic")

            # Create panel with title showing relevance
            panel_title = f"Session: {result.title} ({relevance_pct}% match)"

            console.print(
                Panel(
                    panel_content,
                    title=panel_title,
                    border_style="blue",
                )
            )
            console.print()  # Spacing between panels

    except Exception as e:
        error_console.print(f"[red]Error searching:[/red] {e}")
        sys.exit(1)
    finally:
        store.close()


@cli.command()
@click.option("--source", "-s", type=str, help="Sync specific source only")
@click.option("--watch", "-w", is_flag=True, help="Watch for changes and sync continuously")
@click.option("--dry-run", is_flag=True, help="Show what would be synced without saving")
@click.option("--debounce", type=int, default=2000, help="Debounce interval in ms for watch mode")
def sync(source: str | None, watch: bool, dry_run: bool, debounce: int) -> None:
    """Sync sessions from sources (incremental).

    Performs incremental sync, only importing new sessions since the last sync.

    Examples:
        sagg sync                    # One-time sync from all sources
        sagg sync --source opencode  # Sync only from OpenCode
        sagg sync --watch            # Watch for changes continuously
        sagg sync --dry-run          # Preview what would be synced
    """
    from sagg.sync import SessionSyncer

    try:
        store = SessionStore()
    except Exception as e:
        error_console.print(f"[red]Error initializing store:[/red] {e}")
        sys.exit(1)

    try:
        # Get adapters (optionally filtered by source)
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

        syncer = SessionSyncer(store, adapters)

        if watch:
            # Watch mode with continuous sync
            _run_watch_mode(syncer, source, debounce, dry_run)
        else:
            # One-time sync
            _run_sync_once(syncer, source, dry_run)

    finally:
        store.close()


def _run_sync_once(syncer, source: str | None, dry_run: bool) -> None:
    """Run a one-time sync operation."""
    from rich.live import Live

    mode_label = "[dim](dry run)[/dim] " if dry_run else ""
    console.print(f"{mode_label}[bold]Syncing sessions...[/bold]")

    results = syncer.sync_once(source=source, dry_run=dry_run)

    if not results:
        console.print("[yellow]No sources to sync.[/yellow]")
        return

    total_new = 0
    total_skipped = 0

    for src_name, result in results.items():
        new_count = result.get("new", 0)
        skipped_count = result.get("skipped", 0)
        total_new += new_count
        total_skipped += skipped_count

        if new_count > 0:
            console.print(f"  [green]+{new_count}[/green] new from [cyan]{src_name}[/cyan]")
        elif skipped_count > 0:
            console.print(f"  [dim]No new sessions from {src_name} ({skipped_count} already imported)[/dim]")
        else:
            console.print(f"  [dim]No sessions found from {src_name}[/dim]")

    if dry_run:
        console.print(f"\n[bold]{mode_label}Would sync {total_new} new session(s)[/bold]")
    else:
        console.print(f"\n[bold green]Synced {total_new} new session(s)[/bold green]")


def _run_watch_mode(syncer, source: str | None, debounce: int, dry_run: bool) -> None:
    """Run continuous watch mode."""
    from rich.live import Live

    mode_label = "[dim](dry run)[/dim] " if dry_run else ""
    console.print(f"{mode_label}[bold]Watching for changes...[/bold] (Ctrl+C to stop)\n")

    # Show which paths we're watching
    paths = syncer.get_watch_paths(source)
    for path in paths:
        console.print(f"  [dim]Watching:[/dim] {path}")
    console.print()

    try:
        for event in syncer.watch(source=source, debounce_ms=debounce):
            timestamp = event.timestamp.strftime("%H:%M:%S")
            if event.new_count > 0:
                console.print(
                    f"[dim][{timestamp}][/dim] [green]+[/green] Synced {event.new_count} session(s) from [cyan]{event.source}[/cyan]"
                )
            else:
                console.print(
                    f"[dim][{timestamp}][/dim] [dim]No new sessions from {event.source}[/dim]"
                )
    except KeyboardInterrupt:
        console.print("\n[yellow]Watch mode stopped.[/yellow]")
    except ImportError as e:
        error_console.print(f"[red]Error:[/red] {e}")
        error_console.print("Install watchfiles with: uv add watchfiles")
        sys.exit(1)


@cli.group()
def bundle() -> None:
    """Export and import session bundles for multi-machine sync."""
    pass


@bundle.command("export")
@click.option("--output", "-o", type=click.Path(), required=True, help="Output bundle file path")
@click.option("--since", type=str, help="Only sessions from last N days (e.g., 7d, 2w)")
@click.option("--project", "-p", type=str, help="Filter by project name")
@click.option("--source", "-s", type=str, help="Filter by source (opencode, claude, etc.)")
def bundle_export(output: str, since: str | None, project: str | None, source: str | None) -> None:
    """Export sessions to a portable bundle.

    Creates a .sagg bundle file containing sessions that can be imported
    on another machine.

    Examples:
        sagg bundle export -o my-sessions.sagg
        sagg bundle export --since 7d -o weekly.sagg
        sagg bundle export --project myapp -o myapp.sagg
    """
    from pathlib import Path

    from sagg.bundle import export_bundle

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
        output_path = Path(output)

        # Add .sagg extension if not present
        if not output_path.suffix:
            output_path = output_path.with_suffix(".sagg")

        console.print("Exporting sessions...")

        count = export_bundle(
            store,
            output_path,
            since=since_dt,
            project=project,
            source=source,
        )

        if count == 0:
            console.print("[yellow]No sessions to export.[/yellow]")
        else:
            # Get file size
            size_bytes = output_path.stat().st_size
            if size_bytes >= 1024 * 1024:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
            elif size_bytes >= 1024:
                size_str = f"{size_bytes / 1024:.1f} KB"
            else:
                size_str = f"{size_bytes} bytes"

            console.print(f"[green]Created:[/green] {output_path} ({size_str})")
            console.print(f"[green]Exported {count} session(s)[/green]")

    except Exception as e:
        error_console.print(f"[red]Error exporting bundle:[/red] {e}")
        sys.exit(1)
    finally:
        store.close()


@bundle.command("import")
@click.argument("bundle_file", type=click.Path(exists=True))
@click.option(
    "--strategy",
    type=click.Choice(["skip", "replace"]),
    default="skip",
    help="How to handle duplicates (default: skip)",
)
@click.option("--dry-run", is_flag=True, help="Preview without importing")
@click.option("--verify", "verify_first", is_flag=True, help="Verify integrity before import")
def bundle_import(
    bundle_file: str, strategy: str, dry_run: bool, verify_first: bool
) -> None:
    """Import sessions from a bundle.

    Imports sessions from a .sagg bundle file created on another machine
    or as a backup.

    Examples:
        sagg bundle import my-sessions.sagg
        sagg bundle import backup.sagg --dry-run
        sagg bundle import team.sagg --verify --strategy replace
    """
    from pathlib import Path

    from sagg.bundle import import_bundle, verify_bundle

    bundle_path = Path(bundle_file)

    # Verify integrity if requested
    if verify_first:
        console.print("Verifying bundle integrity...")
        if not verify_bundle(bundle_path):
            error_console.print("[red]Error:[/red] Bundle integrity check failed")
            sys.exit(1)
        console.print("[green]Bundle verified successfully[/green]")

    try:
        store = SessionStore()
    except Exception as e:
        error_console.print(f"[red]Error initializing store:[/red] {e}")
        sys.exit(1)

    try:
        if dry_run:
            console.print("Previewing import (dry run)...")
        else:
            console.print("Importing sessions...")

        result = import_bundle(
            store,
            bundle_path,
            strategy=strategy,
            dry_run=dry_run,
        )

        # Display results
        if dry_run:
            console.print(
                f"Would import {result['imported']} session(s) "
                f"({result['skipped']} duplicate(s) to skip)"
            )
        else:
            console.print(
                f"[green]Imported {result['imported']} session(s)[/green] "
                f"(skipped {result['skipped']} duplicate(s))"
            )

        if result["errors"]:
            error_console.print("[yellow]Warnings:[/yellow]")
            for error in result["errors"]:
                error_console.print(f"  - {error}")

    except Exception as e:
        error_console.print(f"[red]Error importing bundle:[/red] {e}")
        sys.exit(1)
    finally:
        store.close()


@bundle.command("verify")
@click.argument("bundle_file", type=click.Path(exists=True))
def bundle_verify(bundle_file: str) -> None:
    """Verify bundle integrity.

    Checks that the bundle file is not corrupted by verifying its checksum.

    Example:
        sagg bundle verify my-sessions.sagg
    """
    from pathlib import Path

    from sagg.bundle import verify_bundle

    bundle_path = Path(bundle_file)

    console.print(f"Verifying {bundle_path}...")

    if verify_bundle(bundle_path):
        console.print("[green]Bundle integrity verified successfully[/green]")
    else:
        error_console.print("[red]Bundle integrity check failed[/red]")
        sys.exit(1)


@cli.command("friction-points")
@click.option("--since", type=str, help="Only sessions from last N days (e.g., 7d, 2w)")
@click.option("--threshold", type=int, default=3, help="Retry threshold for flagging")
@click.option("--top", "-n", type=int, default=10, help="Number of results to show")
def friction_points(since: str | None, threshold: int, top: int) -> None:
    """Detect sessions with excessive friction.

    Analyzes sessions for friction indicators including:
    - High retry count: Same tool called many times in sequence
    - Error ratio: High percentage of tool call errors
    - Back-and-forth: Many short user corrections

    Examples:
        sagg friction-points
        sagg friction-points --since 7d
        sagg friction-points --threshold 5 --top 20
    """
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
        from sagg.analytics.friction import FrictionType, detect_friction_points

        friction_list = detect_friction_points(
            store,
            since=since_dt,
            retry_threshold=threshold,
        )

        if not friction_list:
            time_desc = f" (last {since})" if since else ""
            console.print(f"[dim]No friction points detected{time_desc}.[/dim]")
            return

        # Limit to top N
        friction_list = friction_list[:top]

        # Build title
        time_desc = f"last {since}" if since else "all time"
        console.print(f"[bold]Friction Points ({time_desc})[/bold]\n")

        # Count by severity
        high_count = sum(1 for fp in friction_list if fp.friction_score >= 0.6)
        medium_count = sum(1 for fp in friction_list if 0.3 <= fp.friction_score < 0.6)

        for fp in friction_list:
            # Determine severity level and color
            if fp.friction_score >= 0.6:
                severity = "High Friction"
                border_color = "red"
            elif fp.friction_score >= 0.3:
                severity = "Medium Friction"
                border_color = "yellow"
            else:
                severity = "Low Friction"
                border_color = "dim"

            # Build panel title
            panel_title = f"{severity}: {fp.title} (score: {fp.friction_score:.2f})"

            # Build panel content
            lines = []

            # Project and age line
            lines.append(
                f"[dim]Project:[/dim] [cyan]{fp.project}[/cyan] "
                f"[dim]-[/dim] [dim]{truncate_id(fp.session_id, 12)}[/dim]"
            )
            lines.append("")

            # Friction indicators
            for ftype in fp.friction_types:
                if ftype == FrictionType.HIGH_RETRIES:
                    retry_count = fp.details.get("retry_count", 0)
                    retry_tools = fp.details.get("retry_tools", [])
                    tools_str = ", ".join(retry_tools[:3])
                    if len(retry_tools) > 3:
                        tools_str += "..."
                    lines.append(
                        f"[yellow]![/yellow]  High retries: "
                        f"{retry_count} sequential retries ({tools_str})"
                    )

                elif ftype == FrictionType.ERROR_RATE:
                    error_rate = fp.details.get("error_rate", 0)
                    lines.append(
                        f"[yellow]![/yellow]  Error rate: "
                        f"{int(error_rate * 100)}% of tool calls failed"
                    )

                elif ftype == FrictionType.BACK_AND_FORTH:
                    count = fp.details.get("back_forth_count", 0)
                    lines.append(f"[yellow]![/yellow]  Back-and-forth: {count} short corrections")

                elif ftype == FrictionType.LOW_EFFICIENCY:
                    lines.append("[yellow]![/yellow]  Low efficiency: Many tokens, little output")

            # Add suggestion based on friction types
            lines.append("")
            if FrictionType.HIGH_RETRIES in fp.friction_types:
                lines.append("[dim]Tip:[/dim] Consider breaking complex tasks into smaller steps")
            elif FrictionType.BACK_AND_FORTH in fp.friction_types:
                lines.append("[dim]Tip:[/dim] Try providing more context upfront")
            elif FrictionType.ERROR_RATE in fp.friction_types:
                lines.append("[dim]Tip:[/dim] Check command syntax before running")

            console.print(
                Panel(
                    "\n".join(lines),
                    title=panel_title,
                    border_style=border_color,
                )
            )
            console.print()  # Spacing between panels

        # Summary
        console.print(
            f"[bold]Summary:[/bold] {high_count} high friction, "
            f"{medium_count} medium friction session(s) found"
        )

    except Exception as e:
        error_console.print(f"[red]Error analyzing sessions:[/red] {e}")
        sys.exit(1)
    finally:
        store.close()


@cli.group()
def budget() -> None:
    """Manage token budgets."""
    pass


@budget.command("set")
@click.option("--weekly", type=str, help="Weekly token budget (e.g., 500k, 1M)")
@click.option("--daily", type=str, help="Daily token budget (e.g., 100k)")
def budget_set(weekly: str | None, daily: str | None) -> None:
    """Set token budgets.

    Examples:
        sagg budget set --weekly 500k
        sagg budget set --daily 100k
        sagg budget set --weekly 1M --daily 200k
    """
    if not weekly and not daily:
        error_console.print("[red]Error:[/red] Specify --weekly or --daily budget")
        sys.exit(1)

    try:
        store = SessionStore()
    except Exception as e:
        error_console.print(f"[red]Error initializing store:[/red] {e}")
        sys.exit(1)

    try:
        if weekly:
            try:
                weekly_limit = parse_token_amount(weekly)
                store.set_budget("weekly", weekly_limit)
                console.print(f"[green]Set weekly budget:[/green] {weekly_limit:,} tokens")
            except ValueError as e:
                error_console.print(f"[red]Error:[/red] {e}")
                sys.exit(1)

        if daily:
            try:
                daily_limit = parse_token_amount(daily)
                store.set_budget("daily", daily_limit)
                console.print(f"[green]Set daily budget:[/green] {daily_limit:,} tokens")
            except ValueError as e:
                error_console.print(f"[red]Error:[/red] {e}")
                sys.exit(1)

    finally:
        store.close()


@budget.command("show")
def budget_show() -> None:
    """Show current budget usage.

    Displays progress bars showing token usage vs. budget with color coding:
    - Green: Below 80% usage
    - Yellow: 80-95% usage (warning)
    - Red: Above 95% usage (critical)
    """
    from rich.progress import BarColumn, Progress, TaskID, TextColumn

    try:
        store = SessionStore()
    except Exception as e:
        error_console.print(f"[red]Error initializing store:[/red] {e}")
        sys.exit(1)

    try:
        daily_budget = store.get_budget("daily")
        weekly_budget = store.get_budget("weekly")

        if daily_budget is None and weekly_budget is None:
            console.print("[dim]No budgets set.[/dim]")
            console.print("\nSet budgets with:")
            console.print("  sagg budget set --daily 100k")
            console.print("  sagg budget set --weekly 500k")
            return

        console.print("[bold]Token Budget Status[/bold]\n")

        def get_color(percentage: float) -> str:
            """Get color based on usage percentage."""
            if percentage >= 95:
                return "red"
            elif percentage >= 80:
                return "yellow"
            else:
                return "green"

        def format_tokens(tokens: int) -> str:
            """Format token count for display."""
            if tokens >= 1000000:
                return f"{tokens / 1000000:.1f}M"
            elif tokens >= 1000:
                return f"{tokens / 1000:.1f}k"
            else:
                return str(tokens)

        if daily_budget is not None:
            daily_usage = store.get_usage_for_period("daily")
            daily_pct = (daily_usage / daily_budget) * 100 if daily_budget > 0 else 0
            color = get_color(daily_pct)

            # Build visual progress bar
            bar_width = 40
            filled = int((daily_pct / 100) * bar_width)
            filled = min(filled, bar_width)  # Cap at 100%
            bar = "[" + "=" * filled + " " * (bar_width - filled) + "]"

            console.print(f"[bold]Daily Budget[/bold]")
            console.print(
                f"  [{color}]{bar}[/{color}] "
                f"[{color}]{daily_pct:.1f}%[/{color}]"
            )
            console.print(
                f"  [dim]Used:[/dim] {format_tokens(daily_usage)} / {format_tokens(daily_budget)}"
            )
            console.print()

        if weekly_budget is not None:
            weekly_usage = store.get_usage_for_period("weekly")
            weekly_pct = (weekly_usage / weekly_budget) * 100 if weekly_budget > 0 else 0
            color = get_color(weekly_pct)

            # Build visual progress bar
            bar_width = 40
            filled = int((weekly_pct / 100) * bar_width)
            filled = min(filled, bar_width)  # Cap at 100%
            bar = "[" + "=" * filled + " " * (bar_width - filled) + "]"

            console.print(f"[bold]Weekly Budget[/bold]")
            console.print(
                f"  [{color}]{bar}[/{color}] "
                f"[{color}]{weekly_pct:.1f}%[/{color}]"
            )
            console.print(
                f"  [dim]Used:[/dim] {format_tokens(weekly_usage)} / {format_tokens(weekly_budget)}"
            )
            console.print()

        # Show alerts if approaching limits
        alerts = []
        if daily_budget is not None:
            daily_usage = store.get_usage_for_period("daily")
            daily_pct = (daily_usage / daily_budget) * 100 if daily_budget > 0 else 0
            if daily_pct >= 95:
                alerts.append("[red]! Daily budget nearly exhausted[/red]")
            elif daily_pct >= 80:
                alerts.append("[yellow]! Approaching daily budget limit[/yellow]")

        if weekly_budget is not None:
            weekly_usage = store.get_usage_for_period("weekly")
            weekly_pct = (weekly_usage / weekly_budget) * 100 if weekly_budget > 0 else 0
            if weekly_pct >= 95:
                alerts.append("[red]! Weekly budget nearly exhausted[/red]")
            elif weekly_pct >= 80:
                alerts.append("[yellow]! Approaching weekly budget limit[/yellow]")

        if alerts:
            console.print("[bold]Alerts[/bold]")
            for alert in alerts:
                console.print(f"  {alert}")

    finally:
        store.close()


@budget.command("clear")
@click.option("--weekly", is_flag=True, help="Clear weekly budget")
@click.option("--daily", is_flag=True, help="Clear daily budget")
def budget_clear(weekly: bool, daily: bool) -> None:
    """Clear token budgets.

    If no flags specified, clears all budgets.

    Examples:
        sagg budget clear          # Clear all
        sagg budget clear --daily  # Clear daily only
        sagg budget clear --weekly # Clear weekly only
    """
    try:
        store = SessionStore()
    except Exception as e:
        error_console.print(f"[red]Error initializing store:[/red] {e}")
        sys.exit(1)

    try:
        # If neither flag specified, clear both
        if not weekly and not daily:
            weekly = True
            daily = True

        if daily:
            store.clear_budget("daily")
            console.print("[green]Cleared daily budget[/green]")

        if weekly:
            store.clear_budget("weekly")
            console.print("[green]Cleared weekly budget[/green]")

    finally:
        store.close()


@cli.command("analyze-sessions")
@click.option("--since", type=str, default="30d", help="Analyze sessions from last N (e.g., 7d, 30d)")
@click.option("--source", "-s", type=str, help="Filter by source tool")
@click.option("--project", "-p", type=str, help="Filter by project")
@click.option("--force", is_flag=True, help="Re-analyze sessions that already have facets")
@click.option(
    "--analyzer",
    type=click.Choice(["heuristic", "llm"]),
    default="heuristic",
    help="Analysis method (default: heuristic)",
)
@click.option("--llm-cli", type=str, help="Which CLI for LLM (claude, codex, gemini). Auto-detects if omitted.")
@click.option("--batch-size", type=int, default=10, show_default=True, help="Sessions per LLM call")
@click.option(
    "--resume/--no-resume",
    default=True,
    show_default=True,
    help="With --force --analyzer llm, skip sessions already analyzed in this range",
)
@click.option("--dry-run", is_flag=True, help="Show what would be analyzed")
@click.option("--verbose", "-v", is_flag=True, help="Show per-session results")
def analyze_sessions(
    since: str,
    source: str | None,
    project: str | None,
    force: bool,
    analyzer: str,
    llm_cli: str | None,
    batch_size: int,
    resume: bool,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Extract structured facets from sessions for insights analysis.

    Analyzes each session and stores a structured "facet" containing
    goal, outcome, friction, and tool effectiveness data.

    Examples:
        sagg analyze-sessions                    # Heuristic, last 30 days
        sagg analyze-sessions --analyzer llm     # Use LLM via CLI tool
        sagg analyze-sessions --since 7d --force # Re-analyze last week
    """
    if batch_size < 1:
        error_console.print("[red]Error:[/red] --batch-size must be >= 1")
        sys.exit(1)

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
        # Get sessions to analyze
        if force:
            sessions = store.list_sessions(source=source, project=project, since=since_dt, limit=5000)
        else:
            sessions = store.get_unfaceted_sessions(
                since=since_dt,
                source=source,
                project=project,
                limit=5000,
            )

        if not sessions:
            console.print("[dim]No sessions to analyze.[/dim]")
            return

        if dry_run:
            console.print(f"[bold]Would analyze {len(sessions)} session(s) ({analyzer})[/bold]")
            for s in sessions[:10]:
                console.print(f"  {s.source.value:10s} {(s.title or 'Untitled')[:50]}")
            if len(sessions) > 10:
                console.print(f"  [dim]... and {len(sessions) - 10} more[/dim]")
            return

        console.print(f"[bold]Analyzing {len(sessions)} session(s) ({analyzer})...[/bold]")

        # Check LLM availability if needed
        backend: str | None = None
        if analyzer == "llm":
            from sagg.analytics.insights.cli_llm import detect_available_backend

            backend = llm_cli or detect_available_backend()
            if backend is None:
                error_console.print(
                    "[red]Error:[/red] No LLM CLI tool found. "
                    "Install claude, codex, or gemini CLI, or use --analyzer heuristic"
                )
                sys.exit(1)
            console.print(f"[dim]Using LLM backend: {backend}[/dim]")

        analyzed = 0
        skipped_non_substantive = 0
        skipped_already_analyzed = 0
        errors = 0

        if analyzer == "llm":
            from sagg.analytics.insights.cli_llm import (
                analyze_session_llm,
                analyze_sessions_llm_batch,
                is_session_substantive,
            )

            completed_ids: set[str] = set()
            if force and resume:
                existing_facets = store.get_facets(source=source, since=since_dt, project=project, limit=10000)
                completed_ids = {
                    f["session_id"]
                    for f in existing_facets
                    if f.get("analyzer_version") == "llm_v1"
                }
                if completed_ids and verbose:
                    console.print(
                        f"[dim]Resume enabled: skipping {len(completed_ids)} already analyzed sessions[/dim]"
                    )

            llm_sessions = []
            for session in sessions:
                if session.id in completed_ids:
                    skipped_already_analyzed += 1
                    continue

                full_session = store.get_session(session.id)
                if full_session is None:
                    continue
                if not is_session_substantive(full_session):
                    skipped_non_substantive += 1
                    if verbose:
                        console.print(
                            f"  [dim]-[/dim] skipped non-substantive: {session.id[:12]} "
                            f"{(session.title or 'Untitled')[:50]}"
                        )
                    continue
                llm_sessions.append(full_session)

            for i in range(0, len(llm_sessions), batch_size):
                chunk = llm_sessions[i:i + batch_size]
                try:
                    facets = analyze_sessions_llm_batch(chunk, backend_name=backend)
                except Exception as e:
                    if verbose:
                        error_console.print(
                            f"  [yellow]![/yellow] Batch failed ({len(chunk)} sessions): {e}"
                        )
                        error_console.print("  [dim]Falling back to per-session LLM calls for this batch[/dim]")
                    facets = []
                    for single_session in chunk:
                        try:
                            facets.append(analyze_session_llm(single_session, backend_name=backend))
                        except Exception as single_err:
                            errors += 1
                            if verbose:
                                error_console.print(
                                    f"  [red]![/red] Failed: {single_session.id[:12]} - {single_err}"
                                )

                for facet_data in facets:
                    try:
                        store.upsert_facet(facet_data)
                        analyzed += 1
                        if verbose:
                            console.print(
                                f"  [green]+[/green] {facet_data['task_type']:12s} "
                                f"{facet_data['outcome']:20s} "
                                f"friction={facet_data['friction_score']:.2f}  "
                                f"{(facet_data['brief_summary'] or '')[:50]}"
                            )
                    except Exception:
                        errors += 1

            console.print(f"\n[bold green]Analyzed {analyzed} session(s)[/bold green]", end="")
            if skipped_already_analyzed:
                console.print(
                    f" [dim]({skipped_already_analyzed} skipped already-analyzed)[/dim]",
                    end="",
                )
            if skipped_non_substantive:
                console.print(f" [dim]({skipped_non_substantive} skipped non-substantive)[/dim]", end="")
            if errors:
                console.print(f" [yellow]({errors} errors)[/yellow]")
            else:
                console.print()
            return

        for session in sessions:
            try:
                # Load full session content
                full_session = store.get_session(session.id)
                if full_session is None:
                    continue

                if analyzer == "llm":
                    from sagg.analytics.insights.cli_llm import analyze_session_llm

                    facet_data = analyze_session_llm(full_session, backend_name=backend)
                else:
                    from sagg.analytics.insights.heuristic import analyze_session

                    facet_data = analyze_session(full_session)

                store.upsert_facet(facet_data)
                analyzed += 1

                if verbose:
                    console.print(
                        f"  [green]+[/green] {facet_data['task_type']:12s} "
                        f"{facet_data['outcome']:20s} "
                        f"friction={facet_data['friction_score']:.2f}  "
                        f"{(facet_data['brief_summary'] or '')[:50]}"
                    )

            except Exception as e:
                errors += 1
                if verbose:
                    error_console.print(f"  [red]![/red] Failed: {session.id[:12]} - {e}")

        console.print(f"\n[bold green]Analyzed {analyzed} session(s)[/bold green]", end="")
        if skipped_non_substantive:
            console.print(f" [dim]({skipped_non_substantive} skipped non-substantive)[/dim]", end="")
        if errors:
            console.print(f" [yellow]({errors} errors)[/yellow]")
        else:
            console.print()

    finally:
        store.close()


@cli.command()
@click.option("--since", type=str, default="30d", help="Time range (e.g., 7d, 30d)")
@click.option("--source", "-s", type=str, multiple=True, help="Filter by source (repeatable)")
@click.option("--project", "-p", type=str, help="Filter by project")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["cli", "json", "html"]),
    default="cli",
    help="Output format",
)
@click.option("--output", "-o", type=click.Path(), help="Save report to file")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed breakdowns")
def insights(
    since: str,
    source: tuple[str, ...],
    project: str | None,
    output_format: str,
    output: str | None,
    verbose: bool,
) -> None:
    """Generate cross-tool usage insights report.

    Aggregates session facets into a comprehensive report showing
    tool comparison, friction patterns, and recommendations.

    Run 'sagg analyze-sessions' first to extract facets.

    Examples:
        sagg insights                           # CLI summary
        sagg insights --format json -o report.json
        sagg insights --source claude --source cursor
    """
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
        # Get facets
        facets = []
        if source:
            for s in source:
                facets.extend(store.get_facets(source=s, since=since_dt, project=project))
        else:
            facets = store.get_facets(since=since_dt, project=project)

        if not facets:
            console.print("[yellow]No facets found. Run 'sagg analyze-sessions' first.[/yellow]")
            return

        # Get stats
        stats = store.get_stats()

        # Generate report
        from sagg.analytics.insights.aggregator import generate_insights

        report = generate_insights(
            facets=facets,
            stats=stats,
            range_start=since_dt,
            range_end=datetime.now(timezone.utc),
        )

        # Output
        if output_format == "json":
            import json

            json_output = json.dumps(report, indent=2, default=str)
            if output:
                with open(output, "w") as f:
                    f.write(json_output)
                console.print(f"[green]Report saved to {output}[/green]")
            else:
                console.print(json_output)

        elif output_format == "html":
            console.print("[yellow]HTML export coming soon. Use --format json for now.[/yellow]")

        else:
            # CLI output
            _print_insights_cli(report, verbose=verbose)

    finally:
        store.close()


def _print_insights_cli(report: dict, verbose: bool = False) -> None:
    """Print insights report as rich CLI output."""
    glance = report.get("at_a_glance", {})
    tool_comp = report.get("tool_comparison", {})
    friction = report.get("friction_analysis", {})
    trends = report.get("trends", {})
    suggestions = report.get("suggestions", {})
    areas = report.get("project_areas", [])
    workflows = report.get("impressive_workflows", [])
    fun = report.get("fun_ending", {})

    total = report.get("total_facets", 0)
    tools = tool_comp.get("tools_analyzed", [])

    # Header
    console.print()
    console.print("[bold]Session Insights[/bold]", end="")
    console.print(f"  [dim]{total} sessions analyzed[/dim]", end="")
    if tools:
        tool_counts = tool_comp.get("sessions_per_tool", {})
        tool_str = " · ".join(f"{t} ({tool_counts.get(t, 0)})" for t in tools)
        console.print(f"  [dim]{tool_str}[/dim]")
    else:
        console.print()

    console.print()

    # At a Glance
    if glance.get("whats_working"):
        console.print(Panel(
            f"[bold]Working:[/bold] {glance['whats_working']}\n\n"
            f"[bold]Hindering:[/bold] {glance.get('whats_hindering', '')}\n\n"
            f"[bold]Quick win:[/bold] {glance.get('quick_wins', '')}",
            title="At a Glance",
            border_style="yellow",
        ))

    # Tool Comparison
    metrics = tool_comp.get("tool_metrics", [])
    if metrics:
        tool_table = Table(show_header=True, header_style="bold", title="Cross-Tool Comparison")
        tool_table.add_column("Tool", style="cyan")
        tool_table.add_column("Sessions", justify="right")
        tool_table.add_column("Success", justify="right")
        tool_table.add_column("Friction", justify="right")
        tool_table.add_column("Best For", style="dim")

        best_for = tool_comp.get("best_for", {})

        for m in metrics:
            tool_name = m["tool"]
            best_tasks = [t for t, tool in best_for.items() if tool == tool_name]
            best_str = ", ".join(best_tasks[:2]) if best_tasks else "—"

            # Color success rate
            success_pct = f"{m['success_rate']:.0%}"
            if m["success_rate"] >= 0.8:
                success_pct = f"[green]{success_pct}[/green]"
            elif m["success_rate"] >= 0.6:
                success_pct = f"[yellow]{success_pct}[/yellow]"
            else:
                success_pct = f"[red]{success_pct}[/red]"

            tool_table.add_row(
                tool_name,
                str(m["session_count"]),
                success_pct,
                f"{m['avg_friction_score']:.2f}",
                best_str,
            )

        console.print(tool_table)
        console.print()

    # Friction
    if friction.get("top_friction_patterns"):
        console.print("[bold]Top Friction Patterns[/bold]")
        for p in friction["top_friction_patterns"][:5]:
            cat = p["category"].replace("_", " ").title()
            console.print(f"  [yellow]![/yellow] {cat} ({p['count']}x)")
        console.print()

    # Project Areas (verbose only)
    if verbose and areas:
        console.print("[bold]Project Areas[/bold]")
        for area in areas[:5]:
            console.print(
                f"  [cyan]{area['name']}[/cyan] ({area['session_count']} sessions, "
                f"{area['success_rate']:.0%} success)"
            )
        console.print()

    # Impressive workflows (verbose only)
    if verbose and workflows:
        console.print("[bold]Impressive Workflows[/bold]")
        for w in workflows:
            console.print(f"  [green]★[/green] {w['title']}")
            if w.get("description"):
                console.print(f"    [dim]{w['description'][:80]}[/dim]")
        console.print()

    # Suggestions
    agents_md = suggestions.get("agents_md_additions", [])
    if agents_md:
        console.print("[bold]Suggested AGENTS.md Additions[/bold]")
        for s in agents_md[:5]:
            console.print(f"  [{s['target_file']}] {s['addition'][:80]}")
            console.print(f"  [dim]Why: {s['why']}[/dim]")
            console.print()

    # Tool recommendations
    recs = suggestions.get("tool_recommendations", [])
    if recs:
        console.print("[bold]Tool Recommendations[/bold]")
        for r in recs[:5]:
            confidence = f"{'●' * int(r['confidence'] * 5)}{'○' * (5 - int(r['confidence'] * 5))}"
            console.print(f"  {r['task_type']:20s} → [cyan]{r['recommended_tool']}[/cyan]  [{confidence}]")
        console.print()

    # Trends
    console.print(
        f"[dim]Friction trend: {trends.get('friction_trend', 'stable')} · "
        f"Productivity trend: {trends.get('productivity_trend', 'stable')}[/dim]"
    )

    # Fun ending
    if fun.get("headline"):
        console.print()
        console.print(Panel(
            f"[bold]{fun['headline']}[/bold]\n[dim]{fun.get('detail', '')}[/dim]",
            border_style="yellow",
        ))


def main() -> None:
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
