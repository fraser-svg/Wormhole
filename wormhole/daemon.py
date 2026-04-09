"""Wormhole background daemon — multi-project watcher and auto-harvester."""

import logging
import os
import signal
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from wormhole.config import GLOBAL_DIR, ensure_global_dir, load_global_config
from wormhole.project_registry import ProjectRegistry
from wormhole.watcher import MultiProjectWatcher

logger = logging.getLogger("wormhole.daemon")

PID_FILE = GLOBAL_DIR / "daemon.pid"
LOG_FILE = GLOBAL_DIR / "daemon.log"


def _read_pid() -> int | None:
    """Read PID from file, return None if missing/invalid."""
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _is_running(pid: int) -> bool:
    """Check if process with *pid* is alive."""
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True  # Process exists but owned by another user
    except ProcessLookupError:
        return False


def daemon_status() -> dict[str, Any]:
    """Return daemon status info."""
    pid = _read_pid()
    running = pid is not None and _is_running(pid)
    registry = ProjectRegistry()
    return {
        "pid": pid if running else None,
        "running": running,
        "projects": len(registry.list_projects()),
    }


def stop_daemon() -> bool:
    """Stop a running daemon.  Returns True if successfully stopped."""
    pid = _read_pid()
    if pid is None or not _is_running(pid):
        return False

    os.kill(pid, signal.SIGTERM)

    # Wait up to 5 seconds
    for _ in range(50):
        if not _is_running(pid):
            break
        time.sleep(0.1)
    else:
        # Force kill
        try:
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.2)
        except OSError:
            pass

    if _is_running(pid):
        return False  # Process survived — don't remove PID file

    PID_FILE.unlink(missing_ok=True)
    return True


def _setup_daemon_logging(level_name: str = "INFO") -> None:
    """Configure rotating file logger for daemon process."""
    ensure_global_dir()
    level = getattr(logging, level_name.upper(), logging.INFO)

    wormhole_logger = logging.getLogger("wormhole")
    wormhole_logger.setLevel(level)
    wormhole_logger.handlers.clear()
    wormhole_logger.propagate = False

    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    wormhole_logger.addHandler(handler)


def run_daemon() -> None:
    """Main daemon loop.  Call directly for foreground mode."""
    global_cfg = load_global_config()
    poll_interval = float(global_cfg.daemon.get("poll_interval", 5.0))
    scan_interval = float(global_cfg.daemon.get("scan_interval", 60.0))

    _setup_daemon_logging(global_cfg.daemon.get("log_level", "INFO"))

    # Write PID
    ensure_global_dir()
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    registry = ProjectRegistry()
    watcher = MultiProjectWatcher()

    running = True

    def _handle_signal(signum: int, frame: Any) -> None:
        nonlocal running
        logger.info("Received signal %d, shutting down", signum)
        running = False

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info(
        "Daemon started (PID %d, poll=%.1fs, scan=%.1fs)",
        os.getpid(), poll_interval, scan_interval,
    )

    # Initial scan
    new = registry.scan_once()
    if new:
        logger.info("Initial scan found %d project(s)", len(new))
    project_dicts = [{"path": p.path} for p in registry.list_projects()]
    watcher.sync_projects(project_dicts)

    last_scan = time.monotonic()

    try:
        while running:
            try:
                # Poll all watchers
                results = watcher.poll_once()
                for path, (w, sk, st) in results.items():
                    logger.info(
                        "Auto-harvest %s: %d written, %d skipped, %d staged",
                        path, w, sk, st,
                    )

                # Periodic project rescan
                now = time.monotonic()
                if now - last_scan >= scan_interval:
                    new = registry.scan_once()
                    if new:
                        logger.info("Scan found %d new project(s)", len(new))
                    project_dicts = [{"path": p.path} for p in registry.list_projects()]
                    watcher.sync_projects(project_dicts)
                    last_scan = now
            except Exception:
                logger.exception("Error in daemon loop iteration")

            time.sleep(poll_interval)
    finally:
        PID_FILE.unlink(missing_ok=True)
        logger.info("Daemon stopped")


def start_daemon(foreground: bool = False) -> int:
    """Start the daemon.  Returns PID (0 in foreground mode)."""
    existing_pid = _read_pid()
    if existing_pid is not None and _is_running(existing_pid):
        return existing_pid  # Already running

    # Clean up stale PID file
    PID_FILE.unlink(missing_ok=True)

    if foreground:
        run_daemon()
        return 0

    if sys.platform == "win32":
        raise RuntimeError("Background daemon requires Unix (macOS/Linux). Use --foreground on Windows.")

    # Daemonize
    pid = os.fork()
    if pid > 0:
        # Parent: wait briefly for grandchild PID file
        time.sleep(0.3)
        child_pid = _read_pid()
        return child_pid or pid

    # Child: setsid + second fork
    os.setsid()
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)

    # Grandchild: redirect stdio, run
    sys.stdin.close()
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)

    run_daemon()
    os._exit(0)
