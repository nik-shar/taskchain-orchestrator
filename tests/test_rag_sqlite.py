from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from orchestrator_api.app.rag_sqlite import (
    build_rag_sqlite_index,
    search_rag_index,
    summarize_rag_hits,
)


def _fts5_available() -> bool:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE fts_probe USING fts5(text);")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


@pytest.mark.skipif(not _fts5_available(), reason="SQLite build does not include FTS5")
def test_build_and_search_rag_index_with_filters(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    index = tmp_path / "rag.sqlite"
    docs = [
        {
            "doc_id": "jira:demo:1",
            "source": "jira",
            "text": (
                "Project: DEMO\nIssueType: Bug\nPriority: Major\nStatus: To Do\n"
                "Summary: Username changes are not read correctly"
            ),
            "metadata": {
                "collection": "JiraEcosystem",
                "issue_type": "Bug",
                "priority": "Major",
                "status": "To Do",
                "project": "DEMO",
                "created": "2018-03-25T23:04:58.826-0500",
            },
        },
        {
            "doc_id": "jira:demo:2",
            "source": "jira",
            "text": (
                "Project: DEMO\nIssueType: Task\nPriority: Minor\nStatus: Done\n"
                "Summary: Update release notes"
            ),
            "metadata": {
                "collection": "JiraEcosystem",
                "issue_type": "Task",
                "priority": "Minor",
                "status": "Done",
                "project": "DEMO",
                "created": "2018-03-26T00:00:00.000-0500",
            },
        },
        {
            "doc_id": "incident:INC100",
            "source": "incident_event_log",
            "text": (
                "Incident: INC100\nState: Closed\nPriority: 2 - High\n"
                "Category: Category 56\nSubcategory: Subcategory 119"
            ),
            "metadata": {
                "incident_number": "INC100",
                "state": "Closed",
                "priority": "2 - High",
                "opened_at": "01/01/2017 01:43",
            },
        },
    ]
    corpus.write_text("\n".join(json.dumps(item) for item in docs) + "\n", encoding="utf-8")

    stats = build_rag_sqlite_index(
        corpus_jsonl_path=corpus,
        index_db_path=index,
        chunk_chars=900,
        overlap_chars=120,
        reset=True,
    )
    assert stats.documents_read == 3
    assert stats.chunks_indexed >= 3
    assert stats.source_counts["jira"] == 2
    assert stats.source_counts["incident_event_log"] == 1

    jira_result = search_rag_index(
        index_db_path=index,
        query="username bug",
        source="jira",
        issue_type="Bug",
        top_k=5,
    )
    assert jira_result.hits
    assert jira_result.hits[0].doc_id == "jira:demo:1"
    assert jira_result.hits[0].metadata.get("issue_type") == "Bug"

    incident_result = search_rag_index(
        index_db_path=index,
        query="category 56 high priority",
        source="incident_event_log",
        priority="2 - High",
        opened_from="2017-01-01T00:00:00Z",
        opened_to="2017-01-02T00:00:00Z",
        top_k=5,
    )
    assert incident_result.hits
    assert incident_result.hits[0].doc_id == "incident:INC100"
    assert incident_result.hits[0].metadata.get("state") == "Closed"

    summary = summarize_rag_hits(query="username bug", hits=jira_result.hits, max_points=2)
    assert "jira:demo:1" in summary
