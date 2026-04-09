"""Wormhole MCP server — live vault queries for AI coding tools."""

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _validate_project_path(project_path: str) -> Path | None:
    """Validate and resolve project path. Returns None if invalid."""
    try:
        p = Path(project_path).resolve()
    except (ValueError, OSError):
        return None
    if not p.is_absolute():
        return None
    if not p.is_dir():
        return None
    return p


def _find_vault(project_path: str) -> Path | None:
    """Locate .wormhole/ vault for a project path."""
    resolved = _validate_project_path(project_path)
    if resolved is None:
        return None
    vault = resolved / ".wormhole"
    return vault if vault.is_dir() else None


def _query_vault_impl(
    project_path: str,
    category: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """List blocks from a project vault, optionally filtered."""
    from wormhole.vault import VALID_CATEGORIES, list_blocks

    vault = _find_vault(project_path)
    if vault is None:
        return []

    if category and category not in VALID_CATEGORIES:
        return []

    blocks = list_blocks(vault, category=category)
    results: list[dict[str, Any]] = []

    for path, block in blocks:
        if query:
            text = f"{block.title} {block.content}".lower()
            if query.lower() not in text:
                continue
        # Truncate content for listing
        snippet = block.content[:300]
        if len(block.content) > 300:
            snippet += "..."
        results.append({
            "title": block.title,
            "category": block.category,
            "date": block.date,
            "confidence": block.confidence,
            "snippet": snippet,
        })

    return results


def _get_block_impl(project_path: str, block_title: str) -> dict[str, Any] | None:
    """Get full content of a specific block by title."""
    from wormhole.vault import list_blocks

    vault = _find_vault(project_path)
    if vault is None:
        return None

    for _path, block in list_blocks(vault):
        if block.title.lower() == block_title.lower():
            return {
                "title": block.title,
                "category": block.category,
                "date": block.date,
                "confidence": block.confidence,
                "content": block.content,
                "files": block.files,
                "related": block.related,
            }
    return None


def _search_vault_impl(project_path: str, pattern: str) -> list[dict[str, Any]]:
    """Regex search across all blocks in a project vault."""
    from wormhole.vault import list_blocks

    vault = _find_vault(project_path)
    if vault is None:
        return []

    if len(pattern) > 1000:
        return []
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return []

    results: list[dict[str, Any]] = []
    for _path, block in list_blocks(vault):
        text = f"{block.title}\n{block.content}"
        matches = regex.findall(text)
        if matches:
            results.append({
                "title": block.title,
                "category": block.category,
                "date": block.date,
                "matches": matches[:10],  # Cap at 10
                "snippet": block.content[:300],
            })

    return results


def _list_projects_impl() -> list[dict[str, Any]]:
    """List all tracked projects from the registry."""
    from wormhole.project_registry import ProjectRegistry

    registry = ProjectRegistry()
    return [
        {
            "path": p.path,
            "detected_at": p.detected_at,
            "tool": p.tool,
            "auto_initialized": p.auto_initialized,
        }
        for p in registry.list_projects()
    ]


def create_mcp_server() -> Any:
    """Create and configure the MCP server instance.

    Returns the Server object.  Requires ``mcp`` package.
    """
    try:
        from mcp.server import Server
    except ImportError as exc:
        raise ImportError(
            "MCP support requires the mcp package: pip install wormhole-ai[mcp]"
        ) from exc

    server = Server("wormhole")

    @server.tool()
    async def query_vault(
        project_path: str,
        category: str | None = None,
        query: str | None = None,
    ) -> str:
        """Query knowledge blocks from a project's Wormhole vault.

        Args:
            project_path: Absolute path to the project directory.
            category: Optional filter by category (decisions, corrections, discoveries, architecture, failures, context).
            query: Optional substring to match against block titles and content.
        """
        results = _query_vault_impl(project_path, category, query)
        return json.dumps(results, indent=2)

    @server.tool()
    async def get_block(project_path: str, block_title: str) -> str:
        """Get the full content of a specific knowledge block by title.

        Args:
            project_path: Absolute path to the project directory.
            block_title: Title of the block to retrieve (case-insensitive match).
        """
        result = _get_block_impl(project_path, block_title)
        if result is None:
            return json.dumps({"error": "Block not found"})
        return json.dumps(result, indent=2)

    @server.tool()
    async def search_vault(project_path: str, pattern: str) -> str:
        """Regex search across all knowledge blocks in a project vault.

        Args:
            project_path: Absolute path to the project directory.
            pattern: Regular expression pattern to search for (case-insensitive).
        """
        results = _search_vault_impl(project_path, pattern)
        return json.dumps(results, indent=2)

    @server.tool()
    async def list_projects() -> str:
        """List all projects tracked by the Wormhole daemon."""
        results = _list_projects_impl()
        return json.dumps(results, indent=2)

    return server


def run_stdio() -> None:
    """Run the MCP server on stdio transport (called by Claude Code)."""
    import asyncio

    try:
        from mcp.server.stdio import stdio_server
    except ImportError as exc:
        raise ImportError(
            "MCP support requires the mcp package: pip install wormhole-ai[mcp]"
        ) from exc

    server = create_mcp_server()

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_run())


def install_mcp_config() -> bool:
    """Register Wormhole as an MCP server in Claude Code config.

    Writes to ~/.claude.json.  Returns True if config was updated.
    """
    claude_config = Path.home() / ".claude.json"

    data: dict[str, Any] = {}
    if claude_config.exists():
        try:
            data = json.loads(claude_config.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("~/.claude.json is corrupt — refusing to overwrite")
            return False
        except OSError:
            data = {}

    servers = data.setdefault("mcpServers", {})
    if "wormhole" in servers:
        return False  # Already registered

    servers["wormhole"] = {
        "command": "wormhole",
        "args": ["mcp"],
    }

    # Atomic write to avoid corrupting Claude Code config on crash
    tmp = claude_config.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(claude_config)
    return True
