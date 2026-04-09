"""Tests for MCP server implementation functions."""

import json
from pathlib import Path

import pytest

from wormhole.config import GLOBAL_DIR
from wormhole.mcp_server import (
    _get_block_impl,
    _list_projects_impl,
    _query_vault_impl,
    _search_vault_impl,
    install_mcp_config,
)
from wormhole.vault import Block, init_vault, write_block


@pytest.fixture
def project_with_blocks(tmp_path: Path) -> Path:
    """Create a project with some knowledge blocks."""
    project = tmp_path / "myproject"
    project.mkdir()
    vault_path = init_vault(project)

    write_block(
        Block(
            title="Use PostgreSQL",
            category="decisions",
            content="We chose PostgreSQL for its JSONB support.",
            date="2026-04-01",
            session="claude",
            confidence=0.9,
        ),
        vault_path,
    )
    write_block(
        Block(
            title="Auth middleware bug",
            category="failures",
            content="Token expiry check used < instead of <=. Fixed.",
            date="2026-04-02",
            session="claude",
            confidence=0.85,
        ),
        vault_path,
    )
    write_block(
        Block(
            title="API schema",
            category="architecture",
            content="REST API uses /api/v1 prefix. OpenAPI spec in docs/.",
            session="manual",
            confidence=1.0,
        ),
        vault_path,
    )

    return project


class TestQueryVault:
    def test_list_all(self, project_with_blocks: Path) -> None:
        results = _query_vault_impl(str(project_with_blocks))
        # 3 blocks we added + 2 from init (project-goal, example-decision)
        assert len(results) >= 3

    def test_filter_by_category(self, project_with_blocks: Path) -> None:
        results = _query_vault_impl(str(project_with_blocks), category="decisions")
        titles = [r["title"] for r in results]
        assert "Use PostgreSQL" in titles

    def test_filter_by_query(self, project_with_blocks: Path) -> None:
        results = _query_vault_impl(str(project_with_blocks), query="PostgreSQL")
        assert len(results) == 1
        assert results[0]["title"] == "Use PostgreSQL"

    def test_invalid_category(self, project_with_blocks: Path) -> None:
        results = _query_vault_impl(str(project_with_blocks), category="invalid")
        assert results == []

    def test_nonexistent_project(self, tmp_path: Path) -> None:
        results = _query_vault_impl(str(tmp_path / "nope"))
        assert results == []


class TestGetBlock:
    def test_found(self, project_with_blocks: Path) -> None:
        result = _get_block_impl(str(project_with_blocks), "Use PostgreSQL")
        assert result is not None
        assert result["title"] == "Use PostgreSQL"
        assert "JSONB" in result["content"]

    def test_case_insensitive(self, project_with_blocks: Path) -> None:
        result = _get_block_impl(str(project_with_blocks), "use postgresql")
        assert result is not None

    def test_not_found(self, project_with_blocks: Path) -> None:
        result = _get_block_impl(str(project_with_blocks), "Nonexistent Block")
        assert result is None


class TestSearchVault:
    def test_regex_match(self, project_with_blocks: Path) -> None:
        results = _search_vault_impl(str(project_with_blocks), r"PostgreSQL|OpenAPI")
        titles = [r["title"] for r in results]
        assert "Use PostgreSQL" in titles
        assert "API schema" in titles

    def test_no_match(self, project_with_blocks: Path) -> None:
        results = _search_vault_impl(str(project_with_blocks), r"zzzznotfound")
        assert results == []

    def test_invalid_regex(self, project_with_blocks: Path) -> None:
        results = _search_vault_impl(str(project_with_blocks), r"[invalid")
        assert results == []


class TestListProjects:
    def test_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        global_dir = tmp_path / ".wormhole"
        global_dir.mkdir()
        monkeypatch.setattr("wormhole.config.GLOBAL_DIR", global_dir)
        monkeypatch.setattr("wormhole.project_registry.GLOBAL_DIR", global_dir)
        from wormhole.project_registry import ProjectRegistry
        monkeypatch.setattr(ProjectRegistry, "REGISTRY_FILE", global_dir / "projects.json")

        results = _list_projects_impl()
        assert results == []


class TestInstallMcpConfig:
    def test_fresh_install(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        claude_config = tmp_path / ".claude.json"
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        result = install_mcp_config()
        assert result is True
        data = json.loads(claude_config.read_text(encoding="utf-8"))
        assert "wormhole" in data["mcpServers"]

    def test_already_registered(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        claude_config = tmp_path / ".claude.json"
        claude_config.write_text(
            json.dumps({"mcpServers": {"wormhole": {"command": "wormhole"}}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        result = install_mcp_config()
        assert result is False
