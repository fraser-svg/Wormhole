"""Tests for MultiProjectWatcher."""

from pathlib import Path

import pytest

from wormhole.config import Config, save_config
from wormhole.vault import init_vault
from wormhole.watcher import MultiProjectWatcher


@pytest.fixture
def projects(tmp_path: Path) -> list[dict[str, str]]:
    """Create two fake projects with vaults."""
    paths = []
    for name in ("alpha", "beta"):
        project = tmp_path / name
        project.mkdir()
        init_vault(project)
        paths.append({"path": str(project)})
    return paths


class TestSyncProjects:
    def test_add_watchers(self, projects: list[dict[str, str]]) -> None:
        mw = MultiProjectWatcher()
        mw.sync_projects(projects)
        assert len(mw._watchers) == 2

    def test_remove_watchers(self, projects: list[dict[str, str]]) -> None:
        mw = MultiProjectWatcher()
        mw.sync_projects(projects)
        mw.sync_projects([projects[0]])
        assert len(mw._watchers) == 1

    def test_no_vault_skipped(self, tmp_path: Path) -> None:
        project = tmp_path / "novault"
        project.mkdir()
        mw = MultiProjectWatcher()
        mw.sync_projects([{"path": str(project)}])
        assert len(mw._watchers) == 0

    def test_idempotent(self, projects: list[dict[str, str]]) -> None:
        mw = MultiProjectWatcher()
        mw.sync_projects(projects)
        watcher_ids = {id(w) for w in mw._watchers.values()}
        mw.sync_projects(projects)
        assert {id(w) for w in mw._watchers.values()} == watcher_ids


class TestPollOnce:
    def test_empty(self) -> None:
        mw = MultiProjectWatcher()
        results = mw.poll_once()
        assert results == {}

    def test_no_changes(self, projects: list[dict[str, str]]) -> None:
        mw = MultiProjectWatcher()
        mw.sync_projects(projects)
        results = mw.poll_once()
        assert results == {}
