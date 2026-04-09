"""LLM-assisted block extraction using Anthropic API."""

import json
import logging
import os
from typing import Any

from wormhole.config import Config
from wormhole.redact import redact_secrets
from wormhole.utils import estimate_tokens
from wormhole.vault import VALID_CATEGORIES, Block

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a knowledge extraction assistant for a software project vault.

Given a conversation between a developer and an AI coding assistant, extract
knowledge blocks that capture important decisions, corrections, discoveries,
architecture choices, and failures.

Each block belongs to exactly one category:
- decisions: Technical choices made ("we chose PostgreSQL because...", "going with React")
- corrections: Bug fixes and corrections ("the bug was in...", "fixed by changing...")
- discoveries: Learnings and insights ("turns out the API...", "found that...")
- architecture: System design ("the schema looks like...", "data flows from...")
- failures: Failed approaches ("tried X but it didn't work because...")
- context: Project goals and overview (rarely extracted, usually manual)

Return a JSON array of objects. Each object has:
- "category": one of the categories above
- "title": short descriptive title (under 80 chars)
- "content": the full knowledge block content (markdown)
- "confidence": float 0.0-1.0, how confident this is real knowledge (not chit-chat)
- "files": list of file paths mentioned (empty list if none)

Only extract genuine knowledge. Skip casual conversation, greetings, and
tool-use mechanics. Focus on decisions, reasoning, and learnings that would
be valuable to recall in future sessions.

Return ONLY valid JSON. No markdown fencing, no explanation outside the array.
If no knowledge blocks are found, return an empty array: []
"""


class LLMExtractor:
    """Extract knowledge blocks using Anthropic Haiku."""

    def __init__(self, config: Config) -> None:
        self.llm_config = config.llm
        self.model = str(self.llm_config.get("model", "claude-haiku-4-5-20251001"))
        self.chunk_size = int(self.llm_config.get("chunk_size", 4000))
        self.max_chunks = int(self.llm_config.get("max_chunks", 20))
        self.temperature = float(self.llm_config.get("temperature", 0.0))
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-load Anthropic client. Raises ImportError or ValueError."""
        if self._client is not None:
            return self._client

        try:
            import anthropic  # type: ignore[import-untyped]
        except ImportError:
            raise ImportError(
                "anthropic package not installed. "
                "Install with: pip install wormhole-ai[llm]"
            )

        api_key_env = str(self.llm_config.get("api_key_env", "ANTHROPIC_API_KEY"))
        api_key = os.environ.get(api_key_env, "")
        if not api_key:
            raise ValueError(
                f"LLM extraction enabled but {api_key_env} environment variable "
                f"is not set. Set it or disable LLM: wormhole config set llm.enabled false"
            )

        self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def chunk_messages(self, messages: list[dict]) -> list[str]:
        """Split messages into chunks on message boundaries.

        Each chunk stays under chunk_size tokens. If a single message
        exceeds chunk_size, it gets its own chunk (split at paragraphs).
        """
        chunks: list[str] = []
        current_lines: list[str] = []
        current_tokens = 0

        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            line = f"[{role}]: {content}"
            line_tokens = estimate_tokens(line)

            if current_tokens + line_tokens > self.chunk_size and current_lines:
                chunks.append("\n\n".join(current_lines))
                current_lines = []
                current_tokens = 0

            # Single message exceeds chunk size — give it its own chunk
            if line_tokens > self.chunk_size:
                if current_lines:
                    chunks.append("\n\n".join(current_lines))
                    current_lines = []
                    current_tokens = 0
                # Truncate to chunk_size worth of words
                words = line.split()
                max_words = int(self.chunk_size / 1.3)
                chunks.append(" ".join(words[:max_words]))
                continue

            current_lines.append(line)
            current_tokens += line_tokens

        if current_lines:
            chunks.append("\n\n".join(current_lines))

        # Respect max_chunks limit
        return chunks[: self.max_chunks]

    def extract_blocks(
        self, messages: list[dict], session_id: str = "", tool_name: str = ""
    ) -> list[Block]:
        """Send message chunks to LLM and parse block responses.

        Returns list of Blocks with extraction_method="llm".
        Raises on auth/import errors. Skips individual chunk failures.
        """
        client = self._get_client()
        chunks = self.chunk_messages(messages)
        if not chunks:
            return []

        from datetime import date as date_mod

        today = date_mod.today().isoformat()
        all_blocks: list[Block] = []

        for i, chunk in enumerate(chunks):
            redacted = redact_secrets(chunk)
            try:
                response = client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    temperature=self.temperature,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": redacted}],
                )
            except Exception as exc:
                logger.warning(
                    "LLM extraction failed on chunk %d/%d: %s",
                    i + 1,
                    len(chunks),
                    exc,
                )
                continue

            # Extract text from response
            text = ""
            for content_block in response.content:
                if hasattr(content_block, "text"):
                    text += content_block.text

            parsed = self._parse_response(text)
            for item in parsed:
                block = Block(
                    title=item.get("title", "untitled")[:80],
                    category=item["category"],
                    content=item.get("content", ""),
                    date=today,
                    session=tool_name,
                    source_session_id=session_id,
                    confidence=max(0.0, min(1.0, float(item.get("confidence", 0.7)))),
                    files=item.get("files", [])[:10],
                    extraction_method="llm",
                )
                all_blocks.append(block)

        logger.info("LLM extracted %d blocks from %d chunks", len(all_blocks), len(chunks))
        return all_blocks

    def _parse_response(self, text: str) -> list[dict]:
        """Parse LLM JSON response, validating each block."""
        text = text.strip()
        # Strip markdown fencing if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3].strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("LLM returned invalid JSON: %s", exc)
            return []

        if not isinstance(data, list):
            logger.warning("LLM returned non-array JSON")
            return []

        valid: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            category = item.get("category", "")
            if category not in VALID_CATEGORIES or category == "context":
                continue
            if not item.get("content"):
                continue
            valid.append(item)

        return valid
