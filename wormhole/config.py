"""Configuration management for Wormhole vaults."""

import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_BUDGETS: dict[str, int] = {
    "claude": 8000,
    "cursor": 2000,
    "aider": 2000,
    "copilot": 1500,
    "generic": 2500,
}

_DEFAULT_WEIGHTS: dict[str, float] = {
    "recency": 0.25,
    "file_proximity": 0.30,
    "dependency_depth": 0.25,
    "category": 0.20,
}

_DEFAULT_CATEGORY_WEIGHTS: dict[str, float] = {
    "context": 1.0,
    "decisions": 0.9,
    "corrections": 0.85,
    "failures": 0.8,
    "architecture": 0.75,
    "discoveries": 0.6,
}

_DEFAULT_MAX_INLINED: dict[str, int] = {
    "decisions": 5,
    "corrections": 3,
    "failures": 3,
    "architecture": 3,
    "discoveries": 2,
}

_DEFAULT_HARVESTER: dict[str, float] = {
    "dedup_threshold": 0.8,
    "min_block_tokens": 50,
    "max_block_tokens": 1500,
    "confidence_threshold": 0.8,
}


@dataclass
class LLMConfig:
    """LLM extraction configuration."""

    enabled: bool = False
    model: str = "claude-haiku-4-5-20251001"
    api_key_env: str = "ANTHROPIC_API_KEY"
    chunk_size: int = 4000
    max_chunks: int = 20
    temperature: float = 0.0


@dataclass
class WatcherConfig:
    """Passive harvesting watcher configuration."""

    poll_interval: float = 5.0
    auto_manifest: bool = True


@dataclass
class Config:
    """Wormhole vault configuration with sensible defaults."""

    budgets: dict[str, int] = field(default_factory=lambda: dict(_DEFAULT_BUDGETS))
    weights: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_WEIGHTS))
    category_weights: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_CATEGORY_WEIGHTS)
    )
    ttl: int = 90
    max_inlined: dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_MAX_INLINED)
    )
    harvester: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_HARVESTER)
    )
    llm: dict[str, Any] = field(default_factory=lambda: asdict(LLMConfig()))
    watcher: dict[str, Any] = field(default_factory=lambda: asdict(WatcherConfig()))
    default_tool: str = ""
    vault_version: str = "1"


def _deep_merge(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Merge overrides into defaults, preserving unset default keys."""
    merged = dict(defaults)
    for key, value in overrides.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(vault_path: Path) -> Config:
    """Load config from vault_path/config.yaml, merged with defaults.

    On YAML errors or missing file, logs warning and returns defaults.
    """
    config_file = vault_path / "config.yaml"
    if not config_file.exists():
        return Config()

    try:
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse %s: %s. Using defaults.", config_file, exc)
        return Config()

    if not isinstance(raw, dict):
        return Config()

    defaults = asdict(Config())
    merged = _deep_merge(defaults, raw)
    return Config(**merged)


def save_config(config: Config, vault_path: Path) -> None:
    """Write config to vault_path/config.yaml."""
    vault_path.mkdir(parents=True, exist_ok=True)
    config_file = vault_path / "config.yaml"
    data = asdict(config)
    config_file.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Global configuration (~/.wormhole/)
# ---------------------------------------------------------------------------

GLOBAL_DIR = Path.home() / ".wormhole"

_DEFAULT_DAEMON: dict[str, Any] = {
    "poll_interval": 5.0,
    "scan_interval": 60.0,
    "auto_init": True,
    "auto_compile": True,
    "log_level": "INFO",
}

_DEFAULT_DISCOVERY: dict[str, Any] = {
    "scan_claude_projects": True,
    "excluded_paths": [],
}

_DEFAULT_MCP: dict[str, Any] = {
    "enabled": True,
}


@dataclass
class GlobalConfig:
    """Daemon and global settings stored in ~/.wormhole/config.yaml."""

    daemon: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_DAEMON))
    discovery: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_DISCOVERY))
    mcp: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_MCP))
    project_defaults: dict[str, Any] = field(default_factory=dict)


def ensure_global_dir() -> Path:
    """Create ~/.wormhole/ if it does not exist.  Returns the path."""
    GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
    return GLOBAL_DIR


def load_global_config() -> GlobalConfig:
    """Load ~/.wormhole/config.yaml, merged with defaults."""
    config_file = GLOBAL_DIR / "config.yaml"
    if not config_file.exists():
        return GlobalConfig()

    try:
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse global config: %s. Using defaults.", exc)
        return GlobalConfig()

    if not isinstance(raw, dict):
        return GlobalConfig()

    defaults = asdict(GlobalConfig())
    merged = _deep_merge(defaults, raw)
    # Filter to known fields to avoid crashes on unknown config keys
    known_fields = {f.name for f in GlobalConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in merged.items() if k in known_fields}
    return GlobalConfig(**filtered)


def save_global_config(config: GlobalConfig) -> None:
    """Write global config to ~/.wormhole/config.yaml."""
    ensure_global_dir()
    config_file = GLOBAL_DIR / "config.yaml"
    data = asdict(config)
    config_file.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def load_merged_config(vault_path: Path) -> Config:
    """Load project config merged over global project_defaults.

    Merge order: hardcoded defaults < global project_defaults < per-project config.yaml
    """
    global_cfg = load_global_config()
    base = asdict(Config())
    if global_cfg.project_defaults:
        base = _deep_merge(base, global_cfg.project_defaults)

    config_file = vault_path / "config.yaml"
    if config_file.exists():
        try:
            raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                base = _deep_merge(base, raw)
        except yaml.YAMLError as exc:
            logger.warning("Failed to parse %s: %s", config_file, exc)

    return Config(**base)
