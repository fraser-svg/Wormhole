"""Base harvester for extracting knowledge blocks from AI transcripts."""

import logging
import re
from datetime import date
from pathlib import Path

from wormhole.config import Config
from wormhole.vault import Block, deduplicate, list_blocks, read_block, write_block

logger = logging.getLogger(__name__)

TRIGGER_PATTERNS: dict[str, list[str]] = {
    "decisions": [
        r"(?:let'?s?\s+go\s+with|the\s+approach\s+is|choosing\s+\w+\s+over)",
        r"(?:decided\s+to|decision\s*:|we(?:'ll|\s+will)\s+use)",
    ],
    "corrections": [
        r"(?:the\s+fix\s+is|that'?s?\s+wrong|bug\s+(?:was|is)\s+in)",
        r"(?:corrected?\s+(?:this|that|the)|should\s+(?:be|have\s+been))",
    ],
    "discoveries": [
        r"(?:found\s+that|turns?\s+out|this\s+works?\s+because)",
        r"(?:TIL|discovered\s+that|the\s+reason\s+is)",
    ],
    "architecture": [
        r"(?:schema\s+(?:is|looks?\s+like)|the\s+flow\s+is|route\s+(?:is|pattern))",
        r"(?:database\s+(?:schema|structure)|API\s+(?:endpoint|route|design))",
    ],
    "failures": [
        r"(?:that\s+didn'?t\s+work|reverting|this\s+(?:approach\s+)?failed)",
        r"(?:tried\s+.+\s+but|doesn'?t\s+work|broken\s+because)",
    ],
}

# Compiled patterns: category -> list of compiled regexes
_COMPILED_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    category: [re.compile(p, re.IGNORECASE) for p in patterns]
    for category, patterns in TRIGGER_PATTERNS.items()
}

# Structural indicators: code blocks, file paths, markdown headings
_STRUCTURAL_RE = re.compile(
    r"(?:```|[a-zA-Z0-9_\-./]+\.[a-zA-Z]{1,10}(?:\s|$|:)|^#{1,4}\s+)",
    re.MULTILINE,
)

_FILE_PATH_RE = re.compile(
    r"(?:[a-zA-Z0-9_\-]+/)+[a-zA-Z0-9_\-]+\.[a-zA-Z]{1,10}"
)


def _extract_paragraph(text: str, match_start: int) -> str:
    """Extract the paragraph containing match_start, plus adjacent code blocks."""
    # Find paragraph boundaries (double newline or start/end of text)
    para_start = text.rfind("\n\n", 0, match_start)
    para_start = 0 if para_start == -1 else para_start + 2

    para_end = text.find("\n\n", match_start)
    para_end = len(text) if para_end == -1 else para_end

    # Expand to include adjacent code blocks
    # Look forward for a code block starting right after this paragraph
    rest = text[para_end:]
    if rest.lstrip("\n").startswith("```"):
        code_end = rest.find("```", rest.find("```") + 3)
        if code_end != -1:
            # Include up to the closing ```
            next_newline = rest.find("\n", code_end + 3)
            extend_to = next_newline if next_newline != -1 else len(rest)
            para_end += extend_to

    # Look backward for a code block ending right before this paragraph
    before = text[:para_start]
    if before.rstrip("\n").endswith("```"):
        code_open = before.rfind("```", 0, len(before) - 3)
        if code_open != -1:
            para_start = code_open

    return text[para_start:para_end].strip()


def _has_structural_context(text: str, match_start: int, window: int = 500) -> bool:
    """Check for structural indicators within `window` chars of match_start."""
    region_start = max(0, match_start - window)
    region_end = min(len(text), match_start + window)
    region = text[region_start:region_end]
    return bool(_STRUCTURAL_RE.search(region))


def _derive_title(content: str) -> str:
    """Derive a short title from the first line or heading of content."""
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Strip markdown heading markers
        if line.startswith("#"):
            line = re.sub(r"^#+\s*", "", line)
        # Strip code fences
        if line.startswith("```"):
            continue
        # Truncate to reasonable title length
        if len(line) > 80:
            line = line[:77] + "..."
        return line
    return "untitled"


class BaseHarvester:
    """Base class for transcript harvesters.

    Subclasses must implement read_transcript() to normalize their
    specific transcript format into a list of message dicts.
    """

    def __init__(self, vault_path: Path, config: Config) -> None:
        self.vault_path = vault_path
        self.config = config
        self.session_id: str = ""
        self.tool_name: str = "generic"

    def read_transcript(self) -> list[dict]:
        """Read and normalize transcript into list of {"role": str, "content": str}.

        Must be implemented by subclasses.
        """
        raise NotImplementedError

    def extract_blocks(self, messages: list[dict]) -> list[Block]:
        """Extract knowledge blocks from normalized messages.

        Scans assistant messages for trigger phrases. When found, extracts
        surrounding context and checks for structural indicators (code blocks,
        file paths, headings) within 500 chars. Scores confidence accordingly.
        """
        blocks: list[Block] = []
        today = date.today().isoformat()
        min_tokens = int(self.config.harvester.get("min_block_tokens", 50))
        max_tokens = int(self.config.harvester.get("max_block_tokens", 1500))

        for msg in messages:
            if msg.get("role") != "assistant":
                continue

            content = msg.get("content", "")
            if not content:
                continue

            # Track which regions we already extracted to avoid overlaps
            extracted_spans: list[tuple[int, int]] = []

            for category, patterns in _COMPILED_PATTERNS.items():
                for pattern in patterns:
                    for match in pattern.finditer(content):
                        # Skip if this region already produced a block
                        match_pos = match.start()
                        if any(s <= match_pos <= e for s, e in extracted_spans):
                            continue

                        # Extract paragraph around the trigger
                        extracted = _extract_paragraph(content, match_pos)
                        if not extracted:
                            continue

                        # Token size gate
                        word_count = len(extracted.split())
                        est_tokens = int(word_count * 1.3)
                        if est_tokens < min_tokens:
                            continue
                        if est_tokens > max_tokens:
                            # Truncate to roughly max_tokens
                            words = extracted.split()
                            max_words = int(max_tokens / 1.3)
                            extracted = " ".join(words[:max_words])

                        # Determine confidence from structural context
                        has_structure = _has_structural_context(
                            content, match_pos
                        )
                        confidence = 0.9 if has_structure else 0.6

                        # Extract file paths mentioned
                        file_refs = _FILE_PATH_RE.findall(extracted)

                        title = _derive_title(extracted)

                        block = Block(
                            title=title,
                            category=category,
                            content=extracted,
                            date=today,
                            session=self.tool_name,
                            source_session_id=self.session_id,
                            confidence=confidence,
                            files=file_refs[:10],  # cap file references
                        )
                        blocks.append(block)

                        # Mark this region as extracted
                        para_start = content.rfind("\n\n", 0, match_pos)
                        para_start = 0 if para_start == -1 else para_start
                        para_end = content.find("\n\n", match_pos)
                        para_end = len(content) if para_end == -1 else para_end
                        extracted_spans.append((para_start, para_end))

        logger.info("Extracted %d candidate blocks from transcript", len(blocks))
        return blocks

    def deduplicate_and_write(
        self, blocks: list[Block]
    ) -> tuple[int, int, int]:
        """Deduplicate against existing vault and write new blocks.

        Returns (written, skipped, staged) counts.
        """
        written = 0
        skipped = 0
        staged = 0

        threshold = float(self.config.harvester.get("dedup_threshold", 0.8))
        confidence_threshold = float(
            self.config.harvester.get("confidence_threshold", 0.8)
        )

        # Load existing blocks grouped by category for dedup
        existing_by_category: dict[str, list[tuple[Path, Block]]] = {}
        for path, blk in list_blocks(self.vault_path):
            cat = blk.category
            if cat not in existing_by_category:
                existing_by_category[cat] = []
            existing_by_category[cat].append((path, blk))

        for block in blocks:
            category = block.category
            existing_in_cat = existing_by_category.get(category, [])
            existing_blocks_only = [b for _, b in existing_in_cat]

            action = deduplicate(block, existing_blocks_only, threshold)

            if action == "skip":
                skipped += 1
                logger.debug("Skipped duplicate block: %s", block.title)
                continue

            if action == "replace":
                # Find and remove the old block file that this replaces
                for old_path, old_block in existing_in_cat:
                    if old_block.category == block.category:
                        old_text = f"{old_block.title} {old_block.content}"
                        new_text = f"{block.title} {block.content}"
                        old_tokens = set(old_text.lower().split())
                        new_tokens = set(new_text.lower().split())
                        overlap = old_tokens & new_tokens
                        union = old_tokens | new_tokens
                        if union and len(overlap) / len(union) > threshold:
                            try:
                                old_path.unlink()
                                logger.info(
                                    "Replaced block: %s -> %s",
                                    old_block.title,
                                    block.title,
                                )
                            except OSError as exc:
                                logger.warning(
                                    "Failed to remove old block %s: %s",
                                    old_path,
                                    exc,
                                )
                            break

            # Write new block: vault or staging based on confidence
            if block.confidence >= confidence_threshold:
                write_block(block, self.vault_path)
                written += 1
                logger.debug("Wrote block: %s (confidence %.2f)", block.title, block.confidence)
            else:
                staging_path = self.vault_path / "staging"
                write_block(block, staging_path)
                staged += 1
                logger.debug(
                    "Staged block: %s (confidence %.2f < %.2f)",
                    block.title,
                    block.confidence,
                    confidence_threshold,
                )

        logger.info(
            "Harvest results: %d written, %d skipped, %d staged",
            written,
            skipped,
            staged,
        )
        return written, skipped, staged

    def harvest(self) -> tuple[int, int, int]:
        """Full harvest pipeline: read, extract, dedup, write.

        Returns (written, skipped, staged) counts.
        """
        last_session = self._get_harvest_state()
        if last_session and last_session == self.session_id and self.session_id:
            logger.info(
                "Session %s already harvested, skipping", self.session_id
            )
            return 0, 0, 0

        messages = self.read_transcript()
        if not messages:
            logger.warning("No messages found in transcript")
            return 0, 0, 0

        blocks = self.extract_blocks(messages)
        if not blocks:
            logger.info("No knowledge blocks extracted")
            return 0, 0, 0

        written, skipped, staged = self.deduplicate_and_write(blocks)

        if self.session_id:
            self._set_harvest_state(self.session_id)

        return written, skipped, staged

    def _get_harvest_state(self) -> str:
        """Read last-harvested session ID from .harvest-state file."""
        state_file = self.vault_path / ".harvest-state"
        if not state_file.exists():
            return ""
        try:
            return state_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("Failed to read harvest state: %s", exc)
            return ""

    def _set_harvest_state(self, session_id: str) -> None:
        """Write session ID to .harvest-state file."""
        state_file = self.vault_path / ".harvest-state"
        try:
            self.vault_path.mkdir(parents=True, exist_ok=True)
            state_file.write_text(session_id + "\n", encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to write harvest state: %s", exc)
