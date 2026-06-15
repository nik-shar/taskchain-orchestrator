import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from api.server import app
from utils.db import OnboardingSessionState, HandoffSession
from agent.orchestrator import get_orchestrator

client = TestClient(app)

def test_handoff_endpoint_with_steering_instructions():
    with patch("api.server.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_get_db.return_value = iter([mock_db])
        
        payload = {
            "session_id": "test_steering_session",
            "selected_issue": 42,
            "user_background": "Python dev",
            "steering_instructions": "Focus only on core math logic in utils/math.py"
        }
        
        # Mock onboarding state lookup and handoff lookup inside trigger_handoff
        mock_state = OnboardingSessionState(
            session_id="test_steering_session",
            repo_id="owner/repo",
            dna_summary="DNA summary text",
            files_explored="[]"
        )
        mock_db.query.return_value.filter_by.return_value.first.side_effect = [mock_state, None]
        
        response = client.post("/repos/owner/repo/handoff", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "started"
        
        # Verify orchestrator set steering_instructions on the handoff session
        # The mock_db.add was called with a HandoffSession
        added_objs = [args[0] for args, _ in mock_db.add.call_args_list]
        handoff_obj = next(o for o in added_objs if isinstance(o, HandoffSession))
        assert handoff_obj.steering_instructions == "Focus only on core math logic in utils/math.py"


@patch("agent.coding_agent.SessionLocal")
@patch("agent.coding_agent.ChatOpenAI")
@patch("agent.coding_agent.subprocess.run")
def test_coding_agent_prompt_injection(mock_sub_run, mock_llm_class, mock_session_local):
    # Setup mock db session
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db
    
    # Mock HandoffSession
    mock_handoff = HandoffSession(
        session_id="session_react_123",
        repo_id="owner/repo",
        selected_issue=101,
        user_background="React Developer",
        steering_instructions="Do not modify package.json at all",
        dna_summary="DNA summary info"
    )
    mock_db.query.return_value.filter_by.return_value.first.return_value = mock_handoff
    
    # Mock LLM and response
    mock_llm_instance = MagicMock()
    mock_llm_class.return_value = mock_llm_instance
    
    # Let LLM immediately return a message that doesn't trigger tool calls to stop loop
    mock_response = MagicMock()
    mock_response.content = "I have successfully analyzed the code and no tool calls are needed."
    mock_llm_instance.invoke.return_value = mock_response
    
    # Run loop
    from agent.coding_agent import run_coding_loop
    
    with patch("agent.coding_agent.config.REPOS_CLONE_DIR", new=MagicMock()):
        with patch("agent.coding_agent.Path.exists", return_value=True):
            run_coding_loop("session_react_123")
            
    # Verify the LLM invoke was called
    assert mock_llm_instance.invoke.called
    
    # Retrieve system prompt passed to invoke
    messages_passed = mock_llm_instance.invoke.call_args[0][0]
    system_message = messages_passed[0]
    
    assert "User steering constraints (MUST FOLLOW STRICTLY):" in system_message.content
    assert "Do not modify package.json at all" in system_message.content
