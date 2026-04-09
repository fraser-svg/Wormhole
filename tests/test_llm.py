"""Tests for wormhole.llm — LLM-assisted block extraction (mocked)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from wormhole.config import Config
from wormhole.llm import LLMExtractor


@pytest.fixture()
def config() -> Config:
    cfg = Config()
    cfg.llm["enabled"] = True
    return cfg


@pytest.fixture()
def extractor(config: Config) -> LLMExtractor:
    return LLMExtractor(config)


class TestChunkMessages:
    def test_single_chunk(self, extractor: LLMExtractor) -> None:
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        chunks = extractor.chunk_messages(msgs)
        assert len(chunks) == 1
        assert "[user]: hello" in chunks[0]
        assert "[assistant]: hi there" in chunks[0]

    def test_respects_chunk_size(self, config: Config) -> None:
        config.llm["chunk_size"] = 10  # Very small
        ext = LLMExtractor(config)
        msgs = [
            {"role": "user", "content": "word " * 20},
            {"role": "assistant", "content": "word " * 20},
        ]
        chunks = ext.chunk_messages(msgs)
        assert len(chunks) >= 2

    def test_max_chunks_limit(self, config: Config) -> None:
        config.llm["max_chunks"] = 2
        config.llm["chunk_size"] = 10
        ext = LLMExtractor(config)
        msgs = [{"role": "user", "content": f"msg {i}"} for i in range(50)]
        chunks = ext.chunk_messages(msgs)
        assert len(chunks) <= 2

    def test_empty_messages(self, extractor: LLMExtractor) -> None:
        assert extractor.chunk_messages([]) == []

    def test_oversized_single_message(self, config: Config) -> None:
        config.llm["chunk_size"] = 10
        ext = LLMExtractor(config)
        msgs = [{"role": "assistant", "content": "word " * 100}]
        chunks = ext.chunk_messages(msgs)
        assert len(chunks) >= 1


class TestParseResponse:
    def test_valid_json_array(self, extractor: LLMExtractor) -> None:
        resp = json.dumps([
            {
                "category": "decisions",
                "title": "Use PostgreSQL",
                "content": "Chose PG for concurrency.",
                "confidence": 0.9,
                "files": ["db.py"],
            }
        ])
        result = extractor._parse_response(resp)
        assert len(result) == 1
        assert result[0]["category"] == "decisions"

    def test_strips_markdown_fencing(self, extractor: LLMExtractor) -> None:
        resp = "```json\n" + json.dumps([
            {"category": "corrections", "title": "Fix bug", "content": "Fixed it.", "confidence": 0.8}
        ]) + "\n```"
        result = extractor._parse_response(resp)
        assert len(result) == 1

    def test_rejects_invalid_json(self, extractor: LLMExtractor) -> None:
        assert extractor._parse_response("not json") == []

    def test_rejects_non_array(self, extractor: LLMExtractor) -> None:
        assert extractor._parse_response('{"key": "value"}') == []

    def test_skips_invalid_category(self, extractor: LLMExtractor) -> None:
        resp = json.dumps([
            {"category": "nonsense", "title": "Bad", "content": "Nope."}
        ])
        assert extractor._parse_response(resp) == []

    def test_skips_context_category(self, extractor: LLMExtractor) -> None:
        resp = json.dumps([
            {"category": "context", "title": "Goal", "content": "Project goal."}
        ])
        assert extractor._parse_response(resp) == []

    def test_skips_empty_content(self, extractor: LLMExtractor) -> None:
        resp = json.dumps([
            {"category": "decisions", "title": "Empty", "content": ""}
        ])
        assert extractor._parse_response(resp) == []

    def test_skips_non_dict_items(self, extractor: LLMExtractor) -> None:
        resp = json.dumps(["string item", 42])
        assert extractor._parse_response(resp) == []


class TestExtractBlocks:
    def test_calls_api_and_returns_blocks(self, extractor: LLMExtractor) -> None:
        mock_response = MagicMock()
        mock_text = MagicMock()
        mock_text.text = json.dumps([
            {
                "category": "decisions",
                "title": "Use Redis",
                "content": "Redis for caching.",
                "confidence": 0.85,
                "files": [],
            }
        ])
        mock_response.content = [mock_text]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        extractor._client = mock_client

        messages = [
            {"role": "user", "content": "Should we use Redis?"},
            {"role": "assistant", "content": "Yes, Redis for caching."},
        ]

        blocks = extractor.extract_blocks(messages, session_id="test-123", tool_name="claude")
        assert len(blocks) == 1
        assert blocks[0].title == "Use Redis"
        assert blocks[0].extraction_method == "llm"
        assert blocks[0].confidence == 0.85
        assert blocks[0].source_session_id == "test-123"

    def test_empty_chunks_returns_empty(self, extractor: LLMExtractor) -> None:
        mock_client = MagicMock()
        extractor._client = mock_client
        blocks = extractor.extract_blocks([])
        assert blocks == []
        mock_client.messages.create.assert_not_called()

    def test_api_error_skips_chunk(self, extractor: LLMExtractor) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")
        extractor._client = mock_client

        messages = [{"role": "user", "content": "test"}]
        blocks = extractor.extract_blocks(messages)
        assert blocks == []

    def test_confidence_clamped(self, extractor: LLMExtractor) -> None:
        mock_response = MagicMock()
        mock_text = MagicMock()
        mock_text.text = json.dumps([
            {
                "category": "decisions",
                "title": "Test",
                "content": "Content.",
                "confidence": 1.5,  # Over 1.0
                "files": [],
            }
        ])
        mock_response.content = [mock_text]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        extractor._client = mock_client

        blocks = extractor.extract_blocks([{"role": "user", "content": "x"}])
        assert blocks[0].confidence == 1.0

    def test_title_truncated(self, extractor: LLMExtractor) -> None:
        mock_response = MagicMock()
        mock_text = MagicMock()
        mock_text.text = json.dumps([
            {
                "category": "decisions",
                "title": "A" * 100,
                "content": "Content.",
                "confidence": 0.9,
            }
        ])
        mock_response.content = [mock_text]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        extractor._client = mock_client

        blocks = extractor.extract_blocks([{"role": "user", "content": "x"}])
        assert len(blocks[0].title) <= 80


class TestGetClient:
    def test_missing_api_key_raises(self, extractor: LLMExtractor) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                extractor._get_client()

    def test_missing_package_raises(self, extractor: LLMExtractor) -> None:
        with patch.dict("sys.modules", {"anthropic": None}):
            with pytest.raises(ImportError):
                extractor._client = None
                extractor._get_client()
