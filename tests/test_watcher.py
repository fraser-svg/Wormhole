"""Tests for wormhole.watcher — passive transcript watching."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wormhole.config import Config
from wormhole.watcher import TranscriptWatcher, _content_hash


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    vault_path = tmp_path / ".wormhole"
    vault_path.mkdir()
    for subdir in ["decisions", "corrections", "discoveries", "architecture", "failures", "context", "staging"]:
        (vault_path / subdir).mkdir()
    return vault_path


@pytest.fixture()
def config() -> Config:
    return Config()


class TestContentHash:
    def test_hashes_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello")
        h = _content_hash(f)
        assert len(h) == 64  # SHA-256 hex

    def test_missing_file(self, tmp_path: Path) -> None:
        assert _content_hash(tmp_path / "nope.txt") == ""


class TestWatchState:
    def test_save_and_load(self, vault: Path, config: Config) -> None:
        watcher = TranscriptWatcher(vault, config)
        watcher._file_state = {"file.jsonl": {"mtime": 123, "size": 456, "hash": "abc"}}
        watcher._save_watch_state()

        watcher2 = TranscriptWatcher(vault, config)
        assert watcher2._file_state["file.jsonl"]["hash"] == "abc"

    def test_missing_state_file(self, vault: Path, config: Config) -> None:
        watcher = TranscriptWatcher(vault, config)
        assert watcher._file_state == {}


class TestCheckForChanges:
    def test_detects_new_file(self, vault: Path, config: Config, tmp_path: Path) -> None:
        # Set up a fake Claude projects dir
        projects_dir = tmp_path / ".claude" / "projects" / "test-project"
        projects_dir.mkdir(parents=True)
        jsonl = projects_dir / "session.jsonl"
        jsonl.write_text('{"type":"user"}\n')

        with patch.object(TranscriptWatcher, "_get_jsonl_dir", return_value=projects_dir):
            watcher = TranscriptWatcher(vault, config)
            changed = watcher._check_for_changes()
            assert len(changed) == 1
            assert changed[0].name == "session.jsonl"

    def test_no_change_on_second_check(self, vault: Path, config: Config, tmp_path: Path) -> None:
        projects_dir = tmp_path / ".claude" / "projects" / "test-project"
        projects_dir.mkdir(parents=True)
        jsonl = projects_dir / "session.jsonl"
        jsonl.write_text('{"type":"user"}\n')

        with patch.object(TranscriptWatcher, "_get_jsonl_dir", return_value=projects_dir):
            watcher = TranscriptWatcher(vault, config)
            watcher._check_for_changes()  # First check registers the file
            changed = watcher._check_for_changes()  # Second check: no change
            assert changed == []

    def test_detects_modified_file(self, vault: Path, config: Config, tmp_path: Path) -> None:
        projects_dir = tmp_path / ".claude" / "projects" / "test-project"
        projects_dir.mkdir(parents=True)
        jsonl = projects_dir / "session.jsonl"
        jsonl.write_text('{"type":"user"}\n')

        with patch.object(TranscriptWatcher, "_get_jsonl_dir", return_value=projects_dir):
            watcher = TranscriptWatcher(vault, config)
            watcher._check_for_changes()

            # Modify file
            time.sleep(0.01)
            jsonl.write_text('{"type":"user"}\n{"type":"assistant"}\n')

            changed = watcher._check_for_changes()
            assert len(changed) == 1

    def test_no_dir_returns_empty(self, vault: Path, config: Config) -> None:
        with patch.object(TranscriptWatcher, "_get_jsonl_dir", return_value=None):
            watcher = TranscriptWatcher(vault, config)
            assert watcher._check_for_changes() == []


class TestPollOnce:
    def test_no_changes_returns_zeros(self, vault: Path, config: Config) -> None:
        with patch.object(TranscriptWatcher, "_get_jsonl_dir", return_value=None):
            watcher = TranscriptWatcher(vault, config)
            assert watcher.poll_once() == (0, 0, 0)

    def test_harvest_called_on_change(self, vault: Path, config: Config, tmp_path: Path) -> None:
        projects_dir = tmp_path / ".claude" / "projects" / "test-project"
        projects_dir.mkdir(parents=True)
        jsonl = projects_dir / "session.jsonl"
        jsonl.write_text('{"type":"user"}\n')

        with patch.object(TranscriptWatcher, "_get_jsonl_dir", return_value=projects_dir), \
             patch.object(TranscriptWatcher, "_harvest_file", return_value=(2, 1, 0)) as mock_harvest:
            watcher = TranscriptWatcher(vault, config)
            w, sk, st = watcher.poll_once()
            assert w == 2
            assert sk == 1
            mock_harvest.assert_called_once()


class TestStartStop:
    def test_stop_flag(self, vault: Path, config: Config) -> None:
        with patch.object(TranscriptWatcher, "_get_jsonl_dir", return_value=None):
            watcher = TranscriptWatcher(vault, config)
            watcher._running = False
            # start() should exit immediately since _running is False
            # We test stop() sets the flag
            watcher._running = True
            watcher.stop()
            assert watcher._running is False
