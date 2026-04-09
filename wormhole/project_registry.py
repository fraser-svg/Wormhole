"""Project discovery and tracking for the Wormhole daemon."""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wormhole.config import GLOBAL_DIR, ensure_global_dir, load_global_config
from wormhole.vault import init_vault

logger = logging.getLogger(__name__)


@dataclass
class TrackedProject:
    """A project being watched by the daemon."""

    path: str
    detected_at: str  # ISO 8601 timestamp
    tool: str  # "claude", "cursor", etc.
    auto_initialized: bool = False


class ProjectRegistry:
    """Discover, track, and manage Wormhole-enabled projects."""

    REGISTRY_FILE = GLOBAL_DIR / "projects.json"

    def __init__(self) -> None:
        self._projects: dict[str, TrackedProject] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self.REGISTRY_FILE.exists():
            return
        try:
            raw = json.loads(self.REGISTRY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load project registry: %s", exc)
            return

        for entry in raw:
            if isinstance(entry, dict) and "path" in entry:
                tp = TrackedProject(
                    path=entry["path"],
                    detected_at=entry.get("detected_at", ""),
                    tool=entry.get("tool", "claude"),
                    auto_initialized=entry.get("auto_initialized", False),
                )
                self._projects[tp.path] = tp

    def _save(self) -> None:
        ensure_global_dir()
        data: list[dict[str, Any]] = [asdict(p) for p in self._projects.values()]
        tmp = self.REGISTRY_FILE.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.rename(self.REGISTRY_FILE)
        except OSError as exc:
            logger.warning("Failed to save project registry: %s", exc)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_projects(self) -> list[TrackedProject]:
        return list(self._projects.values())

    def add_project(
        self, path: str, tool: str = "claude", auto_initialized: bool = False
    ) -> TrackedProject:
        if path in self._projects:
            return self._projects[path]
        tp = TrackedProject(
            path=path,
            detected_at=datetime.now(timezone.utc).isoformat(),
            tool=tool,
            auto_initialized=auto_initialized,
        )
        self._projects[path] = tp
        self._save()
        logger.info("Registered project: %s", path)
        return tp

    def remove_project(self, path: str) -> None:
        if path in self._projects:
            del self._projects[path]
            self._save()
            logger.info("Removed project: %s", path)

    def has_project(self, path: str) -> bool:
        return path in self._projects

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _reverse_mangle(self, mangled: str) -> str | None:
        """Best-effort reverse of Claude Code's path mangling.

        Claude mangles ``/Users/foxy/code`` → ``Users-foxy-code``.
        We prepend ``/`` and replace ``-`` with ``/``.  Because directory
        names can contain hyphens this is ambiguous, so we validate the
        result against the filesystem.
        """
        # Reject entries with path traversal components
        if ".." in mangled:
            return None

        candidate = "/" + mangled.replace("-", "/")
        resolved = Path(candidate).resolve()

        # Must be a real directory under user's home
        home = Path.home().resolve()
        if not str(resolved).startswith(str(home)):
            return None
        if not resolved.is_dir():
            return None

        return str(resolved)

    def scan_once(self) -> list[TrackedProject]:
        """Scan for new projects and auto-init if configured.

        Returns list of newly-discovered projects.
        """
        global_cfg = load_global_config()
        new_projects: list[TrackedProject] = []

        if global_cfg.discovery.get("scan_claude_projects", True):
            claude_projects = Path.home() / ".claude" / "projects"
            if claude_projects.is_dir():
                excluded = set(global_cfg.discovery.get("excluded_paths", []))
                for mangled_dir in claude_projects.iterdir():
                    if not mangled_dir.is_dir():
                        continue
                    project_path = self._reverse_mangle(mangled_dir.name)
                    if project_path is None:
                        continue
                    if project_path in excluded:
                        continue
                    if self.has_project(project_path):
                        continue

                    # Auto-init vault if configured
                    vault_exists = (Path(project_path) / ".wormhole").is_dir()
                    auto_init = global_cfg.daemon.get("auto_init", True)
                    was_auto = False

                    if not vault_exists and auto_init:
                        try:
                            init_vault(Path(project_path))
                            was_auto = True
                            logger.info(
                                "Wormhole detected new project: %s", project_path
                            )
                        except FileExistsError:
                            # Another process created it between our check and init
                            vault_exists = True
                        except OSError as exc:
                            logger.warning(
                                "Auto-init failed for %s: %s", project_path, exc
                            )
                            continue

                    if vault_exists or was_auto:
                        tp = self.add_project(
                            project_path,
                            tool="claude",
                            auto_initialized=was_auto,
                        )
                        new_projects.append(tp)

        return new_projects
