"""Comprehensive tests for Wormhole Phase 1."""

import os
import textwrap
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from wormhole.cli import main
from wormhole.compiler_base import SENTINEL_END, SENTINEL_START, BaseCompiler
from wormhole.compiler_claude import ClaudeCompiler
from wormhole.compiler_cursor import CursorCompiler
from wormhole.config import Config, load_config, save_config
from wormhole.harvester_base import BaseHarvester
from wormhole.harvester_claude import ClaudeHarvester
from wormhole.manifest import build_manifest
from wormhole.scoring import get_changed_files, score_block, select_blocks
from wormhole.utils import estimate_tokens, format_error, sanitize_slug, validate_path_within
from wormhole.vault import Block, deduplicate, list_blocks, parse_filename, read_block, write_block


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """Create a minimal vault directory structure."""
    vault_path = tmp_path / ".wormhole"
    vault_path.mkdir()
    for subdir in [
        "decisions",
        "corrections",
        "discoveries",
        "architecture",
        "failures",
        "context",
        "staging",
    ]:
        (vault_path / subdir).mkdir()
    return vault_path


@pytest.fixture()
def sample_block() -> Block:
    """A reusable sample block."""
    return Block(
        title="Use PostgreSQL over SQLite",
        category="decisions",
        content="We chose PostgreSQL for production because of concurrency requirements.",
        date=date.today().isoformat(),
        session="claude",
        files=["src/db.py", "config/database.yaml"],
        confidence=1.0,
    )


@pytest.fixture()
def config() -> Config:
    """Default config."""
    return Config()


# ===========================================================================
# utils.py tests
# ===========================================================================


class TestEstimateTokens:
    def test_known_text(self) -> None:
        text = "the quick brown fox jumps over the lazy dog"
        tokens = estimate_tokens(text)
        # 9 words * 1.3 = 11.7 -> 11
        assert tokens == 11

    def test_empty(self) -> None:
        assert estimate_tokens("") == 0

    def test_single_word(self) -> None:
        assert estimate_tokens("hello") == 1


class TestSanitizeSlug:
    def test_spaces(self) -> None:
        assert sanitize_slug("Hello World") == "hello-world"

    def test_special_chars(self) -> None:
        assert sanitize_slug("Use @postgres! (v15)") == "use-postgres-v15"

    def test_uppercase(self) -> None:
        assert sanitize_slug("ALLCAPS") == "allcaps"

    def test_multiple_hyphens_collapsed(self) -> None:
        assert sanitize_slug("a---b") == "a-b"

    def test_leading_trailing_stripped(self) -> None:
        assert sanitize_slug("--trimmed--") == "trimmed"


class TestValidatePathWithin:
    def test_valid_child(self, tmp_path: Path) -> None:
        child = tmp_path / "sub" / "file.txt"
        assert validate_path_within(child, tmp_path) is True

    def test_path_traversal(self, tmp_path: Path) -> None:
        malicious = tmp_path / ".." / "etc" / "passwd"
        assert validate_path_within(malicious, tmp_path) is False

    def test_exact_root(self, tmp_path: Path) -> None:
        assert validate_path_within(tmp_path, tmp_path) is True


class TestFormatError:
    def test_format(self) -> None:
        result = format_error("File missing", "Not found on disk", "Check path")
        assert result == "Error: File missing. Not found on disk. Check path."


# ===========================================================================
# config.py tests
# ===========================================================================


class TestConfig:
    def test_load_defaults(self, tmp_path: Path) -> None:
        """No config file -> default Config."""
        cfg = load_config(tmp_path)
        assert cfg.ttl == 90
        assert "claude" in cfg.budgets
        assert cfg.budgets["claude"] == 8000

    def test_load_valid_config(self, tmp_path: Path) -> None:
        """Valid YAML overrides specific fields, keeps others default."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"ttl": 30, "budgets": {"claude": 4000}}),
            encoding="utf-8",
        )
        cfg = load_config(tmp_path)
        assert cfg.ttl == 30
        assert cfg.budgets["claude"] == 4000
        # Unset defaults preserved
        assert cfg.budgets["cursor"] == 2000

    def test_load_invalid_yaml(self, tmp_path: Path) -> None:
        """Malformed YAML -> defaults without crash."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("{{{{bad yaml::::", encoding="utf-8")
        cfg = load_config(tmp_path)
        assert cfg.ttl == 90

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """Save config, load it back, verify match."""
        original = Config(ttl=45, default_tool="claude")
        save_config(original, tmp_path)
        loaded = load_config(tmp_path)
        assert loaded.ttl == 45
        assert loaded.default_tool == "claude"
        assert loaded.budgets == original.budgets


# ===========================================================================
# vault.py tests
# ===========================================================================


class TestVaultReadWrite:
    def test_write_and_read_block(self, vault: Path, sample_block: Block) -> None:
        path = write_block(sample_block, vault)
        assert path.exists()

        loaded = read_block(path)
        assert loaded is not None
        assert loaded.title == sample_block.title
        assert loaded.category == sample_block.category
        assert loaded.content == sample_block.content
        assert loaded.date == sample_block.date
        assert loaded.files == sample_block.files

    def test_read_missing_block(self, tmp_path: Path) -> None:
        result = read_block(tmp_path / "nonexistent.md")
        assert result is None

    def test_read_malformed_frontmatter(self, vault: Path) -> None:
        bad_file = vault / "decisions" / "bad.md"
        bad_file.write_text("no frontmatter here", encoding="utf-8")
        assert read_block(bad_file) is None

    def test_read_malformed_yaml_frontmatter(self, vault: Path) -> None:
        bad_file = vault / "decisions" / "bad-yaml.md"
        bad_file.write_text("---\n{{bad yaml\n---\ncontent", encoding="utf-8")
        assert read_block(bad_file) is None


class TestListBlocks:
    def test_list_blocks(self, vault: Path) -> None:
        """Write 3 blocks in 2 categories, list all, list filtered."""
        blocks = [
            Block(title="Decision A", category="decisions", content="A", date="2025-01-01"),
            Block(title="Decision B", category="decisions", content="B", date="2025-01-02"),
            Block(title="Fix C", category="corrections", content="C", date="2025-01-03"),
        ]
        for b in blocks:
            write_block(b, vault)

        all_blocks = list_blocks(vault)
        assert len(all_blocks) == 3

        decisions_only = list_blocks(vault, category="decisions")
        assert len(decisions_only) == 2

        corrections_only = list_blocks(vault, category="corrections")
        assert len(corrections_only) == 1


class TestParseFilename:
    def test_dated(self) -> None:
        result = parse_filename("2025-04-08--auth-strategy--session-cookies.md")
        assert result == {
            "date": "2025-04-08",
            "topic": "auth-strategy",
            "slug": "session-cookies",
        }

    def test_undated(self) -> None:
        result = parse_filename("architecture--system-overview.md")
        assert result == {
            "date": "",
            "topic": "architecture",
            "slug": "system-overview",
        }


class TestDeduplicate:
    def test_accept_different_blocks(self) -> None:
        new = Block(
            title="Use Redis for caching",
            category="decisions",
            content="Redis provides fast key-value storage for our caching layer.",
        )
        existing = [
            Block(
                title="Use PostgreSQL",
                category="decisions",
                content="PostgreSQL chosen for relational data persistence needs.",
            )
        ]
        assert deduplicate(new, existing) == "accept"

    def test_skip_nearly_identical(self) -> None:
        content = "We chose PostgreSQL for production because of concurrency."
        new = Block(title="Use PostgreSQL", category="decisions", content=content)
        existing = [
            Block(
                title="Use PostgreSQL",
                category="decisions",
                content=content + " It handles concurrent writes well.",
            )
        ]
        result = deduplicate(new, existing, threshold=0.6)
        # Existing has more tokens -> "skip"
        assert result == "skip"

    def test_replace_when_new_has_more(self) -> None:
        short_content = "We chose PostgreSQL for production."
        long_content = "We chose PostgreSQL for production. It handles concurrent writes and provides ACID compliance."
        existing = [
            Block(title="Use PostgreSQL", category="decisions", content=short_content)
        ]
        new = Block(title="Use PostgreSQL", category="decisions", content=long_content)
        result = deduplicate(new, existing, threshold=0.3)
        assert result == "replace"


class TestPathTraversalPrevention:
    def test_malicious_slug(self, vault: Path) -> None:
        block = Block(
            title="../../etc/passwd",
            category="decisions",
            content="malicious content",
            date="2025-01-01",
        )
        # sanitize_slug will clean the title, so the path stays within vault
        path = write_block(block, vault)
        assert validate_path_within(path, vault)


# ===========================================================================
# scoring.py tests
# ===========================================================================


class TestScoring:
    def test_score_block_recency(self, config: Config) -> None:
        """Recent block scores higher than old block."""
        today = date.today().isoformat()
        old_date = (date.today() - timedelta(days=60)).isoformat()

        recent = Block(title="Recent", category="decisions", content="x", date=today)
        old = Block(title="Old", category="decisions", content="x", date=old_date)

        score_recent = score_block(recent, config, [], [])
        score_old = score_block(old, config, [], [])
        assert score_recent > score_old

    def test_score_block_file_proximity(self, config: Config) -> None:
        """Block matching changed files scores higher."""
        block_with_match = Block(
            title="A",
            category="decisions",
            content="x",
            date=date.today().isoformat(),
            files=["src/main.py"],
        )
        block_no_match = Block(
            title="B",
            category="decisions",
            content="x",
            date=date.today().isoformat(),
            files=["src/other.py"],
        )

        changed = ["src/main.py"]
        score_match = score_block(block_with_match, config, changed, [])
        score_no = score_block(block_no_match, config, changed, [])
        assert score_match > score_no

    def test_score_block_category_weight(self, config: Config) -> None:
        """context (1.0) > decisions (0.9) > discoveries (0.6)."""
        today = date.today().isoformat()
        ctx = Block(title="A", category="context", content="x", date=today)
        dec = Block(title="B", category="decisions", content="x", date=today)
        disc = Block(title="C", category="discoveries", content="x", date=today)

        s_ctx = score_block(ctx, config, [], [])
        s_dec = score_block(dec, config, [], [])
        s_disc = score_block(disc, config, [], [])
        assert s_ctx > s_dec > s_disc

    def test_select_blocks_budget(self, vault: Path, config: Config) -> None:
        """Selection respects token budget."""
        # Create blocks with known content sizes
        for i in range(10):
            block = Block(
                title=f"Block {i}",
                category="decisions",
                content="word " * 200,  # ~260 tokens each
                date=date.today().isoformat(),
            )
            write_block(block, vault)

        all_blocks = list_blocks(vault)
        # Set a small budget that can only fit a few blocks
        config.budgets["generic"] = 500
        with patch("wormhole.scoring.get_changed_files", return_value=[]):
            selected = select_blocks(all_blocks, config, "generic")

        total_tokens = sum(estimate_tokens(b.content) for _, b, _ in selected)
        assert total_tokens <= 500
        assert len(selected) < 10

    def test_get_changed_files_no_git(self, tmp_path: Path) -> None:
        """Returns empty list when not in git repo."""
        with patch("subprocess.run", side_effect=OSError("no git")):
            result = get_changed_files()
            assert result == []


# ===========================================================================
# manifest.py tests
# ===========================================================================


class TestManifest:
    def test_build_manifest(self, vault: Path) -> None:
        blocks_data = [
            Block(title="Dec A", category="decisions", content="a", date="2025-01-01"),
            Block(title="Corr B", category="corrections", content="b", date="2025-01-02"),
        ]
        pairs: list[tuple[Path, Block]] = []
        for b in blocks_data:
            p = write_block(b, vault)
            pairs.append((p, b))

        manifest = build_manifest(vault, pairs)
        assert "Wormhole Vault Manifest" in manifest
        assert "Decisions (1)" in manifest
        assert "Corrections (1)" in manifest
        assert "Total: 2 blocks" in manifest

    def test_build_manifest_empty(self, vault: Path) -> None:
        manifest = build_manifest(vault, [])
        assert "Wormhole Vault Manifest" in manifest
        assert "Total: 0 blocks" in manifest


# ===========================================================================
# compiler tests
# ===========================================================================


class TestCompiler:
    def test_compile_with_blocks(self, vault: Path, config: Config) -> None:
        block = Block(
            title="Auth Strategy",
            category="decisions",
            content="Use JWT tokens for authentication across all services.",
            date=date.today().isoformat(),
        )
        write_block(block, vault)

        compiler = ClaudeCompiler(vault, config)
        with patch("wormhole.scoring.get_changed_files", return_value=[]):
            output = compiler.compile()

        assert "Project Memory" in output
        assert len(output) > 100

    def test_compile_empty_vault(self, vault: Path, config: Config) -> None:
        compiler = ClaudeCompiler(vault, config)
        with patch("wormhole.scoring.get_changed_files", return_value=[]):
            output = compiler.compile()

        assert "Project Memory" in output
        assert "Vault Manifest" in output

    def test_write_preserves_existing(self, vault: Path, config: Config, tmp_path: Path) -> None:
        """Write to file with existing content, verify sentinel markers preserve it."""
        output_file = tmp_path / "CLAUDE.md"
        existing_content = "# My Existing Rules\n\nDo not touch this.\n"
        output_file.write_text(existing_content, encoding="utf-8")

        compiler = ClaudeCompiler(vault, config)
        with patch("wormhole.scoring.get_changed_files", return_value=[]):
            compiler.write(output_file)

        result = output_file.read_text(encoding="utf-8")
        assert "My Existing Rules" in result
        assert SENTINEL_START in result
        assert SENTINEL_END in result

    def test_write_creates_new_file(self, vault: Path, config: Config, tmp_path: Path) -> None:
        output_file = tmp_path / "NEW_FILE.md"
        assert not output_file.exists()

        compiler = ClaudeCompiler(vault, config)
        with patch("wormhole.scoring.get_changed_files", return_value=[]):
            compiler.write(output_file)

        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        assert SENTINEL_START in content
        assert SENTINEL_END in content

    def test_claude_compiler_output_path(self, vault: Path, config: Config) -> None:
        compiler = ClaudeCompiler(vault, config)
        with patch("wormhole.scoring.get_changed_files", return_value=[]):
            # write() with no args defaults to CLAUDE.md in parent of vault
            compiler.write()
        expected = vault.parent / "CLAUDE.md"
        assert expected.exists()

    def test_cursor_compiler_output_path(self, vault: Path, config: Config) -> None:
        compiler = CursorCompiler(vault, config)
        with patch("wormhole.scoring.get_changed_files", return_value=[]):
            compiler.write()
        expected = vault.parent / ".cursorrules"
        assert expected.exists()


# ===========================================================================
# harvester tests
# ===========================================================================


class _FakeHarvester(BaseHarvester):
    """Concrete harvester that accepts messages directly for testing."""

    def __init__(self, vault_path: Path, config: Config, messages: list[dict]) -> None:
        super().__init__(vault_path, config)
        self._messages = messages
        self.tool_name = "test"
        self.session_id = "test-session-001"

    def read_transcript(self) -> list[dict]:
        return self._messages


class TestHarvesterExtraction:
    def test_extract_decisions(self, vault: Path, config: Config) -> None:
        messages = [
            {
                "role": "assistant",
                "content": (
                    "After analyzing all the available options and considering our requirements "
                    "for scalability and reliability, let's go with PostgreSQL for the database "
                    "layer. This gives us better concurrency support than SQLite for production "
                    "workloads, and it has excellent support for JSON columns and full-text search "
                    "which we will need for the search feature.\n\n"
                    "```python\nDATABASE_URL = \"postgresql://localhost/myapp\"\n```\n"
                ),
            }
        ]
        harvester = _FakeHarvester(vault, config, messages)
        blocks = harvester.extract_blocks(messages)
        categories = [b.category for b in blocks]
        assert "decisions" in categories

    def test_extract_corrections(self, vault: Path, config: Config) -> None:
        messages = [
            {
                "role": "assistant",
                "content": (
                    "The fix is in the auth middleware at src/auth/middleware.py where "
                    "there was a wrong comparison operator being used for the token expiry "
                    "check. I changed the operator from less-than to less-than-or-equal so "
                    "that tokens expiring at exactly the current timestamp are still considered "
                    "valid. This was causing intermittent authentication failures for users "
                    "whose sessions were expiring right at the boundary.\n\n"
                    "```python\nif token.expiry <= now:\n    raise ExpiredToken()\n```\n"
                ),
            }
        ]
        harvester = _FakeHarvester(vault, config, messages)
        blocks = harvester.extract_blocks(messages)
        categories = [b.category for b in blocks]
        assert "corrections" in categories

    def test_extract_failures(self, vault: Path, config: Config) -> None:
        messages = [
            {
                "role": "assistant",
                "content": (
                    "That didn't work because the Redis connection pool was completely "
                    "exhausted under heavy load conditions. We need to increase the "
                    "max_connections setting or implement proper connection recycling with "
                    "a timeout mechanism. The current configuration in config/redis.yaml "
                    "only allows ten concurrent connections which is far too low for our "
                    "production traffic patterns during peak hours.\n"
                ),
            }
        ]
        harvester = _FakeHarvester(vault, config, messages)
        blocks = harvester.extract_blocks(messages)
        categories = [b.category for b in blocks]
        assert "failures" in categories

    def test_no_false_positives(self, vault: Path, config: Config) -> None:
        """Conversational message without structural context -> no extraction."""
        messages = [
            {
                "role": "assistant",
                "content": "Actually, I was thinking about lunch. What do you want to eat?",
            }
        ]
        harvester = _FakeHarvester(vault, config, messages)
        blocks = harvester.extract_blocks(messages)
        assert len(blocks) == 0

    def test_confidence_with_structure(self, vault: Path, config: Config) -> None:
        """Trigger + code block -> confidence >= 0.8."""
        messages = [
            {
                "role": "assistant",
                "content": (
                    "After evaluating several creational patterns and considering the "
                    "complexity of our service initialization logic, let's go with the "
                    "factory pattern for service initialization. This gives us a clean "
                    "separation between the instantiation logic and the business logic "
                    "that consumes these services throughout the application.\n\n"
                    "```python\n"
                    "class ServiceFactory:\n"
                    "    def create(self, name: str) -> Service:\n"
                    "        return _registry[name]()\n"
                    "```\n"
                ),
            }
        ]
        harvester = _FakeHarvester(vault, config, messages)
        blocks = harvester.extract_blocks(messages)
        assert len(blocks) > 0
        assert all(b.confidence >= 0.8 for b in blocks)

    def test_confidence_without_structure(self, vault: Path, config: Config) -> None:
        """Trigger only, no code block/file path -> confidence < 0.8."""
        # Need enough words to pass min_block_tokens (50 tokens ~ 38 words)
        filler = " ".join(["important"] * 40)
        messages = [
            {
                "role": "assistant",
                "content": f"We decided to use the monorepo approach for the project. {filler}",
            }
        ]
        harvester = _FakeHarvester(vault, config, messages)
        blocks = harvester.extract_blocks(messages)
        # If extracted, confidence should be low since no structural context
        for b in blocks:
            assert b.confidence < 0.8

    def test_deduplicate_and_write(self, vault: Path, config: Config) -> None:
        messages = [
            {
                "role": "assistant",
                "content": textwrap.dedent("""\
                    Let's go with Redis for the caching layer.

                    ```python
                    CACHE_BACKEND = "redis://localhost:6379/0"
                    ```

                    It provides sub-millisecond latency for cache lookups.
                """),
            }
        ]
        harvester = _FakeHarvester(vault, config, messages)
        blocks = harvester.extract_blocks(messages)
        written, skipped, staged = harvester.deduplicate_and_write(blocks)
        assert written + staged == len(blocks)
        assert skipped == 0

    def test_harvest_idempotency(self, vault: Path, config: Config) -> None:
        """Harvest same session twice -> second time skips via session state."""
        messages = [
            {
                "role": "assistant",
                "content": (
                    "After benchmarking both REST and gRPC approaches for our internal "
                    "microservice communication layer, let's go with gRPC for service "
                    "communication. The protobuf serialization provides significantly "
                    "better performance than JSON over REST for high-throughput internal "
                    "service calls between our backend components.\n\n"
                    "```protobuf\n"
                    "service UserService {\n"
                    "    rpc GetUser (GetUserRequest) returns (User);\n"
                    "}\n"
                    "```\n"
                ),
            }
        ]
        harvester = _FakeHarvester(vault, config, messages)

        w1, s1, st1 = harvester.harvest()
        assert w1 + st1 > 0

        # Second harvest with same session_id -> all zeros
        w2, s2, st2 = harvester.harvest()
        assert (w2, s2, st2) == (0, 0, 0)


# ===========================================================================
# CLI tests (Click CliRunner)
# ===========================================================================


class TestCLI:
    def test_init_creates_structure(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            result = runner.invoke(main, ["init"])
            assert result.exit_code == 0

            vault = Path(td) / ".wormhole"
            assert vault.is_dir()
            for subdir in [
                "decisions",
                "corrections",
                "discoveries",
                "architecture",
                "failures",
                "context",
                "staging",
            ]:
                assert (vault / subdir).is_dir(), f"Missing subdir: {subdir}"
            assert (vault / "config.yaml").exists()

    def test_init_already_exists(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(main, ["init"])
            result = runner.invoke(main, ["init"])
            assert result.exit_code == 1

    def test_status_empty_vault(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            runner.invoke(main, ["init"])
            result = runner.invoke(main, ["status"])
            # init creates 1 example block, but status should work
            assert result.exit_code == 0

    def test_boot_no_init(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["boot", "claude"])
            assert result.exit_code == 2

    def test_new_block(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            # Unset EDITOR so subprocess doesn't try to launch one
            env = os.environ.copy()
            env.pop("EDITOR", None)
            runner.invoke(main, ["init"], env=env)
            result = runner.invoke(main, ["new", "decisions", "My Decision"], env=env)
            assert result.exit_code == 0

            # Verify file was created with frontmatter
            vault = Path(td) / ".wormhole"
            decision_files = list((vault / "decisions").glob("*my-decision*"))
            assert len(decision_files) >= 1
            block = read_block(decision_files[0])
            assert block is not None
            assert block.title == "My Decision"
            assert block.category == "decisions"
