"""Filesystem watcher for passive transcript harvesting."""

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from wormhole.config import Config, load_config
from wormhole.harvester_claude import ClaudeHarvester
from wormhole.manifest import build_manifest, write_manifest
from wormhole.scoring import build_index
from wormhole.vault import list_blocks

logger = logging.getLogger(__name__)


def _content_hash(path: Path) -> str:
    """SHA-256 of file content, empty string if unreadable."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


class TranscriptWatcher:
    """Poll for new/modified JSONL transcripts and auto-harvest."""

    def __init__(
        self,
        vault_path: Path,
        config: Config,
        project_path: str | None = None,
    ) -> None:
        self.vault_path = vault_path
        self.config = config
        self.project_path = project_path or os.getcwd()
        self.poll_interval = float(config.watcher.get("poll_interval", 5.0))
        self.auto_manifest = bool(config.watcher.get("auto_manifest", True))
        self._running = False
        self._file_state: dict[str, dict[str, Any]] = {}
        self._load_watch_state()

    def _state_file(self) -> Path:
        return self.vault_path / ".watch-state"

    def _load_watch_state(self) -> None:
        """Load persisted file state (hashes, mtimes)."""
        sf = self._state_file()
        if sf.exists():
            try:
                self._file_state = json.loads(sf.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._file_state = {}

    def _save_watch_state(self) -> None:
        """Persist file state atomically."""
        sf = self._state_file()
        tmp = sf.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(self._file_state, indent=2), encoding="utf-8"
            )
            tmp.rename(sf)
        except OSError as exc:
            logger.warning("Failed to save watch state: %s", exc)

    def _get_jsonl_dir(self) -> Path | None:
        """Resolve Claude projects directory for current project."""
        from wormhole.harvester_claude import _mangle_path

        claude_home = Path.home() / ".claude" / "projects"
        mangled = _mangle_path(self.project_path)
        projects_dir = claude_home / mangled
        return projects_dir if projects_dir.exists() else None

    def _check_for_changes(self) -> list[Path]:
        """Return JSONL files that have changed since last check."""
        projects_dir = self._get_jsonl_dir()
        if not projects_dir:
            return []

        changed: list[Path] = []
        for jsonl_path in projects_dir.glob("*.jsonl"):
            key = str(jsonl_path)
            try:
                stat = jsonl_path.stat()
            except OSError:
                continue

            prev = self._file_state.get(key, {})
            prev_mtime = prev.get("mtime", 0)
            prev_size = prev.get("size", 0)

            # Quick check: mtime and size unchanged → skip
            if stat.st_mtime == prev_mtime and stat.st_size == prev_size:
                continue

            # Content hash to confirm real change
            new_hash = _content_hash(jsonl_path)
            if new_hash == prev.get("hash", ""):
                # mtime changed but content didn't
                self._file_state[key] = {
                    "mtime": stat.st_mtime,
                    "size": stat.st_size,
                    "hash": new_hash,
                }
                continue

            changed.append(jsonl_path)
            self._file_state[key] = {
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "hash": new_hash,
            }

        return changed

    def _harvest_file(self, jsonl_path: Path) -> tuple[int, int, int]:
        """Harvest a specific JSONL file."""
        config = load_config(self.vault_path)
        harvester = ClaudeHarvester(
            self.vault_path, config, project_path=self.project_path
        )
        try:
            written, skipped, staged = harvester.harvest()
        except Exception as exc:
            logger.warning("Harvest failed for %s: %s", jsonl_path.name, exc)
            return 0, 0, 0

        if self.auto_manifest and written > 0:
            all_blocks = list_blocks(self.vault_path)
            write_manifest(self.vault_path, all_blocks)
            build_index(self.vault_path, all_blocks)

        return written, skipped, staged

    def poll_once(self) -> tuple[int, int, int]:
        """Single poll cycle. Returns aggregate (written, skipped, staged)."""
        changed = self._check_for_changes()
        if not changed:
            return 0, 0, 0

        total_w, total_sk, total_st = 0, 0, 0
        for jsonl_path in changed:
            logger.info("Detected change: %s", jsonl_path.name)
            w, sk, st = self._harvest_file(jsonl_path)
            total_w += w
            total_sk += sk
            total_st += st

        self._save_watch_state()
        return total_w, total_sk, total_st

    def start(self) -> None:
        """Start polling loop. Blocks until stop() is called."""
        self._running = True
        logger.info(
            "Watcher started (poll every %.1fs)", self.poll_interval
        )

        while self._running:
            try:
                w, sk, st = self.poll_once()
                if w > 0 or st > 0:
                    logger.info(
                        "Auto-harvest: %d written, %d skipped, %d staged",
                        w, sk, st,
                    )
            except Exception as exc:
                logger.warning("Watcher poll error: %s", exc)

            time.sleep(self.poll_interval)

    def stop(self) -> None:
        """Signal the polling loop to stop."""
        self._running = False
        logger.info("Watcher stopping")
