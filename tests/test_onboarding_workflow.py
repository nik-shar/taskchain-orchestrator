import pytest
import sqlite3
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import config
from utils.db import SessionLocal, RepoIngestion, init_db
from agent.onboarding_workflow import (
    load_repo_context,
    build_search_query,
    hybrid_search_issues,
    synthesize_guide,
    collect_feedback,
    run_onboarding_workflow
)

@pytest.fixture(scope="module", autouse=True)
def setup_databases():
    init_db()

def test_load_repo_context_missing():
    # Run node on a missing repo
    state = {
        "repo_id": "non_existent/repo",
        "user_background": "I know python",
        "dna_summary": "",
        "background_hash": "",
        "search_queries": [],
        "retrieved_issues": [],
        "guide": "",
        "error": None
    }
    result = load_repo_context(state)
    assert result["error"] == "Repo not indexed yet"

def test_stale_repo_still_runs():
    db = SessionLocal()
    # Create a stale ingestion record (>7 days ago)
    stale_time = datetime.now(timezone.utc) - timedelta(days=10)
    ingestion = RepoIngestion(
        owner="stale_owner",
        repo="stale_repo",
        dna_summary="DNA Summary Stale",
        ingested_at=stale_time,
        status="complete"
    )
    db.add(ingestion)
    db.commit()
    db.close()
    
    state = {
        "repo_id": "stale_owner/stale_repo",
        "user_background": "I know python",
        "dna_summary": "",
        "background_hash": "",
        "search_queries": [],
        "retrieved_issues": [],
        "guide": "",
        "error": None
    }
    
    result = load_repo_context(state)
    assert result["error"] is None
    assert result["dna_summary"] == "DNA Summary Stale"

@patch("agent.onboarding_workflow.build_llm")
def test_build_search_query_output(mock_llm_build):
    # Mock ChatOpenAI invoke
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = '["python tutorial", "easy fastapi issues"]'
    mock_llm.invoke.return_value = mock_response
    mock_llm_build.return_value = mock_llm
    
    state = {
        "repo_id": "owner/repo",
        "user_background": "I know Python and FastAPI",
        "dna_summary": "Summary",
        "background_hash": "",
        "search_queries": [],
        "retrieved_issues": [],
        "guide": "",
        "error": None
    }
    
    result = build_search_query(state)
    assert len(result["search_queries"]) == 2
    assert "python tutorial" in result["search_queries"]

def test_hybrid_search_returns_results(tmp_path):
    sqlite_db_path = tmp_path / "test_fts.db"
    
    # Initialize SQLite FTS5 database with mock data
    con = sqlite3.connect(str(sqlite_db_path))
    cur = con.cursor()
    cur.execute("""
        CREATE VIRTUAL TABLE issues_fts USING fts5(
            repo_id,
            issue_number,
            title,
            body,
            labels,
            state,
            is_good_first_issue,
            type
        );
    """)
    cur.execute("""
        INSERT INTO issues_fts (repo_id, issue_number, title, body, labels, state, is_good_first_issue, type)
        VALUES ('owner/repo', 1, 'FastAPI Bug', 'There is a bug in the endpoint', 'bug, good first issue', 'open', 1, 'issue')
    """)
    cur.execute("""
        INSERT INTO issues_fts (repo_id, issue_number, title, body, labels, state, is_good_first_issue, type)
        VALUES ('owner/repo', 2, 'Doc Fix', 'Update fastapi documentation', 'docs', 'open', 0, 'issue')
    """)
    con.commit()
    con.close()
    
    # Patch config path and Chroma query
    with patch.object(config, "SQLITE_PATH", str(sqlite_db_path)), \
         patch("chromadb.PersistentClient") as mock_chroma_client:
         
        # Mock Chroma client & collection
        mock_coll = MagicMock()
        # Chroma returns issue 1
        mock_coll.query.return_value = {
            "ids": [["issue_1_0"]],
            "metadatas": [[{"number": 1, "type": "issue"}]],
            "documents": [["FastAPI Bug"]]
        }
        mock_chroma_client.return_value.get_collection.return_value = mock_coll
        
        state = {
            "repo_id": "owner/repo",
            "user_background": "fastapi",
            "dna_summary": "Summary",
            "background_hash": "",
            "search_queries": ["fastapi"],
            "retrieved_issues": [],
            "guide": "",
            "error": None
        }
        
        result = hybrid_search_issues(state)
        
        assert len(result["retrieved_issues"]) > 0
        first_issue = result["retrieved_issues"][0]
        assert first_issue["number"] == 1
        assert "FastAPI Bug" in first_issue["title"]

@patch("agent.onboarding_workflow.build_llm")
def test_guide_has_required_sections(mock_llm_build):
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "## Welcome to repo\n### What this repo does\n...\n### Your setup steps\n..."
    mock_llm.invoke.return_value = mock_response
    mock_llm_build.return_value = mock_llm
    
    state = {
        "repo_id": "owner/repo",
        "user_background": "python",
        "dna_summary": "Summary",
        "background_hash": "",
        "search_queries": [],
        "retrieved_issues": [
            {"number": 1, "title": "Issue 1", "body": "Body 1", "labels": [], "state": "open", "type": "issue", "is_good_first_issue": True}
        ],
        "guide": "",
        "error": None
    }
    
    result = synthesize_guide(state)
    assert "Welcome to repo" in result["guide"]
    assert "Your setup steps" in result["guide"]

def test_collect_feedback():
    state = {
        "repo_id": "owner/repo",
        "user_background": "I know python",
        "dna_summary": "Summary",
        "background_hash": "",
        "search_queries": [],
        "retrieved_issues": [],
        "guide": "Guide text",
        "error": None
    }
    result = collect_feedback(state)
    assert result["background_hash"] != ""
    assert isinstance(result["background_hash"], str)
