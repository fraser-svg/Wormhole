"""Tests for project_registry module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wormhole.config import GLOBAL_DIR, GlobalConfig
from wormhole.project_registry import ProjectRegistry, TrackedProject


@pytest.fixture
def registry_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override GLOBAL_DIR and HOME for isolated registry tests."""
    global_dir = tmp_path / ".wormhole"
    global_dir.mkdir()
    monkeypatch.setattr("wormhole.config.GLOBAL_DIR", global_dir)
    monkeypatch.setattr("wormhole.project_registry.GLOBAL_DIR", global_dir)
    monkeypatch.setattr(ProjectRegistry, "REGISTRY_FILE", global_dir / "projects.json")
    return tmp_path


class TestCRUD:
    def test_add_and_list(self, registry_home: Path) -> None:
        reg = ProjectRegistry()
        assert reg.list_projects() == []

        tp = reg.add_project("/tmp/myproject", tool="claude")
        assert tp.path == "/tmp/myproject"
        assert tp.tool == "claude"
        assert len(reg.list_projects()) == 1

    def test_add_duplicate(self, registry_home: Path) -> None:
        reg = ProjectRegistry()
        reg.add_project("/tmp/myproject")
        reg.add_project("/tmp/myproject")
        assert len(reg.list_projects()) == 1

    def test_remove(self, registry_home: Path) -> None:
        reg = ProjectRegistry()
        reg.add_project("/tmp/a")
        reg.add_project("/tmp/b")
        reg.remove_project("/tmp/a")
        paths = [p.path for p in reg.list_projects()]
        assert "/tmp/a" not in paths
        assert "/tmp/b" in paths

    def test_remove_nonexistent(self, registry_home: Path) -> None:
        reg = ProjectRegistry()
        reg.remove_project("/tmp/nope")  # Should not raise

    def test_has_project(self, registry_home: Path) -> None:
        reg = ProjectRegistry()
        reg.add_project("/tmp/x")
        assert reg.has_project("/tmp/x")
        assert not reg.has_project("/tmp/y")

    def test_persistence(self, registry_home: Path) -> None:
        reg1 = ProjectRegistry()
        reg1.add_project("/tmp/persist", tool="cursor")

        reg2 = ProjectRegistry()
        projects = reg2.list_projects()
        assert len(projects) == 1
        assert projects[0].path == "/tmp/persist"
        assert projects[0].tool == "cursor"


class TestReverseMangling:
    def test_rejects_dotdot(self, registry_home: Path) -> None:
        reg = ProjectRegistry()
        result = reg._reverse_mangle("foo-..-..-etc")
        assert result is None

    def test_nonexistent_returns_none(self, registry_home: Path) -> None:
        reg = ProjectRegistry()
        result = reg._reverse_mangle("nonexistent-path-xyz-abc")
        assert result is None

    def test_rejects_path_outside_home(self, registry_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: Path("/nonexistent/fakehome"))
        reg = ProjectRegistry()
        # /tmp exists but is not under /nonexistent/fakehome
        result = reg._reverse_mangle("tmp")
        assert result is None


class TestScanOnce:
    def test_scan_discovers_claude_projects(
        self, registry_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_path = tmp_path / "myapp"
        project_path.mkdir(parents=True)
        (project_path / ".wormhole").mkdir()

        claude_projects = tmp_path / ".claude" / "projects"
        claude_projects.mkdir(parents=True)
        mangled = "fake-mangled"
        (claude_projects / mangled).mkdir()

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # Mock reverse_mangle to return our project path
        monkeypatch.setattr(
            ProjectRegistry, "_reverse_mangle",
            lambda self, m: str(project_path) if m == mangled else None,
        )

        reg = ProjectRegistry()
        new = reg.scan_once()
        assert len(new) == 1
        assert new[0].path == str(project_path)

    def test_scan_skips_excluded_paths(
        self, registry_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_path = tmp_path / "secret"
        project_path.mkdir(parents=True)
        (project_path / ".wormhole").mkdir()

        claude_projects = tmp_path / ".claude" / "projects"
        claude_projects.mkdir(parents=True)
        mangled = "fake-secret"
        (claude_projects / mangled).mkdir()

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr(
            ProjectRegistry, "_reverse_mangle",
            lambda self, m: str(project_path) if m == mangled else None,
        )

        # Configure exclusion
        global_dir = registry_home / ".wormhole"
        global_cfg = GlobalConfig(
            discovery={"scan_claude_projects": True, "excluded_paths": [str(project_path)]}
        )
        from dataclasses import asdict

        import yaml
        (global_dir / "config.yaml").write_text(
            yaml.dump(asdict(global_cfg), default_flow_style=False),
            encoding="utf-8",
        )

        reg = ProjectRegistry()
        new = reg.scan_once()
        assert len(new) == 0

    def test_scan_auto_init(
        self, registry_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_path = tmp_path / "newproject"
        project_path.mkdir(parents=True)

        claude_projects = tmp_path / ".claude" / "projects"
        claude_projects.mkdir(parents=True)
        mangled = "fake-new"
        (claude_projects / mangled).mkdir()

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr(
            ProjectRegistry, "_reverse_mangle",
            lambda self, m: str(project_path) if m == mangled else None,
        )

        reg = ProjectRegistry()
        new = reg.scan_once()
        assert len(new) == 1
        assert new[0].auto_initialized is True
        assert (project_path / ".wormhole").is_dir()

    def test_scan_no_claude_dir(
        self, registry_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        reg = ProjectRegistry()
        new = reg.scan_once()
        assert new == []
