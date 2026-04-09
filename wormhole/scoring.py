"""Relevance scoring engine for vault blocks."""

import hashlib
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from wormhole.config import Config
from wormhole.utils import estimate_tokens
from wormhole.vault import Block

logger = logging.getLogger(__name__)


def _build_ref_counts(
    all_blocks: list[Block],
    all_paths: list[str],
) -> dict[str, int]:
    """Count how many blocks reference each path via related/supersedes."""
    ref_counts: dict[str, int] = {p: 0 for p in all_paths}

    for block in all_blocks:
        refs: list[str] = list(block.related)
        if block.supersedes:
            refs.append(block.supersedes)
        for ref in refs:
            if ref in ref_counts:
                ref_counts[ref] += 1

    return ref_counts


def score_block(
    block: Block,
    config: Config,
    changed_files: list[str],
    all_blocks: list[Block],
    *,
    block_path: str = "",
    ref_counts: dict[str, int] | None = None,
) -> float:
    """Score a single block using 4 weighted factors.

    Factors with weight 0 are skipped; their weight is redistributed
    proportionally among non-zero factors.

    Args:
        block_path: Path string for this block (used for dependency_depth).
        ref_counts: Pre-computed reference counts from _build_ref_counts.
            If None, dependency_depth defaults to 0.
    """
    weights = config.weights

    # Compute raw factor values
    factors: dict[str, float] = {}

    # Recency: 1 / (1 + days * 0.1)
    if block.date:
        try:
            block_date = datetime.fromisoformat(block.date).replace(
                tzinfo=timezone.utc
            )
            days = max(0.0, (datetime.now(timezone.utc) - block_date).days)
        except (ValueError, TypeError):
            days = 0.0
        factors["recency"] = 1.0 / (1.0 + days * 0.1)
    else:
        factors["recency"] = 0.5

    # File proximity: 1.0 if any overlap, 0.0 otherwise
    if changed_files and block.files:
        changed_set = set(changed_files)
        factors["file_proximity"] = (
            1.0 if changed_set.intersection(block.files) else 0.0
        )
    else:
        factors["file_proximity"] = 0.0

    # Dependency depth: how many other blocks reference this block's path
    if ref_counts and block_path:
        refs = ref_counts.get(block_path, 0)
        max_refs = max(ref_counts.values()) if ref_counts else 0
        factors["dependency_depth"] = min(1.0, refs / max(1, max_refs))
    else:
        factors["dependency_depth"] = 0.0

    # Category weight: lookup in config
    factors["category"] = config.category_weights.get(block.category, 0.5)

    # Collect non-zero weights and redistribute
    active: dict[str, float] = {
        k: weights.get(k, 0.0) for k in factors if weights.get(k, 0.0) > 0
    }

    total_active_weight = sum(active.values())
    if total_active_weight == 0:
        return 0.0

    score = 0.0
    for key, weight in active.items():
        normalized_weight = weight / total_active_weight
        score += normalized_weight * factors[key]

    return score


def get_changed_files() -> list[str]:
    """Get recently changed files from git diff.

    Tries HEAD~5 down to HEAD~0. Returns empty list on failure.
    """
    for n in range(5, -1, -1):
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", f"HEAD~{n}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                files = [f for f in result.stdout.strip().split("\n") if f]
                return files
        except (subprocess.SubprocessError, OSError):
            continue
    return []


def select_blocks(
    blocks: list[tuple[Path, Block]],
    config: Config,
    tool: str,
) -> list[tuple[Path, Block, float]]:
    """Score, rank, and select blocks that fit within token budget."""
    changed_files = get_changed_files()
    all_block_objs = [b for _, b in blocks]
    all_paths = [str(p) for p, _ in blocks]
    ref_counts = _build_ref_counts(all_block_objs, all_paths)

    scored: list[tuple[Path, Block, float]] = []
    for path, block in blocks:
        s = score_block(
            block,
            config,
            changed_files,
            all_block_objs,
            block_path=str(path),
            ref_counts=ref_counts,
        )
        scored.append((path, block, s))

    scored.sort(key=lambda x: x[2], reverse=True)

    budget = config.budgets.get(tool, config.budgets.get("generic", 2500))
    selected: list[tuple[Path, Block, float]] = []
    tokens_used = 0

    for path, block, s in scored:
        block_tokens = estimate_tokens(block.content)
        if tokens_used + block_tokens <= budget:
            selected.append((path, block, s))
            tokens_used += block_tokens

    return selected


def _content_hash(block: Block) -> str:
    """SHA-256 hash of block content for cache invalidation."""
    return hashlib.sha256(block.content.encode("utf-8")).hexdigest()[:16]


def build_index(vault_path: Path, blocks: list[tuple[Path, Block]]) -> None:
    """Write .index.json with block metadata for fast future reads."""
    entries = []
    for path, block in blocks:
        entries.append(
            {
                "path": str(path),
                "title": block.title,
                "category": block.category,
                "date": block.date,
                "files": block.files,
                "related": block.related,
                "supersedes": block.supersedes,
                "content_hash": _content_hash(block),
            }
        )

    index_path = vault_path / ".index.json"
    index_path.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_index(vault_path: Path) -> dict | None:
    """Read .index.json. Return None if missing or corrupt."""
    index_path = vault_path / ".index.json"
    if not index_path.exists():
        return None
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return None
        return {"blocks": data}
    except (json.JSONDecodeError, OSError):
        return None
