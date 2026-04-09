"""Utility functions for Wormhole."""

import re
from pathlib import Path


def estimate_tokens(text: str) -> int:
    """Rough token estimate: word count * 1.3."""
    words = text.split()
    return int(len(words) * 1.3)


def sanitize_slug(text: str) -> str:
    """Lowercase, replace non-alphanumeric with hyphens, collapse and strip."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    return slug


def validate_path_within(path: Path, root: Path) -> bool:
    """Check resolved path is inside resolved root. Prevents path traversal."""
    try:
        resolved_path = path.resolve()
        resolved_root = root.resolve()
        return resolved_path == resolved_root or str(resolved_path).startswith(
            str(resolved_root) + "/"
        )
    except (OSError, ValueError):
        return False


def format_error(what: str, why: str, fix: str) -> str:
    """Standard error format string."""
    return f"Error: {what}. {why}. {fix}."
