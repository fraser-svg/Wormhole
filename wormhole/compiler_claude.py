"""Claude compiler: outputs to CLAUDE.md."""

from pathlib import Path

from wormhole.compiler_base import BaseCompiler
from wormhole.config import Config


class ClaudeCompiler(BaseCompiler):
    """Compile vault blocks into CLAUDE.md format."""

    @property
    def tool_name(self) -> str:
        return "claude"

    def write(self, output_path: Path | None = None) -> None:
        """Write compiled context to CLAUDE.md in project root."""
        if output_path is None:
            output_path = self.vault_path.parent / "CLAUDE.md"
        super().write(output_path)
