"""Tier 2 retrieval: index repository source files into SQLite FTS5.

Code was previously reachable only through a read-only filesystem tool, which meant
the LLM had to guess which files matter from a bare file tree. Indexing file contents
into FTS5 makes "which files are relevant?" an actual search over the repository, and
gives the Q&A pipeline a deterministic candidate list to ground file selection.

Rows live in a `files_fts` table (one row per file) alongside the `issues_fts` table
built by `ingestion.sqlite_indexer`.
"""
import logging
import os
import sqlite3
from pathlib import Path

import config
from ingestion.sqlite_indexer import _sqlite_db_path, ensure_db_path, to_fts_query
from ingestion.workspace import _is_text_file

logger = logging.getLogger(__name__)

FILES_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    repo_id,
    path,
    content
);
"""


def _db_path() -> str | None:
    """Return the SQLite file path, or None when the backend is not SQLite."""
    try:
        return _sqlite_db_path()
    except RuntimeError:
        logger.warning("Source-file indexing requires a sqlite DATABASE_URL; skipping.")
        return None


def index_source_files(repo_id: str, workspace: Path | str, max_files: int | None = None) -> int:
    """Index the text files of a workspace into FTS5. Returns the number indexed.

    The workspace is already filtered by `ingestion.workspace.download_workspace`;
    the `_is_text_file` check is repeated here so the indexer is also safe when
    pointed at an arbitrary directory.
    """
    db_path = _db_path()
    if db_path is None:
        return 0

    workspace = Path(workspace)
    if not workspace.is_dir():
        logger.warning("Workspace does not exist: %s", workspace)
        return 0

    limit = max_files if max_files is not None else config.MAX_INDEXED_FILES
    cap = config.CODE_INDEX_FILE_MAX_CHARS

    ensure_db_path()
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    try:
        cur.execute(FILES_FTS_SCHEMA)
        cur.execute("DELETE FROM files_fts WHERE repo_id = ?", (repo_id,))

        rows = []
        for path in sorted(workspace.rglob("*")):
            if len(rows) >= limit:
                break
            if not path.is_file():
                continue
            rel_path = path.relative_to(workspace).as_posix()
            if not _is_text_file(rel_path):
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.warning("Could not read %s for indexing: %s", rel_path, exc)
                continue
            rows.append((repo_id, rel_path, content[:cap]))

        cur.executemany(
            "INSERT INTO files_fts (repo_id, path, content) VALUES (?, ?, ?)", rows
        )
        con.commit()
    finally:
        con.close()

    logger.info("Indexed %d source files for %s", len(rows), repo_id)
    return len(rows)


def search_code(repo_id: str, query: str, top_k: int = 5) -> list[dict]:
    """Search indexed source files. Returns [{path, snippet}] ranked by relevance."""
    fts_query = to_fts_query(query)
    if not fts_query:
        return []

    db_path = _db_path()
    if db_path is None:
        return []

    if not os.path.exists(db_path):
        return []

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    try:
        rows = cur.execute(
            """
            SELECT path, snippet(files_fts, 2, '', '', '…', 12)
            FROM files_fts
            WHERE repo_id = ? AND files_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (repo_id, fts_query, top_k),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            logger.debug("files_fts not built yet for %s", repo_id)
        else:
            logger.warning("FTS file search failed for %s (%r): %s", repo_id, query, exc)
        rows = []
    finally:
        con.close()

    return [{"path": row[0], "snippet": row[1]} for row in rows]


def count_indexed_files(repo_id: str) -> int:
    """Number of source files indexed for a repo (0 when unavailable)."""
    db_path = _db_path()
    if db_path is None:
        return 0

    if not os.path.exists(db_path):
        return 0

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    try:
        row = cur.execute(
            "SELECT COUNT(*) FROM files_fts WHERE repo_id = ?", (repo_id,)
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    finally:
        con.close()
    return int(row[0]) if row else 0
