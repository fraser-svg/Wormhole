"""Manifest builder: auto-generate manifest.md from vault blocks."""

from datetime import datetime, timezone
from pathlib import Path

from wormhole.vault import Block


def build_manifest(vault_path: Path, blocks: list[tuple[Path, Block]]) -> str:
    """Generate manifest.md content grouped by category, sorted by date desc.

    Target: <500 tokens.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Group blocks by category
    by_category: dict[str, list[Block]] = {}
    for _, block in blocks:
        cat = block.category or "uncategorized"
        by_category.setdefault(cat, []).append(block)

    # Sort each category by date descending
    def _sort_key(b: Block) -> str:
        return b.date or "0000-00-00"

    for cat in by_category:
        by_category[cat].sort(key=_sort_key, reverse=True)

    lines: list[str] = [
        "# Wormhole Vault Manifest",
        f"Last updated: {timestamp} | Total: {len(blocks)} blocks",
        "",
    ]

    # Deterministic category order: known categories first, then alphabetical remainder
    known_order = [
        "decisions",
        "corrections",
        "failures",
        "architecture",
        "discoveries",
        "context",
    ]
    ordered_cats = [c for c in known_order if c in by_category]
    ordered_cats += sorted(c for c in by_category if c not in known_order)

    for cat in ordered_cats:
        cat_blocks = by_category[cat]
        lines.append(f"## {cat.title()} ({len(cat_blocks)})")
        for b in cat_blocks:
            date_str = b.date or "no-date"
            lines.append(f"- {date_str} | {b.title}")
        lines.append("")

    return "\n".join(lines)


def write_manifest(vault_path: Path, blocks: list[tuple[Path, Block]]) -> None:
    """Build manifest string and write to vault_path/manifest.md."""
    content = build_manifest(vault_path, blocks)
    manifest_path = vault_path / "manifest.md"
    manifest_path.write_text(content, encoding="utf-8")
