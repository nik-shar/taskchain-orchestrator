import pytest
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from api.server import app
from agent.orchestrator import check_handoff_trigger, get_orchestrator
from utils.db import OnboardingSessionState, HandoffSession

client = TestClient(app)

def test_check_handoff_trigger():
    # Test cases that should match explicit issue numbers
    assert check_handoff_trigger("/solve #42") == 42
    assert check_handoff_trigger("solve issue 7") == 7
    assert check_handoff_trigger("let's solve issue #99") == 99
    assert check_handoff_trigger("start coding 1001") == 1001
    
    # Test cases that should match generic trigger (-1)
    assert check_handoff_trigger("let's solve this") == -1
    assert check_handoff_trigger("start coding") == -1
    assert check_handoff_trigger("/solve") == -1
    
    # Test cases that should NOT match (None)
    assert check_handoff_trigger("hello world") is None
    assert check_handoff_trigger("I want to solve it later") is None

def test_orchestrator_route_no_trigger():
    orchestrator = get_orchestrator()
    mock_db = MagicMock()
    mock_bg = MagicMock()
    
    # Normal chat message, should return None (standard onboarding routing)
    res = orchestrator.route_message(
        session_id="session_123",
        repo_id="owner/repo",
        message="tell me about this repository",
        user_background="Python dev",
        db=mock_db,
        background_tasks=mock_bg
    )
    assert res is None
    assert not mock_bg.add_task.called

def test_orchestrator_route_explicit_trigger():
    orchestrator = get_orchestrator()
    mock_db = MagicMock()
    mock_bg = MagicMock()
    
    # Mocking state lookup to return OnboardingSessionState with DNA summary
    mock_state = OnboardingSessionState(
        session_id="session_123",
        repo_id="owner/repo",
        user_background="Python dev",
        dna_summary="DNA context data",
        selected_issue=None,
        files_explored="[\"src/core.py\"]"
    )
    # First query is state lookup, second is handoff lookup (returns None/new)
    mock_db.query.return_value.filter_by.return_value.first.side_effect = [mock_state, None]
    
    res = orchestrator.route_message(
        session_id="session_123",
        repo_id="owner/repo",
        message="let's solve issue #42",
        user_background="Python dev",
        db=mock_db,
        background_tasks=mock_bg
    )
    
    assert res == {"type": "handoff_triggered", "selected_issue": 42}
    assert mock_bg.add_task.called
    assert mock_db.commit.called

def test_orchestrator_route_generic_trigger_no_state_issue():
    orchestrator = get_orchestrator()
    mock_db = MagicMock()
    mock_bg = MagicMock()
    
    # Mock state query to return state without selected issue
    mock_state = OnboardingSessionState(
        session_id="session_123",
        selected_issue=None
    )
    mock_db.query.return_value.filter_by.return_value.first.return_value = mock_state
    
    res = orchestrator.route_message(
        session_id="session_123",
        repo_id="owner/repo",
        message="let's solve this",
        user_background="Python dev",
        db=mock_db,
        background_tasks=mock_bg
    )
    
    # Should ask user to specify issue number
    assert res["type"] == "chat_response"
    assert "Please specify which issue number" in res["message"]
    assert not mock_bg.add_task.called

def test_orchestrator_route_generic_trigger_with_state_issue():
    orchestrator = get_orchestrator()
    mock_db = MagicMock()
    mock_bg = MagicMock()
    
    # Mock state query to return state with a selected issue
    mock_state = OnboardingSessionState(
        session_id="session_123",
        repo_id="owner/repo",
        user_background="Python dev",
        dna_summary="DNA context data",
        selected_issue=73,
        files_explored="[]"
    )
    mock_db.query.return_value.filter_by.return_value.first.side_effect = [mock_state, mock_state, None]
    
    res = orchestrator.route_message(
        session_id="session_123",
        repo_id="owner/repo",
        message="let's solve this",
        user_background="Python dev",
        db=mock_db,
        background_tasks=mock_bg
    )
    
    # Should resolve to issue #73 and trigger handoff
    assert res == {"type": "handoff_triggered", "selected_issue": 73}
    assert mock_bg.add_task.called
    assert mock_db.commit.called

def test_handoff_endpoints():
    with patch("api.server.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_get_db.return_value = iter([mock_db])
        
        # Test start handoff API
        payload = {
            "session_id": "test_endpoint_session",
            "selected_issue": 42,
            "user_background": "Python dev"
        }
        
        # Mock the db query inside trigger_handoff
        mock_state = OnboardingSessionState(
            session_id="test_endpoint_session",
            repo_id="owner/repo",
            dna_summary="DNA summary text",
            files_explored="[]"
        )
        # First query in trigger_handoff is OnboardingSessionState, second is HandoffSession
        mock_db.query.return_value.filter_by.return_value.first.side_effect = [mock_state, None]
        
        response = client.post("/repos/owner/repo/handoff", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "started"
        assert response.json()["session_id"] == "test_endpoint_session"

def test_handoff_status_endpoint():
    with patch("api.server.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_get_db.return_value = iter([mock_db])
        
        # Mock active HandoffSession
        mock_session = HandoffSession(
            session_id="test_status_session",
            repo_id="owner/repo",
            selected_issue=100,
            status="coding",
            progress_pct=50,
            logs="Running patch...\n",
            patch_diff=None
        )
        
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_session
        
        response = client.get("/repos/owner/repo/handoff/status", params={"session_id": "test_status_session"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "coding"
        assert data["progress_pct"] == 50
        assert data["logs"] == "Running patch...\n"
        assert data["selected_issue"] == 100
