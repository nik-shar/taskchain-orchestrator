import pytest
import os
import sqlite3
from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session
import chromadb

import config
from utils.db import SessionLocal, RepoIngestion, init_db
from ingestion.github_fetcher import RepoSnapshot, Issue, PR
from ingestion.ingestion_pipeline import (
    get_collection_name,
    index_in_sqlite_fts5,
    index_in_chroma,
    ingest_repository
)

@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    # Initialize the Postgres test tables on port 5433
    init_db()

def test_get_collection_name():
    assert get_collection_name("owner", "repo") == "issues_owner_repo"
    assert get_collection_name("Owner-Name", "Repo.Name") == "issues_owner-name_repo_name"
    assert get_collection_name("o", "r") == "issues_o_r"

def test_index_in_sqlite_fts5(tmp_path):
    sqlite_db_path = tmp_path / "test_fts.db"
    
    # Mock SQLITE_PATH in config
    with patch.object(config, "SQLITE_PATH", str(sqlite_db_path)):
        snapshot = RepoSnapshot(
            owner="test_owner",
            repo="test_repo",
            fetched_at=MagicMock(),
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
                    created_at=MagicMock(),
                    closed_at=None,
                    is_good_first_issue=True
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
                    created_at=MagicMock()
                )
            ]
        )
        
        index_in_sqlite_fts5("test_owner/test_repo", snapshot)
        
        # Verify it was inserted and is searchable
        con = sqlite3.connect(str(sqlite_db_path))
        cur = con.cursor()
        rows = cur.execute("SELECT * FROM issues_fts WHERE body MATCH 'python'").fetchall()
        assert len(rows) == 2 # both issue and pr mention python
        
        issue_rows = cur.execute("SELECT * FROM issues_fts WHERE type = 'issue'").fetchall()
        assert len(issue_rows) == 1
        assert int(issue_rows[0][1]) == 1 # issue number
        
        con.close()

@patch("ingestion.ingestion_pipeline.embed_texts")
def test_index_in_chroma(mock_embed, tmp_path):
    chroma_path = tmp_path / "test_chroma"
    mock_embed.return_value = [[0.1] * 4096, [0.2] * 4096]
    
    with patch.object(config, "CHROMA_PATH", str(chroma_path)):
        snapshot = RepoSnapshot(
            owner="test_owner",
            repo="test_repo2",
            fetched_at=MagicMock(),
            metadata={},
            readme="README",
            contributing="CONTRIBUTING",
            file_tree=[],
            tech_stack={},
            issues=[
                Issue(
                    number=1,
                    title="Test Issue",
                    body="Body",
                    state="open",
                    labels=[],
                    comments=[],
                    created_at=MagicMock(),
                    closed_at=None,
                    is_good_first_issue=False
                )
            ],
            pull_requests=[
                PR(
                    number=2,
                    title="Test PR",
                    body="PR Body",
                    state="closed",
                    merged=True,
                    linked_issue=1,
                    created_at=MagicMock()
                )
            ]
        )
        
        index_in_chroma("test_owner/test_repo2", snapshot)
        
        # Verify collection has documents
        chroma_client = chromadb.PersistentClient(path=str(chroma_path))
        collection = chroma_client.get_collection(name="issues_test_owner_test_repo2")
        results = collection.get()
        assert len(results["ids"]) == 2
        assert "issue_1_0" in results["ids"]
        assert "pr_2_0" in results["ids"]

@patch("ingestion.ingestion_pipeline.generate_repo_dna_summary")
@patch("ingestion.ingestion_pipeline.index_in_sqlite_fts5")
@patch("ingestion.ingestion_pipeline.index_in_chroma")
@patch("ingestion.github_fetcher.GitHubFetcher.fetch_repo")
def test_ingestion_record_persisted(mock_fetch, mock_chroma, mock_fts, mock_dna):
    # Setup mocks
    mock_dna.return_value = "1. What this repo does\nThis is a mock DNA summary.\n2. Tech stack\nPython"
    mock_fetch.return_value = RepoSnapshot(
        owner="test_owner",
        repo="test_repo3",
        fetched_at=MagicMock(),
        metadata={},
        readme="README",
        contributing="CONTRIBUTING",
        file_tree=[],
        tech_stack={},
        issues=[],
        pull_requests=[]
    )
    
    result = ingest_repository("https://github.com/test_owner/test_repo3")
    
    assert result["status"] == "complete"
    assert result["repo_id"] == "test_owner/test_repo3"
    
    # Verify Postgres DB contains the record
    db = SessionLocal()
    try:
        record = db.query(RepoIngestion).filter_by(owner="test_owner", repo="test_repo3").first()
        assert record is not None
        assert record.status == "complete"
        assert record.dna_summary == "1. What this repo does\nThis is a mock DNA summary.\n2. Tech stack\nPython"
    finally:
        db.close()
