"""Tests for daemon module."""

import os
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wormhole.daemon import (
    LOG_FILE,
    PID_FILE,
    _is_running,
    _read_pid,
    daemon_status,
    stop_daemon,
)


@pytest.fixture
def daemon_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override global dir for daemon tests."""
    global_dir = tmp_path / ".wormhole"
    global_dir.mkdir()
    monkeypatch.setattr("wormhole.daemon.PID_FILE", global_dir / "daemon.pid")
    monkeypatch.setattr("wormhole.daemon.LOG_FILE", global_dir / "daemon.log")
    monkeypatch.setattr("wormhole.config.GLOBAL_DIR", global_dir)
    monkeypatch.setattr("wormhole.project_registry.GLOBAL_DIR", global_dir)
    from wormhole.project_registry import ProjectRegistry
    monkeypatch.setattr(ProjectRegistry, "REGISTRY_FILE", global_dir / "projects.json")
    return tmp_path


class TestReadPid:
    def test_no_file(self, daemon_home: Path) -> None:
        assert _read_pid() is None

    def test_valid_pid(self, daemon_home: Path) -> None:
        pid_file = daemon_home / ".wormhole" / "daemon.pid"
        pid_file.write_text("12345", encoding="utf-8")
        assert _read_pid() == 12345

    def test_invalid_content(self, daemon_home: Path) -> None:
        pid_file = daemon_home / ".wormhole" / "daemon.pid"
        pid_file.write_text("not-a-number", encoding="utf-8")
        assert _read_pid() is None


class TestIsRunning:
    def test_current_process(self) -> None:
        assert _is_running(os.getpid()) is True

    def test_nonexistent_pid(self) -> None:
        # PID 99999999 almost certainly doesn't exist
        assert _is_running(99999999) is False


class TestDaemonStatus:
    def test_not_running(self, daemon_home: Path) -> None:
        info = daemon_status()
        assert info["running"] is False
        assert info["pid"] is None
        assert info["projects"] == 0

    def test_running(self, daemon_home: Path) -> None:
        pid_file = daemon_home / ".wormhole" / "daemon.pid"
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        info = daemon_status()
        assert info["running"] is True
        assert info["pid"] == os.getpid()

    def test_stale_pid(self, daemon_home: Path) -> None:
        pid_file = daemon_home / ".wormhole" / "daemon.pid"
        pid_file.write_text("99999999", encoding="utf-8")
        info = daemon_status()
        assert info["running"] is False


class TestStopDaemon:
    def test_not_running(self, daemon_home: Path) -> None:
        assert stop_daemon() is False

    def test_stale_pid_file(self, daemon_home: Path) -> None:
        pid_file = daemon_home / ".wormhole" / "daemon.pid"
        pid_file.write_text("99999999", encoding="utf-8")
        assert stop_daemon() is False
