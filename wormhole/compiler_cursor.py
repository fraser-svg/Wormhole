"""Cursor compiler: outputs to .cursorrules."""

from pathlib import Path

from wormhole.compiler_base import BaseCompiler


class CursorCompiler(BaseCompiler):
    """Compile vault blocks into .cursorrules format."""

    @property
    def tool_name(self) -> str:
        return "cursor"

    def write(self, output_path: Path | None = None) -> None:
        """Write compiled context to .cursorrules in project root."""
        if output_path is None:
            output_path = self.vault_path.parent / ".cursorrules"
        super().write(output_path)
