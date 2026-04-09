"""Transcript redaction — strip secrets before sending to LLM APIs."""

import re

# API key patterns (common prefixes)
_API_KEY_PATTERNS = [
    re.compile(r"sk-ant-[a-zA-Z0-9_-]{20,}"),  # Anthropic
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI
    re.compile(r"AKIA[A-Z0-9]{16}"),  # AWS access key
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),  # GitHub PAT
    re.compile(r"gho_[a-zA-Z0-9]{36}"),  # GitHub OAuth
    re.compile(r"glpat-[a-zA-Z0-9_-]{20,}"),  # GitLab PAT
    re.compile(r"xoxb-[a-zA-Z0-9-]+"),  # Slack bot token
    re.compile(r"xoxp-[a-zA-Z0-9-]+"),  # Slack user token
]

# JWT pattern (three base64url segments separated by dots)
_JWT_RE = re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}")

# Private key blocks
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
)

# Environment variable assignments with sensitive-looking keys
_ENV_VAR_RE = re.compile(
    r"(?:^|\n)([A-Z_]*(?:KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTH)[A-Z_]*)=([^\n]+)",
    re.IGNORECASE,
)

# Home directory paths
_HOME_PATH_RE = re.compile(r"(/Users/[a-zA-Z0-9_.-]+|/home/[a-zA-Z0-9_.-]+|~)")

_REDACTED = "[REDACTED]"
_REDACTED_KEY = "[REDACTED_KEY]"
_REDACTED_PATH = "[HOME]"


def redact_secrets(text: str) -> str:
    """Strip API keys, JWTs, private keys, env secrets, and home paths.

    Returns redacted text safe to send to external LLM APIs.
    """
    result = text

    # Private keys (do first, they're multiline)
    result = _PRIVATE_KEY_RE.sub(f"-----PRIVATE KEY {_REDACTED}-----", result)

    # JWT tokens
    result = _JWT_RE.sub(_REDACTED_KEY, result)

    # API keys
    for pattern in _API_KEY_PATTERNS:
        result = pattern.sub(_REDACTED_KEY, result)

    # Environment variable assignments with sensitive keys
    def _redact_env(match: re.Match[str]) -> str:
        key = match.group(1)
        prefix = "\n" if match.group(0).startswith("\n") else ""
        return f"{prefix}{key}={_REDACTED}"

    result = _ENV_VAR_RE.sub(_redact_env, result)

    # Home directory paths
    result = _HOME_PATH_RE.sub(_REDACTED_PATH, result)

    return result
