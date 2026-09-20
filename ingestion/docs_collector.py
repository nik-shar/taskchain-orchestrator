"""Tier 1: documentation collection (ingestion) and injection (query time).

Docs are the highest-signal-per-token data in a repo, so they are injected
directly into the prompt — but always under a character budget, prioritized
so the most important docs survive truncation.
"""
import logging
from os.path import basename, splitext
from pathlib import Path

import config
from utils.db import RepoDoc, SessionLocal

logger = logging.getLogger(__name__)

# Lower priority number = injected first.
PRIORITY_BASENAMES = {
    "readme": 10,
    "architecture": 20,
    "contributing": 30,
    "changelog": 40,
}


def _doc_priority(rel_path: str) -> int:
    stem = splitext(basename(rel_path))[0].lower()
    return PRIORITY_BASENAMES.get(stem, 50)


def _is_doc(rel_path: str) -> bool:
    _, ext = splitext(rel_path)
    return ext.lower() in {".md", ".rst", ".txt"}


def collect_docs(repo_id: str, workspace: Path) -> int:
    """Collect documentation files from the workspace into the repo_docs table."""
    db = SessionLocal()
    try:
        db.query(RepoDoc).filter_by(repo_id=repo_id).delete()
        doc_files = []
        for path in sorted(workspace.rglob("*")):
            if not path.is_file():
                continue
            rel_path = path.relative_to(workspace).as_posix()
            if _is_doc(rel_path):
                doc_files.append((rel_path, path))
        # README first, then architecture docs, then everything else.
        doc_files.sort(key=lambda item: _doc_priority(item[0]))

        count = 0
        for rel_path, path in doc_files[: config.MAX_DOCS_STORED]:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.warning(f"Could not read doc {rel_path}: {exc}")
                continue
            truncated = len(content) > config.DOC_FILE_MAX_CHARS
            if truncated:
                content = content[: config.DOC_FILE_MAX_CHARS]
            db.add(
                RepoDoc(
                    repo_id=repo_id,
                    path=rel_path,
                    content=content,
                    priority=_doc_priority(rel_path),
                    truncated=truncated,
                )
            )
            count += 1
        db.commit()
        logger.info(f"Collected {count} docs for {repo_id}")
        return count
    finally:
        db.close()


def build_docs_context(repo_id: str, budget_chars: int | None = None) -> str:
    """Build the budgeted Tier 1 docs block to inject into a prompt."""
    budget = budget_chars if budget_chars is not None else config.DOCS_CONTEXT_CHARS
    db = SessionLocal()
    try:
        docs = (
            db.query(RepoDoc)
            .filter_by(repo_id=repo_id)
            .order_by(RepoDoc.priority, RepoDoc.path)
            .all()
        )
    finally:
        db.close()

    if not docs:
        return ""

    sections = []
    used = 0
    for doc in docs:
        block = f"### {doc.path}\n{doc.content}"
        if doc.truncated:
            block += "\n... [truncated at ingestion time]"
        remaining = budget - used
        if remaining <= 0:
            break
        if len(block) > remaining:
            block = block[:remaining] + "\n... [truncated to fit context budget]"
        sections.append(block)
        used += len(block) + 2

    return "\n\n".join(sections)
