from datetime import UTC, datetime

import config
from ingestion.github_indexer import PR, Issue, RepoSnapshot
from ingestion.sqlite_indexer import index_issues_and_prs, keyword_search


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
