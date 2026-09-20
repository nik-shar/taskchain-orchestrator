"""SQLite FTS5 indexing and search for repository issues, pull requests and files."""
import logging
import os
import re
import sqlite3
from typing import Any

import config
from ingestion.github_indexer import RepoSnapshot

logger = logging.getLogger(__name__)

# Tokens too common to discriminate; without them an OR query matches everything.
# Two-letter function words are listed explicitly so that short but meaningful
# technical tokens (db, ci, io, os, ui, js, py, go, id) survive tokenization.
FTS_STOPWORDS = {
    "about", "am", "an", "and", "any", "are", "as", "at", "be", "by", "can",
    "do", "does", "for", "from", "get", "has", "have", "how", "if", "in",
    "into", "is", "it", "its", "me", "my", "no", "not", "of", "on", "or",
    "so", "that", "the", "their", "then", "there", "these", "they", "this",
    "to", "up", "us", "was", "we", "what", "when", "where", "which", "who",
    "why", "will", "with", "would", "you", "your",
}

MAX_FTS_TERMS = 12


def to_fts_query(text: str, max_terms: int = MAX_FTS_TERMS) -> str:
    """Convert free-form text into a safe FTS5 OR query.

    A raw question cannot be passed to ``MATCH``: characters like ``?``, ``-`` and
    ``:`` are FTS5 syntax, so the query raises and search silently returns nothing.
    Tokenize to word characters (2+, so abbreviations survive), drop stopwords, and
    quote every surviving term so each one is matched literally.
    """
    tokens = re.findall(r"[A-Za-z0-9_]{2,}", text.lower())
    terms = [token for token in tokens if token not in FTS_STOPWORDS]
    if not terms:
        # Query was all stopwords ("what does this do"); fall back to raw tokens.
        terms = tokens

    ordered: list[str] = []
    for term in terms:
        if term not in ordered:
            ordered.append(term)
    return " OR ".join(f'"{term}"' for term in ordered[:max_terms])



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
    fts_query = to_fts_query(query)
    if not fts_query:
        return []

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
            (repo_id, fts_query, top_k),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        # A missing table just means the repo has not been ingested yet; anything
        # else is a real problem worth surfacing.
        if "no such table" in str(exc):
            logger.debug("issues_fts not built yet for %s", repo_id)
        else:
            logger.warning("FTS issue search failed for %s (%r): %s", repo_id, query, exc)
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
