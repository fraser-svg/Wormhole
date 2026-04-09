"""Claude Code transcript harvester."""

import json
import logging
import os
from pathlib import Path

from wormhole.config import Config
from wormhole.harvester_base import BaseHarvester

logger = logging.getLogger(__name__)


def _mangle_path(project_path: str) -> str:
    """Convert absolute path to Claude's mangled directory name.

    Claude Code mangles project paths by replacing / with - and
    stripping the leading -.

    Example: /Users/foxy/myproject -> Users-foxy-myproject
    """
    mangled = project_path.replace("/", "-")
    return mangled.lstrip("-")


def _find_latest_jsonl(projects_dir: Path) -> Path | None:
    """Find the most recently modified JSONL file in a Claude projects dir."""
    jsonl_files = list(projects_dir.glob("*.jsonl"))
    if not jsonl_files:
        return None
    return max(jsonl_files, key=lambda p: p.stat().st_mtime)


def _extract_content(message: dict) -> str:
    """Extract text content from a Claude message object.

    Content can be a plain string or a list of content blocks.
    For list form, concatenate all text-type blocks.
    """
    content = message.get("message", {}).get("content", "")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)

    return ""


class ClaudeHarvester(BaseHarvester):
    """Harvester for Claude Code JSONL transcripts."""

    def __init__(
        self,
        vault_path: Path,
        config: Config,
        project_path: str | None = None,
    ) -> None:
        super().__init__(vault_path, config)
        self.tool_name = "claude"
        self.project_path = project_path or os.getcwd()

    def read_transcript(self) -> list[dict]:
        """Read Claude Code JSONL transcript.

        Resolves the project path to the Claude projects directory,
        finds the most recent JSONL file, parses it, and returns
        normalized messages filtering out non-conversation entries.
        """
        claude_home = Path.home() / ".claude" / "projects"
        mangled = _mangle_path(self.project_path)
        projects_dir = claude_home / mangled

        if not projects_dir.exists():
            logger.warning(
                "Claude projects directory not found: %s", projects_dir
            )
            return []

        jsonl_path = _find_latest_jsonl(projects_dir)
        if jsonl_path is None:
            logger.warning(
                "No JSONL files found in %s", projects_dir
            )
            return []

        logger.info("Reading Claude transcript: %s", jsonl_path)

        # Use filename stem as session ID
        self.session_id = jsonl_path.stem

        messages: list[dict] = []
        try:
            text = jsonl_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read transcript %s: %s", jsonl_path, exc)
            return []

        for line_num, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.debug(
                    "Skipping malformed JSON at line %d: %s", line_num, exc
                )
                continue

            if not isinstance(entry, dict):
                continue

            # Skip non-message types
            entry_type = entry.get("type", "")
            if entry_type not in ("user", "assistant"):
                continue

            # Skip sidechains
            if entry.get("isSidechain", False):
                continue

            # Extract role and content
            msg_obj = entry.get("message", {})
            if not isinstance(msg_obj, dict):
                continue

            role = msg_obj.get("role", entry_type)
            content = _extract_content(entry)

            if not content.strip():
                continue

            messages.append({"role": role, "content": content})

        logger.info(
            "Parsed %d messages from Claude transcript", len(messages)
        )
        return messages
