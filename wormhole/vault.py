"""Vault operations for reading, writing, and managing knowledge blocks."""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from wormhole.utils import sanitize_slug, validate_path_within

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {
    "decisions",
    "corrections",
    "discoveries",
    "architecture",
    "failures",
    "context",
}

NEGATION_WORDS = {
    "not",
    "no",
    "never",
    "dont",
    "don't",
    "doesn't",
    "doesnt",
    "shouldn't",
    "shouldnt",
    "avoid",
    "instead",
    "wrong",
    "incorrect",
    "false",
    "removed",
    "deprecated",
    "reverted",
    "rolled back",
    "rollback",
}


@dataclass
class Block:
    """A single knowledge block from the vault."""

    title: str
    category: str  # decisions, corrections, discoveries, architecture, failures, context
    content: str
    date: str = ""  # YYYY-MM-DD, empty for architecture blocks
    session: str = ""
    supersedes: str = ""
    files: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    source_session_id: str = ""
    confidence: float = 1.0


def read_block(path: Path) -> Block | None:
    """Read markdown file with YAML frontmatter delimited by ---.

    Parse frontmatter into Block fields. Content is everything after
    the second ---. Return None if file doesn't exist. Log warning and
    return None if frontmatter is malformed.
    """
    if not path.exists():
        return None

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        logger.warning("Malformed frontmatter in %s: missing --- delimiters", path)
        return None

    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        logger.warning("Malformed YAML frontmatter in %s: %s", path, exc)
        return None

    if not isinstance(fm, dict):
        logger.warning(
            "Malformed frontmatter in %s: expected mapping, got %s",
            path,
            type(fm).__name__,
        )
        return None

    content = parts[2].strip()

    return Block(
        title=str(fm.get("title", "")),
        category=str(fm.get("category", "")),
        content=content,
        date=str(fm.get("date", "")),
        session=str(fm.get("session", "")),
        supersedes=str(fm.get("supersedes", "")),
        files=fm.get("files") or [],
        related=fm.get("related") or [],
        source_session_id=str(fm.get("source_session_id", "")),
        confidence=float(fm.get("confidence", 1.0)),
    )


def write_block(block: Block, vault_path: Path) -> Path:
    """Write block as markdown with YAML frontmatter.

    Generate filename from block fields using sanitize_slug. Create
    category subdirectory if needed. Validate path stays within vault_path.
    Return the file path written.
    """
    slug = sanitize_slug(block.title)
    safe_category = sanitize_slug(block.category)

    if block.date:
        filename = f"{block.date}--{safe_category}--{slug}.md"
    else:
        filename = f"{safe_category}--{slug}.md"

    category_dir = vault_path / safe_category
    file_path = category_dir / filename

    if not validate_path_within(file_path, vault_path):
        msg = f"Path {file_path} escapes vault root {vault_path}"
        raise ValueError(msg)

    category_dir.mkdir(parents=True, exist_ok=True)

    fm: dict[str, object] = {
        "title": block.title,
        "category": block.category,
    }
    if block.date:
        fm["date"] = block.date
    if block.session:
        fm["session"] = block.session
    if block.supersedes:
        fm["supersedes"] = block.supersedes
    if block.files:
        fm["files"] = block.files
    if block.related:
        fm["related"] = block.related
    if block.source_session_id:
        fm["source_session_id"] = block.source_session_id
    if block.confidence != 1.0:
        fm["confidence"] = block.confidence

    frontmatter = yaml.dump(fm, default_flow_style=False, sort_keys=False).strip()
    output = f"---\n{frontmatter}\n---\n\n{block.content}\n"

    file_path.write_text(output, encoding="utf-8")
    return file_path


def list_blocks(
    vault_path: Path, category: str | None = None
) -> list[tuple[Path, Block]]:
    """List all blocks in vault, optionally filtered by category.

    Returns list of (path, block) tuples.
    """
    results: list[tuple[Path, Block]] = []

    if category:
        search_dirs = [vault_path / category]
    else:
        search_dirs = [
            d
            for d in vault_path.iterdir()
            if d.is_dir() and d.name in VALID_CATEGORIES
        ]

    for directory in search_dirs:
        if not directory.exists():
            continue
        for md_file in sorted(directory.glob("*.md")):
            block = read_block(md_file)
            if block is not None:
                results.append((md_file, block))

    return results


def parse_filename(filename: str) -> dict[str, str]:
    """Parse block filename into components.

    Dated: "2025-04-08--auth-strategy--session-cookies.md"
      -> {"date": "2025-04-08", "topic": "auth-strategy", "slug": "session-cookies"}

    Undated: "architecture--system-overview.md"
      -> {"date": "", "topic": "architecture", "slug": "system-overview"}
    """
    stem = filename.removesuffix(".md")
    parts = stem.split("--")

    # Dated: date--topic--slug (date matches YYYY-MM-DD)
    if len(parts) >= 3 and re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0]):
        return {
            "date": parts[0],
            "topic": parts[1],
            "slug": "--".join(parts[2:]),
        }

    # Undated: topic--slug
    if len(parts) >= 2:
        return {
            "date": "",
            "topic": parts[0],
            "slug": "--".join(parts[1:]),
        }

    # Single segment fallback
    return {
        "date": "",
        "topic": "",
        "slug": stem,
    }


def _tokenize(text: str) -> set[str]:
    """Lowercase, strip, split into word tokens."""
    return set(text.lower().split())


def _has_negation(text: str) -> bool:
    """Check if text contains negation words (whole-word match)."""
    words = set(text.lower().split())
    return bool(words & NEGATION_WORDS)


def deduplicate(
    new_block: Block,
    existing_blocks: list[Block],
    threshold: float = 0.8,
) -> str:
    """Check new block against existing blocks for duplication.

    Normalize both blocks (lowercase, strip whitespace), compute token
    overlap ratio. Compare within same category only.

    Returns:
        "skip"    -- existing has same info or more, drop new block
        "replace" -- new block has more info, replace existing
        "accept"  -- below threshold or contradiction, keep both
    """
    for existing in existing_blocks:
        # Only compare within same category
        if existing.category != new_block.category:
            continue

        # Don't auto-dedup contradictions (negation mismatch)
        new_text = f"{new_block.title} {new_block.content}"
        existing_text = f"{existing.title} {existing.content}"
        if _has_negation(new_text) != _has_negation(existing_text):
            continue

        # Compute token overlap ratio (Jaccard similarity)
        new_tokens = _tokenize(new_text)
        existing_tokens = _tokenize(existing_text)

        if not new_tokens or not existing_tokens:
            continue

        overlap = new_tokens & existing_tokens
        union = new_tokens | existing_tokens

        if not union:
            continue

        ratio = len(overlap) / len(union)

        if ratio > threshold:
            # More tokens = more info
            if len(existing_tokens) >= len(new_tokens):
                return "skip"
            return "replace"

    return "accept"
