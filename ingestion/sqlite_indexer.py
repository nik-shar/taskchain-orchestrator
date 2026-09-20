"""SQLite FTS5 indexing for repository issues and pull requests."""
import logging
import os
import sqlite3
from typing import Any

import config
from ingestion.github_indexer import RepoSnapshot

logger = logging.getLogger(__name__)


def _sqlite_db_path() -> str:
    """Extract the file path from a sqlite:// DATABASE_URL."""
    url = config.DATABASE_URL
    if not url.startswith("sqlite"):
        raise RuntimeError(
            "sqlite_indexer requires a SQLite DATABASE_URL (FTS5 index). "
            f"Got: {url}"
        )
    return url.replace("sqlite:///", "")


def ensure_db_path() -> None:
    """Ensure the directory containing the SQLite database exists."""
    db_path = _sqlite_db_path()
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def index_issues_and_prs(repo_id: str, snapshot: RepoSnapshot) -> None:
    """Index issue and pull request content into a SQLite FTS5 table."""
    ensure_db_path()
    db_path = _sqlite_db_path()

    con = sqlite3.connect(db_path)
    cur = con.cursor()

    cur.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS issues_fts USING fts5(
            repo_id,
            issue_number,
            title,
            body,
            labels,
            state,
            is_good_first_issue,
            type
        );
        """
    )
    cur.execute("DELETE FROM issues_fts WHERE repo_id = ?", (repo_id,))

    for issue in snapshot.issues:
        labels_str = ", ".join(issue.labels)
        cur.execute(
            """
            INSERT INTO issues_fts
                (repo_id, issue_number, title, body, labels, state, is_good_first_issue, type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repo_id,
                issue.number,
                issue.title,
                issue.body,
                labels_str,
                issue.state,
                1 if issue.is_good_first_issue else 0,
                "issue",
            ),
        )

    for pr in snapshot.pull_requests:
        cur.execute(
            """
            INSERT INTO issues_fts
                (repo_id, issue_number, title, body, labels, state, is_good_first_issue, type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repo_id,
                pr.number,
                pr.title,
                pr.body,
                "",
                pr.state,
                0,
                "pr",
            ),
        )

    con.commit()
    con.close()
    logger.info(
        f"Indexed {len(snapshot.issues)} issues and "
        f"{len(snapshot.pull_requests)} PRs for {repo_id}"
    )


def keyword_search(repo_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Search the FTS5 index for issues and PRs matching the query."""
    try:
        db_path = _sqlite_db_path()
    except RuntimeError:
        return []
    if not os.path.exists(db_path):
        return []

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    try:
        rows = cur.execute(
            """
            SELECT repo_id, issue_number, title, body, labels, state, type
            FROM issues_fts
            WHERE repo_id = ? AND issues_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (repo_id, query, top_k),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        con.close()

    return [
        {
            "repo_id": r[0],
            "number": r[1],
            "title": r[2],
            "body": r[3],
            "labels": r[4],
            "state": r[5],
            "type": r[6],
        }
        for r in rows
    ]
