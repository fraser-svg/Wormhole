"""Wormhole CLI — Click-based command interface with Rich output."""

import logging
import os
import shlex
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.panel import Panel

from wormhole.compiler_base import BaseCompiler
from wormhole.compiler_claude import ClaudeCompiler
from wormhole.compiler_cursor import CursorCompiler
from wormhole.config import Config, load_config, save_config
from wormhole.harvester_base import BaseHarvester
from wormhole.harvester_claude import ClaudeHarvester
from wormhole.manifest import build_manifest, write_manifest
from wormhole.scoring import build_index
from wormhole.utils import format_error
from wormhole.vault import VALID_CATEGORIES, Block, list_blocks, read_block, write_block

logger = logging.getLogger(__name__)

console = Console()

# Exit codes
EXIT_OK = 0
EXIT_GENERAL = 1
EXIT_NOT_INIT = 2
EXIT_CONFIG = 3
EXIT_HARVEST = 4

_VAULT_DIR = ".wormhole"

_COMPILERS: dict[str, type[BaseCompiler]] = {
    "claude": ClaudeCompiler,
    "cursor": CursorCompiler,
}

_HARVESTERS: dict[str, type[BaseHarvester]] = {
    "claude": ClaudeHarvester,
}

_CATEGORY_DIRS = [
    "decisions",
    "corrections",
    "discoveries",
    "architecture",
    "failures",
    "context",
    "staging",
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _get_vault_path() -> Path:
    """Find .wormhole/ in current or parent dirs. Exit with code 2 if not found."""
    current = Path.cwd()
    for directory in [current, *current.parents]:
        candidate = directory / _VAULT_DIR
        if candidate.is_dir():
            return candidate
    console.print(
        f"[red]{format_error('Vault not found', 'No .wormhole/ in current or parent directories', 'Run wormhole init')}[/red]"
    )
    raise SystemExit(EXIT_NOT_INIT)


def _resolve_tool(tool: str | None, config: Config) -> str:
    """Resolve tool name from argument or config default. Exit on failure."""
    resolved = tool or config.default_tool
    if not resolved:
        console.print(
            f"[red]{format_error('No tool specified', 'No tool argument and no default_tool in config', 'Pass tool name or set default_tool in config.yaml')}[/red]"
        )
        raise SystemExit(EXIT_CONFIG)
    return resolved


def _get_compiler(tool: str, vault_path: Path, config: Config) -> BaseCompiler:
    """Instantiate compiler for given tool name."""
    cls = _COMPILERS.get(tool)
    if cls is None:
        console.print(
            f"[red]{format_error(f'Unknown compiler: {tool}', f'Supported tools: {', '.join(_COMPILERS)}', 'Check tool name')}[/red]"
        )
        raise SystemExit(EXIT_CONFIG)
    return cls(vault_path, config)


def _get_harvester(tool: str, vault_path: Path, config: Config) -> BaseHarvester:
    """Instantiate harvester for given tool name."""
    cls = _HARVESTERS.get(tool)
    if cls is None:
        console.print(
            f"[red]{format_error(f'Unknown harvester: {tool}', f'Supported tools: {', '.join(_HARVESTERS)}', 'Check tool name')}[/red]"
        )
        raise SystemExit(EXIT_CONFIG)
    return cls(vault_path, config)


def _setup_logging(verbose: bool, quiet: bool) -> None:
    """Configure logging based on verbosity flags."""
    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.ERROR
    else:
        level = logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug output.")
@click.option("--quiet", "-q", is_flag=True, help="Errors only.")
@click.option("--dry-run", is_flag=True, help="Show what would be written without writing.")
@click.pass_context
def main(ctx: click.Context, verbose: bool, quiet: bool, dry_run: bool) -> None:
    """Wormhole — Universal project intelligence for AI coding agents."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet
    ctx.obj["dry_run"] = dry_run
    _setup_logging(verbose, quiet)


# ---------------------------------------------------------------------------
# wormhole init
# ---------------------------------------------------------------------------


@main.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Initialize a new .wormhole/ vault in the current directory."""
    vault_path = Path.cwd() / _VAULT_DIR

    if vault_path.exists():
        console.print(
            f"[yellow]{format_error('Already initialized', f'{vault_path} already exists', 'Remove it first or use existing vault')}[/yellow]"
        )
        raise SystemExit(EXIT_GENERAL)

    dry_run = ctx.obj.get("dry_run", False)

    if dry_run:
        console.print("[dim]Dry run: would create .wormhole/ directory structure[/dim]")
        return

    # Create directory structure
    vault_path.mkdir(parents=True)
    for subdir in _CATEGORY_DIRS:
        (vault_path / subdir).mkdir()

    # Write config.yaml with defaults
    config = Config()
    save_config(config, vault_path)

    # Write .version file
    (vault_path / ".version").write_text("1\n", encoding="utf-8")

    # Write context/project-goal.md stub
    goal_content = """\
---
title: Project Goal
category: context
confidence: 1.0
---
Describe your project's purpose, target users, and key constraints here.
This file is always included in compiled context.
"""
    (vault_path / "context" / "project-goal.md").write_text(goal_content, encoding="utf-8")

    # Write example decision block
    today = date.today().isoformat()
    example_block = f"""\
---
title: Example Decision
date: {today}
session: manual
category: decisions
files: []
confidence: 1.0
---

## Decision
This is an example decision block. Replace or delete it.

## Reasoning
Wormhole creates this example so your first `wormhole boot` produces useful output.
"""
    (vault_path / "decisions" / f"{today}--decisions--example-decision.md").write_text(
        example_block, encoding="utf-8"
    )

    # Add .wormhole/ to .gitignore
    gitignore_path = Path.cwd() / ".gitignore"
    gitignore_entry = ".wormhole/\n"
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8")
        if ".wormhole/" not in existing:
            with gitignore_path.open("a", encoding="utf-8") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write(gitignore_entry)
    else:
        gitignore_path.write_text(gitignore_entry, encoding="utf-8")

    console.print(
        Panel(
            "[green]Vault initialized.[/green]\n\n"
            "Next steps:\n"
            "  1. Edit [bold].wormhole/context/project-goal.md[/bold] with your project description\n"
            "  2. Run [bold]wormhole start claude[/bold] to boot and launch Claude Code\n"
            "  3. After a session, run [bold]wormhole end claude[/bold] to harvest knowledge",
            title="wormhole init",
        )
    )


# ---------------------------------------------------------------------------
# wormhole start [tool]
# ---------------------------------------------------------------------------


@main.command()
@click.argument("tool", required=False, default=None)
@click.pass_context
def start(ctx: click.Context, tool: str | None) -> None:
    """Boot context and launch an AI tool session."""
    vault_path = _get_vault_path()
    config = load_config(vault_path)
    resolved_tool = _resolve_tool(tool, config)
    dry_run = ctx.obj.get("dry_run", False)

    compiler = _get_compiler(resolved_tool, vault_path, config)

    if dry_run:
        compiled = compiler.compile()
        console.print("[dim]Dry run: compiled context below[/dim]")
        console.print(compiled)
        return

    # Compile and write
    compiler.write()
    console.print(f"[green]Compiled context for {resolved_tool}.[/green]")

    # Launch tool
    if resolved_tool == "claude":
        console.print("[bold]Launching Claude Code...[/bold]")
        claude_path = shutil.which("claude")
        if claude_path:
            os.execvp(claude_path, [claude_path])
        else:
            console.print(
                f"[yellow]{format_error('claude not found in PATH', 'Cannot auto-launch', 'Run claude manually')}[/yellow]"
            )
    else:
        console.print(
            f"[cyan]Context written. Open {resolved_tool} manually to use the compiled context.[/cyan]"
        )


# ---------------------------------------------------------------------------
# wormhole end [tool]
# ---------------------------------------------------------------------------


@main.command()
@click.argument("tool", required=False, default=None)
@click.pass_context
def end(ctx: click.Context, tool: str | None) -> None:
    """Harvest knowledge and rebuild manifest after a session."""
    vault_path = _get_vault_path()
    config = load_config(vault_path)
    resolved_tool = _resolve_tool(tool, config)
    dry_run = ctx.obj.get("dry_run", False)

    if dry_run:
        console.print(f"[dim]Dry run: would harvest from {resolved_tool} and rebuild manifest[/dim]")
        return

    # Harvest
    harvester = _get_harvester(resolved_tool, vault_path, config)
    try:
        written, skipped, staged = harvester.harvest()
    except (OSError, ValueError, KeyError) as exc:
        console.print(
            f"[red]{format_error('Harvest failed', str(exc), 'Check transcript availability')}[/red]"
        )
        raise SystemExit(EXIT_HARVEST) from exc

    # Rebuild manifest and index
    all_blocks = list_blocks(vault_path)
    try:
        write_manifest(vault_path, all_blocks)
        build_index(vault_path, all_blocks)
    except OSError as exc:
        console.print(
            f"[red]{format_error('Rebuild failed', str(exc), 'Check file permissions')}[/red]"
        )
        raise SystemExit(EXIT_GENERAL) from exc

    console.print(
        Panel(
            f"[green]Harvest complete.[/green]\n\n"
            f"  Written: [bold]{written}[/bold]\n"
            f"  Skipped: [bold]{skipped}[/bold] (duplicates)\n"
            f"  Staged:  [bold]{staged}[/bold] (low confidence, run [bold]wormhole review[/bold])",
            title=f"wormhole end {resolved_tool}",
        )
    )


# ---------------------------------------------------------------------------
# wormhole boot [tool]
# ---------------------------------------------------------------------------


@main.command()
@click.argument("tool", required=False, default=None)
@click.pass_context
def boot(ctx: click.Context, tool: str | None) -> None:
    """Compile and write context without launching the tool."""
    vault_path = _get_vault_path()
    config = load_config(vault_path)
    resolved_tool = _resolve_tool(tool, config)
    dry_run = ctx.obj.get("dry_run", False)

    compiler = _get_compiler(resolved_tool, vault_path, config)

    if dry_run:
        compiled = compiler.compile()
        console.print("[dim]Dry run: compiled context below[/dim]")
        console.print(compiled)
        return

    compiler.write()
    console.print(f"[green]Compiled context written for {resolved_tool}.[/green]")


# ---------------------------------------------------------------------------
# wormhole harvest [tool]
# ---------------------------------------------------------------------------


@main.command()
@click.argument("tool", required=False, default=None)
@click.pass_context
def harvest(ctx: click.Context, tool: str | None) -> None:
    """Harvest knowledge blocks from the latest session transcript."""
    vault_path = _get_vault_path()
    config = load_config(vault_path)
    resolved_tool = _resolve_tool(tool, config)
    dry_run = ctx.obj.get("dry_run", False)

    if dry_run:
        console.print(f"[dim]Dry run: would harvest from {resolved_tool}[/dim]")
        return

    harvester = _get_harvester(resolved_tool, vault_path, config)
    try:
        written, skipped, staged = harvester.harvest()
    except (OSError, ValueError, KeyError) as exc:
        console.print(
            f"[red]{format_error('Harvest failed', str(exc), 'Check transcript availability')}[/red]"
        )
        raise SystemExit(EXIT_HARVEST) from exc

    console.print(
        Panel(
            f"  Written: [bold]{written}[/bold]\n"
            f"  Skipped: [bold]{skipped}[/bold]\n"
            f"  Staged:  [bold]{staged}[/bold]",
            title=f"wormhole harvest {resolved_tool}",
        )
    )


# ---------------------------------------------------------------------------
# wormhole status
# ---------------------------------------------------------------------------


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show vault statistics and configuration summary."""
    vault_path = _get_vault_path()
    config = load_config(vault_path)

    # Block counts per category
    all_blocks = list_blocks(vault_path)
    counts: dict[str, int] = {}
    for _path, block in all_blocks:
        counts[block.category] = counts.get(block.category, 0) + 1

    # Staging count
    staging_path = vault_path / "staging"
    staging_count = 0
    if staging_path.exists():
        for subdir in staging_path.iterdir():
            if subdir.is_dir():
                staging_count += len(list(subdir.glob("*.md")))

    # Version
    version_file = vault_path / ".version"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "unknown"

    lines: list[str] = []
    lines.append(f"Vault version: [bold]{version}[/bold]")
    lines.append(f"Location: {vault_path}")
    lines.append(f"Total blocks: [bold]{len(all_blocks)}[/bold]")
    lines.append("")

    for cat in sorted(counts):
        lines.append(f"  {cat}: {counts[cat]}")

    if staging_count:
        lines.append(f"\n  staging: [yellow]{staging_count}[/yellow] (pending review)")

    lines.append("")
    lines.append(f"Default tool: [bold]{config.default_tool or '(not set)'}[/bold]")

    budget_parts = [f"{t}={b}" for t, b in config.budgets.items()]
    lines.append(f"Budgets: {', '.join(budget_parts)}")

    console.print(Panel("\n".join(lines), title="wormhole status"))


# ---------------------------------------------------------------------------
# wormhole manifest
# ---------------------------------------------------------------------------


@main.command()
@click.pass_context
def manifest(ctx: click.Context) -> None:
    """Rebuild and display the vault manifest."""
    vault_path = _get_vault_path()
    all_blocks = list_blocks(vault_path)
    dry_run = ctx.obj.get("dry_run", False)

    manifest_text = build_manifest(vault_path, all_blocks)

    if not dry_run:
        write_manifest(vault_path, all_blocks)

    console.print(manifest_text)


# ---------------------------------------------------------------------------
# wormhole config [action] [key] [value]
# ---------------------------------------------------------------------------


@main.command("config")
@click.argument("action", type=click.Choice(["show", "set", "edit"]))
@click.argument("key", required=False, default=None)
@click.argument("value", required=False, default=None)
@click.pass_context
def config_cmd(ctx: click.Context, action: str, key: str | None, value: str | None) -> None:
    """View or modify vault configuration."""
    vault_path = _get_vault_path()
    config = load_config(vault_path)

    if action == "show":
        from dataclasses import asdict

        data = asdict(config)
        console.print(yaml.dump(data, default_flow_style=False, sort_keys=False))

    elif action == "set":
        if not key or value is None:
            console.print(
                f"[red]{format_error('Missing arguments', 'set requires key and value', 'wormhole config set <key> <value>')}[/red]"
            )
            raise SystemExit(EXIT_CONFIG)

        from dataclasses import asdict

        data = asdict(config)

        # Support dot-path keys like "budgets.claude"
        parts = key.split(".")
        target = data
        for part in parts[:-1]:
            if isinstance(target, dict) and part in target:
                target = target[part]
            else:
                console.print(
                    f"[red]{format_error(f'Invalid key: {key}', f'Path segment {part} not found', 'Check config structure with wormhole config show')}[/red]"
                )
                raise SystemExit(EXIT_CONFIG)

        final_key = parts[-1]
        if isinstance(target, dict):
            # Type coercion: booleans, int, float, string
            if value.lower() in ("true", "false"):
                target[final_key] = value.lower() == "true"
            elif value.isdigit():
                target[final_key] = int(value)
            else:
                try:
                    target[final_key] = float(value)
                except ValueError:
                    target[final_key] = value

            new_config = Config(**data)
            dry_run = ctx.obj.get("dry_run", False)
            if dry_run:
                console.print(f"[dim]Dry run: would set {key} = {value}[/dim]")
            else:
                save_config(new_config, vault_path)
                console.print(f"[green]Set {key} = {value}[/green]")
        else:
            console.print(
                f"[red]{format_error(f'Cannot set {key}', 'Target is not a mapping', 'Check config structure')}[/red]"
            )
            raise SystemExit(EXIT_CONFIG)

    elif action == "edit":
        editor = os.environ.get("EDITOR", "vi")
        config_file = vault_path / "config.yaml"
        try:
            subprocess.run([*shlex.split(editor), str(config_file)], check=True)
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            console.print(
                f"[red]{format_error('Editor failed', str(exc), f'Set $EDITOR or edit {config_file} manually')}[/red]"
            )
            raise SystemExit(EXIT_GENERAL) from exc


# ---------------------------------------------------------------------------
# wormhole new <category> <title>
# ---------------------------------------------------------------------------


@main.command("new")
@click.argument("category", type=click.Choice(sorted(VALID_CATEGORIES)))
@click.argument("title")
@click.pass_context
def new_block(ctx: click.Context, category: str, title: str) -> None:
    """Create a new knowledge block with scaffolded frontmatter."""
    vault_path = _get_vault_path()
    dry_run = ctx.obj.get("dry_run", False)

    today = date.today().isoformat()
    block = Block(
        title=title,
        category=category,
        content=f"## {title}\n\nDescribe the {category.rstrip('s')} here.\n",
        date=today,
        session="manual",
        confidence=1.0,
    )

    if dry_run:
        console.print(f"[dim]Dry run: would create block '{title}' in {category}/[/dim]")
        return

    file_path = write_block(block, vault_path)
    console.print(f"[green]Created: {file_path}[/green]")

    editor = os.environ.get("EDITOR")
    if editor:
        try:
            subprocess.run([*shlex.split(editor), str(file_path)], check=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            pass  # Non-critical: block already written


# ---------------------------------------------------------------------------
# wormhole review
# ---------------------------------------------------------------------------


@main.command()
@click.pass_context
def review(ctx: click.Context) -> None:
    """Review staged blocks (low-confidence harvested blocks)."""
    vault_path = _get_vault_path()
    quiet = ctx.obj.get("quiet", False)
    dry_run = ctx.obj.get("dry_run", False)

    staging_path = vault_path / "staging"
    if not staging_path.exists():
        console.print("[dim]No staging directory found.[/dim]")
        return

    # Collect all staged block files
    staged_files: list[Path] = []
    for category_dir in sorted(staging_path.iterdir()):
        if category_dir.is_dir():
            staged_files.extend(sorted(category_dir.glob("*.md")))

    if not staged_files:
        console.print("[dim]No blocks in staging.[/dim]")
        return

    console.print(f"[bold]{len(staged_files)} block(s) in staging:[/bold]\n")

    if quiet:
        # Non-interactive: just list
        for path in staged_files:
            block = read_block(path)
            if block:
                console.print(f"  [{block.category}] {block.title} ({path.name})")
        return

    for path in staged_files:
        block = read_block(path)
        if block is None:
            continue

        console.print(
            Panel(
                f"[bold]{block.title}[/bold] ({block.category})\n"
                f"Confidence: {block.confidence}\n\n"
                f"{block.content[:500]}{'...' if len(block.content) > 500 else ''}",
                title=path.name,
            )
        )

        if dry_run:
            console.print("[dim]Dry run: skipping prompt[/dim]")
            continue

        action = click.prompt(
            "Action",
            type=click.Choice(["accept", "edit", "reject", "skip"]),
            default="skip",
        )

        if action == "accept":
            new_path = write_block(block, vault_path)
            path.unlink()
            console.print(f"[green]Accepted -> {new_path}[/green]")

        elif action == "edit":
            editor = os.environ.get("EDITOR", "vi")
            try:
                subprocess.run([*shlex.split(editor), str(path)], check=True)
            except (subprocess.SubprocessError, FileNotFoundError):
                console.print("[yellow]Editor failed. Block left in staging.[/yellow]")
                continue
            # Re-read after edit, then accept
            edited_block = read_block(path)
            if edited_block:
                new_path = write_block(edited_block, vault_path)
                path.unlink()
                console.print(f"[green]Edited and accepted -> {new_path}[/green]")

        elif action == "reject":
            path.unlink()
            console.print("[red]Rejected and deleted.[/red]")

        # skip: do nothing


# ---------------------------------------------------------------------------
# wormhole watch
# ---------------------------------------------------------------------------


@main.command()
@click.option("--interval", "-i", type=float, default=None, help="Poll interval in seconds.")
@click.pass_context
def watch(ctx: click.Context, interval: float | None) -> None:
    """Passively watch for transcript changes and auto-harvest."""
    vault_path = _get_vault_path()
    config = load_config(vault_path)

    if interval is not None:
        config.watcher["poll_interval"] = interval

    from wormhole.watcher import TranscriptWatcher

    watcher = TranscriptWatcher(vault_path, config)
    console.print(
        f"[bold]Watching for transcript changes[/bold] "
        f"(poll every {watcher.poll_interval:.1f}s, Ctrl+C to stop)"
    )

    try:
        watcher.start()
    except KeyboardInterrupt:
        watcher.stop()
        console.print("\n[dim]Watcher stopped.[/dim]")


# ---------------------------------------------------------------------------
# wormhole install-hooks
# ---------------------------------------------------------------------------

_HOOK_MARKER = "# wormhole-managed"

_HOOK_SCRIPT = """\
#!/bin/sh
{marker}
# Chain with existing hook if present
if [ -f "$0.local" ]; then
    "$0.local" "$@"
fi
wormhole --quiet end {tool} 2>/dev/null || true
"""


@main.command("install-hooks")
@click.argument("tool", required=False, default=None)
@click.pass_context
def install_hooks(ctx: click.Context, tool: str | None) -> None:
    """Install git post-commit hook for automatic harvesting."""
    vault_path = _get_vault_path()
    config = load_config(vault_path)
    resolved_tool = _resolve_tool(tool, config)

    git_dir = Path.cwd() / ".git"
    if not git_dir.is_dir():
        console.print(
            f"[red]{format_error('Not a git repo', 'No .git/ directory found', 'Run from a git repository')}[/red]"
        )
        raise SystemExit(EXIT_GENERAL)

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    hook_path = hooks_dir / "post-commit"

    dry_run = ctx.obj.get("dry_run", False)
    if dry_run:
        console.print("[dim]Dry run: would install post-commit hook[/dim]")
        return

    # Preserve existing hook
    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        if _HOOK_MARKER in existing:
            console.print("[yellow]Wormhole hook already installed.[/yellow]")
            return
        # Rename existing hook to .local
        local_path = hook_path.with_suffix(".local")
        hook_path.rename(local_path)
        console.print(f"[dim]Existing hook moved to {local_path.name}[/dim]")

    hook_path.write_text(
        _HOOK_SCRIPT.format(marker=_HOOK_MARKER, tool=resolved_tool),
        encoding="utf-8",
    )
    hook_path.chmod(0o755)
    console.print("[green]Installed post-commit hook for auto-harvesting.[/green]")


# ---------------------------------------------------------------------------
# wormhole uninstall-hooks
# ---------------------------------------------------------------------------


@main.command("uninstall-hooks")
@click.pass_context
def uninstall_hooks(ctx: click.Context) -> None:
    """Remove wormhole git hooks and restore originals."""
    git_dir = Path.cwd() / ".git"
    if not git_dir.is_dir():
        console.print(
            f"[red]{format_error('Not a git repo', 'No .git/ directory found', 'Run from a git repository')}[/red]"
        )
        raise SystemExit(EXIT_GENERAL)

    hook_path = git_dir / "hooks" / "post-commit"
    local_path = hook_path.with_suffix(".local")

    dry_run = ctx.obj.get("dry_run", False)
    if dry_run:
        console.print("[dim]Dry run: would uninstall post-commit hook[/dim]")
        return

    if not hook_path.exists():
        console.print("[dim]No post-commit hook found.[/dim]")
        return

    existing = hook_path.read_text(encoding="utf-8")
    if _HOOK_MARKER not in existing:
        console.print("[yellow]Post-commit hook not managed by wormhole.[/yellow]")
        return

    hook_path.unlink()

    # Restore original if it was saved
    if local_path.exists():
        local_path.rename(hook_path)
        console.print("[green]Restored original post-commit hook.[/green]")
    else:
        console.print("[green]Removed wormhole post-commit hook.[/green]")
