"""Tier 2: read-only code access tools.

The LLM never writes to the workspace. These tools expose exactly three
read operations — list, read, search — each bounded by size caps and path
safety so a single request cannot blow up the context window or escape the
workspace directory.
"""
import logging
import re
from pathlib import Path

import config
from ingestion.workspace import _is_text_file

logger = logging.getLogger(__name__)


class CodeReader:
    """Read-only filesystem tools scoped to a repository workspace."""

    def __init__(self, workspace: Path | str):
        self.workspace = Path(workspace).resolve()
        if not self.workspace.is_dir():
            raise FileNotFoundError(f"Workspace not found: {self.workspace}")

    def _safe_resolve(self, rel_path: str) -> Path | None:
        """Resolve a relative path, refusing anything that escapes the workspace."""
        target = (self.workspace / rel_path).resolve()
        if not str(target).startswith(str(self.workspace)):
            return None
        return target

    def list_files(self, limit: int = 500) -> list[str]:
        """List text files in the workspace, relative paths sorted."""
        files = []
        for path in sorted(self.workspace.rglob("*")):
            if not path.is_file():
                continue
            rel_path = path.relative_to(self.workspace).as_posix()
            if _is_text_file(rel_path):
                files.append(rel_path)
            if len(files) >= limit:
                break
        return files

    def read_file(
        self, rel_path: str, max_chars: int | None = None
    ) -> dict | None:
        """Read a single file, truncated to a per-file character cap."""
        cap = max_chars if max_chars is not None else config.CODE_FILE_MAX_CHARS
        target = self._safe_resolve(rel_path)
        if target is None or not target.is_file():
            return None
        if target.stat().st_size > 100_000:  # mirrors ingestion skip rule
            return None
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        truncated = len(content) > cap
        return {
            "path": rel_path,
            "content": content[:cap] if truncated else content,
            "truncated": truncated,
            "total_chars": len(content),
        }

    def search(self, pattern: str, max_results: int = 20) -> list[dict]:
        """Regex search across workspace text files. Returns bounded matches."""
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            return []

        results = []
        for rel_path in self.list_files():
            target = self._safe_resolve(rel_path)
            if target is None or not target.is_file():
                continue
            try:
                content = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(content.splitlines(), start=1):
                if regex.search(line):
                    results.append(
                        {"path": rel_path, "line": i, "text": line.strip()[:200]}
                    )
                    if len(results) >= max_results:
                        return results
        return results


def build_code_context(
    workspace: Path | str,
    selected_files: list[str],
    total_budget: int | None = None,
) -> tuple[str, list[str]]:
    """Read the selected files and format them into a budgeted code block.

    Returns (context_text, files_actually_read). Files are read in selection
    order until the total budget is exhausted; later files are dropped whole
    rather than sliced mid-file, so each included file stays coherent.
    """
    budget = total_budget if total_budget is not None else config.CODE_CONTEXT_CHARS
    reader = CodeReader(workspace)

    sections = []
    read_ok = []
    used = 0
    for rel_path in selected_files[: config.MAX_SELECTED_FILES]:
        result = reader.read_file(rel_path)
        if result is None:
            continue
        block = f"### {rel_path}\n```{rel_path.rsplit('.', 1)[-1]}\n{result['content']}\n```"
        if result["truncated"]:
            block += (
                f"\n... [showing first {len(result['content'])} "
                f"of {result['total_chars']} chars]"
            )
        if used + len(block) > budget:
            break
        sections.append(block)
        read_ok.append(rel_path)
        used += len(block) + 2

    return "\n\n".join(sections), read_ok
