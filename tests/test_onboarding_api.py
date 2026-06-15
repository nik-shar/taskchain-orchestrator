import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from api.server import app

client = TestClient(app)

def test_ingest_endpoint_queues_task():
    with patch("api.server.ingest_repository") as mock_ingest, \
         patch("api.server.get_db") as mock_get_db:
        # Mock DB to return no existing ingestion (cache miss → queued)
        mock_db = MagicMock()
        mock_get_db.return_value = iter([mock_db])
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        
        response = client.post("/repos/ingest", json={"repo_url": "https://github.com/owner/repo"})
        assert response.status_code == 200
        assert response.json() == {"repo_id": "owner/repo", "status": "queued"}
        mock_ingest.assert_called_once_with("https://github.com/owner/repo")

def test_status_endpoint_returns_db_data():
    with patch("api.server.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_get_db.return_value = iter([mock_db])
        
        mock_ingestion = MagicMock()
        mock_ingestion.status = "complete"
        mock_ingestion.ingested_at = None
        mock_ingestion.issue_count = 10
        mock_ingestion.pr_count = 5
        mock_ingestion.progress_pct = 100
        mock_ingestion.status_message = "Complete!"
        
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_ingestion
        
        response = client.get("/repos/owner/repo/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "complete"
        assert data["issue_count"] == 10
        assert data["pr_count"] == 5
        assert data["progress_pct"] == 100
        assert data["status_message"] == "Complete!"

def test_onboard_endpoint_cache_miss():
    with patch("api.server.run_onboarding_workflow") as mock_wf, \
         patch("api.server.get_db") as mock_get_db:
         
        mock_db = MagicMock()
        mock_get_db.return_value = iter([mock_db, mock_db])
        
        # Cache miss
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        
        mock_wf.return_value = {
            "guide": "Onboarding Guide Details",
            "retrieved_issues": [],
            "search_queries": ["query1"]
        }
        
        response = client.post("/repos/owner/repo/onboard", json={"user_background": "I know Python"})
        assert response.status_code == 200
        data = response.json()
        assert data["guide"] == "Onboarding Guide Details"
        assert data["trace"]["cached"] is False
        assert mock_db.add.called

def test_onboard_endpoint_cache_hit():
    with patch("api.server.get_db") as mock_get_db, \
         patch("agent.onboarding_workflow.hybrid_search_issues") as mock_search:
         
        mock_db = MagicMock()
        mock_get_db.return_value = iter([mock_db])
        
        # Cache hit
        mock_guide = MagicMock()
        mock_guide.guide = "Cached Onboarding Guide"
        mock_guide.created_at = datetime.now(timezone.utc)
        
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_guide
        
        mock_search.return_value = {
            "search_queries": ["query1"],
            "retrieved_issues": []
        }
        
        response = client.post("/repos/owner/repo/onboard", json={"user_background": "I know Python"})
        assert response.status_code == 200
        data = response.json()
        assert data["guide"] == "Cached Onboarding Guide"
        assert data["trace"]["cached"] is True
        
def test_feedback_endpoint():
    with patch("api.server.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_get_db.return_value = iter([mock_db])
        
        response = client.post("/repos/owner/repo/feedback", json={
            "session_id": "session123",
            "rating": 2,
            "background_hash": "hash123"
        })
        assert response.status_code == 200
        assert response.json() == {"saved": True}
        assert mock_db.add.called
        assert mock_db.commit.called
