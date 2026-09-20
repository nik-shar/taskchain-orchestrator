from datetime import UTC, datetime

import config
from ingestion.github_indexer import PR, Issue, RepoSnapshot
from ingestion.sqlite_indexer import index_issues_and_prs, keyword_search, to_fts_query


def _make_snapshot():
    return RepoSnapshot(
        owner="test_owner",
        repo="test_repo",
        fetched_at=datetime.now(UTC),
        metadata={},
        readme="README",
        contributing="CONTRIBUTING",
        file_tree=[],
        tech_stack={},
        issues=[
            Issue(
                number=1,
                title="Test Issue",
                body="This is a test issue body about python and fastapi",
                state="open",
                labels=["bug", "good first issue"],
                comments=[],
                created_at=datetime.now(UTC),
                closed_at=None,
                is_good_first_issue=True,
            )
        ],
        pull_requests=[
            PR(
                number=2,
                title="Test PR",
                body="Fixed a bug in python config",
                state="closed",
                merged=True,
                linked_issue=1,
                created_at=datetime.now(UTC),
            )
        ],
    )


def test_index_and_search(tmp_path, monkeypatch):
    db_path = tmp_path / "test_rag.sqlite"
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{db_path}")

    snapshot = _make_snapshot()
    index_issues_and_prs("test_owner/test_repo", snapshot)

    results = keyword_search("test_owner/test_repo", "python", top_k=10)
    assert len(results) == 2
    assert any(r["type"] == "issue" for r in results)
    assert any(r["type"] == "pr" for r in results)

    issue_results = keyword_search("test_owner/test_repo", "Test Issue")
    assert len(issue_results) >= 1
    assert issue_results[0]["type"] == "issue"
    assert issue_results[0]["number"] == 1


def test_fts_query_sanitizer():
    # Stopwords and 1-2 char tokens are dropped; terms are quoted and OR-ed.
    assert to_fts_query("What does this repo do?") == '"repo"'
    assert to_fts_query("Where is authentication handled?") == '"authentication" OR "handled"'
    # FTS5 syntax characters must not survive into the MATCH expression.
    assert to_fts_query('sqlite3 OR "x" -y:z*') == '"sqlite3"'
    # Nothing tokenizable -> empty query, so callers can short-circuit.
    assert to_fts_query("") == ""
    assert to_fts_query("a b") == ""
    # Duplicate terms collapse.
    assert to_fts_query("token token auth") == '"token" OR "auth"'


def test_keyword_search_survives_question_punctuation(tmp_path, monkeypatch):
    db_path = tmp_path / "test_rag.sqlite"
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{db_path}")
    index_issues_and_prs("test_owner/test_repo", _make_snapshot())

    # This exact shape of query used to raise inside FTS5 and return nothing.
    results = keyword_search("test_owner/test_repo", "What is this about python?")
    assert results, "punctuation-heavy question should still match indexed text"
    assert any("python" in (r["body"] or "").lower() for r in results)

    assert keyword_search("test_owner/test_repo", "a b") == []
