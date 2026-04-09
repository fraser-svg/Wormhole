"""Tests for wormhole.redact — secret stripping before LLM API calls."""

from wormhole.redact import redact_secrets


class TestAPIKeyRedaction:
    def test_anthropic_key(self) -> None:
        text = "key is sk-ant-abc123XYZ789defGHI456jkl"
        result = redact_secrets(text)
        assert "sk-ant-" not in result
        assert "[REDACTED_KEY]" in result

    def test_openai_key(self) -> None:
        text = "OPENAI_KEY=sk-abcdefghij1234567890ab"
        result = redact_secrets(text)
        assert "sk-abcdefghij" not in result

    def test_aws_key(self) -> None:
        text = "aws_key: AKIAIOSFODNN7EXAMPLE"
        result = redact_secrets(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_github_pat(self) -> None:
        text = "token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        result = redact_secrets(text)
        assert "ghp_" not in result

    def test_gitlab_pat(self) -> None:
        text = "token: glpat-abcdefghijklmnopqrst"
        result = redact_secrets(text)
        assert "glpat-" not in result

    def test_slack_bot_token(self) -> None:
        text = "SLACK_TOKEN=xoxb-123-456-abc"
        result = redact_secrets(text)
        assert "xoxb-" not in result

    def test_no_false_positive_short_sk(self) -> None:
        """Short 'sk-' prefixes below 20 chars should not be redacted."""
        text = "sk-short"
        result = redact_secrets(text)
        assert result == text


class TestJWTRedaction:
    def test_jwt_stripped(self) -> None:
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        text = f"Authorization: Bearer {jwt}"
        result = redact_secrets(text)
        assert "eyJ" not in result


class TestPrivateKeyRedaction:
    def test_rsa_key(self) -> None:
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIBogIBAAJBALR\n-----END RSA PRIVATE KEY-----"
        result = redact_secrets(text)
        assert "MIIBogIBAAJBALR" not in result
        assert "REDACTED" in result


class TestEnvVarRedaction:
    def test_env_secret(self) -> None:
        text = "DATABASE_PASSWORD=s3cret123"
        result = redact_secrets(text)
        assert "s3cret123" not in result
        assert "DATABASE_PASSWORD=[REDACTED]" in result

    def test_env_token(self) -> None:
        text = "\nAUTH_TOKEN=mytoken123"
        result = redact_secrets(text)
        assert "mytoken123" not in result

    def test_non_sensitive_env_untouched(self) -> None:
        text = "NODE_ENV=production"
        result = redact_secrets(text)
        assert result == text


class TestHomePathRedaction:
    def test_macos_home(self) -> None:
        text = "path: /Users/foxy/project/src/main.py"
        result = redact_secrets(text)
        assert "/Users/foxy" not in result
        assert "[HOME]" in result

    def test_linux_home(self) -> None:
        text = "path: /home/dev/project/src"
        result = redact_secrets(text)
        assert "/home/dev" not in result

    def test_tilde_path(self) -> None:
        text = "config at ~/.config/app.yaml"
        result = redact_secrets(text)
        assert "~" not in result


class TestCombined:
    def test_multiple_secrets_in_one_text(self) -> None:
        text = (
            "API_KEY=sk-ant-abc123XYZ789defGHI456jkl\n"
            "Path: /Users/foxy/project\n"
            "JWT: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        )
        result = redact_secrets(text)
        assert "sk-ant-" not in result
        assert "/Users/foxy" not in result
        assert "eyJ" not in result

    def test_normal_text_unchanged(self) -> None:
        text = "The quick brown fox decided to use PostgreSQL."
        assert redact_secrets(text) == text
