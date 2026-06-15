import logging
import re
import json
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from utils.db import OnboardingSessionState, HandoffSession, ChatMessage
from agent.coding_agent import run_coding_loop

logger = logging.getLogger(__name__)

def check_handoff_trigger(message: str) -> Optional[int]:
    """Check if the user message triggers a handoff to the coding agent.
    Returns:
        int: The selected issue number if explicitly matched.
        -1: If a generic handoff trigger was matched but no issue was specified.
        None: If no handoff trigger was matched.
    """
    message_clean = message.strip().lower()
    
    # 1. Look for explicit triggers like /solve #42 or /solve 42
    solve_cmd_match = re.search(r"^/solve\s+#?(\d+)$", message_clean)
    if solve_cmd_match:
        return int(solve_cmd_match.group(1))
        
    # 2. Look for phrases like "let's solve issue #42", "solve issue 42", "start coding #42"
    phrases = [
        r"let's\s+solve\s+issue\s+#?(\d+)",
        r"solve\s+issue\s+#?(\d+)",
        r"let's\s+work\s+on\s+issue\s+#?(\d+)",
        r"work\s+on\s+issue\s+#?(\d+)",
        r"start\s+coding\s+issue\s+#?(\d+)",
        r"start\s+coding\s+#?(\d+)"
    ]
    for pattern in phrases:
        match = re.search(pattern, message_clean)
        if match:
            return int(match.group(1))
            
    # 3. Look for generic triggers like "let's solve this", "start coding", "/solve"
    generic_phrases = [
        "let's solve this",
        "let's solve it",
        "solve this issue",
        "start coding",
        "/solve"
    ]
    if any(p in message_clean for p in generic_phrases):
        return -1
        
    return None

class Orchestrator:
    """Lightweight rule-based router and session state coordinator."""

    def route_message(
        self,
        session_id: str,
        repo_id: str,
        message: str,
        user_background: str,
        db: Session,
        background_tasks
    ) -> Optional[Dict[str, Any]]:
        """Inspects incoming user message and routes it.
        If it triggers a handoff, initiates the handoff process and returns a control dict.
        Otherwise, returns None (indicating standard onboarding path).
        """
        issue_trigger = check_handoff_trigger(message)
        if issue_trigger is None:
            return None

        # Resolve selected issue
        selected_issue = None
        if issue_trigger == -1:
            # Retrieve last selected issue from saved state
            state = db.query(OnboardingSessionState).filter_by(session_id=session_id).first()
            if state and state.selected_issue:
                selected_issue = state.selected_issue
        else:
            selected_issue = issue_trigger

        if not selected_issue:
            # Inform user they need to select or specify an issue number
            return {
                "type": "chat_response",
                "message": "Please specify which issue number you'd like to work on (e.g., 'let's solve #42' or '/solve 42')."
            }

        # Trigger handoff to coding agent
        self.trigger_handoff(session_id, repo_id, selected_issue, user_background, db, background_tasks)
        
        return {
            "type": "handoff_triggered",
            "selected_issue": selected_issue
        }

    def trigger_handoff(
        self,
        session_id: str,
        repo_id: str,
        selected_issue: int,
        user_background: str,
        db: Session,
        background_tasks,
        steering_instructions: Optional[str] = None
    ):
        """Creates/Updates HandoffSession and schedules background Coding Agent run."""
        logger.info(f"Triggering handoff for session {session_id}, repo {repo_id}, issue #{selected_issue}")
        
        # Query saved onboarding state to extract context files and DNA summary
        state = db.query(OnboardingSessionState).filter_by(session_id=session_id).first()
        dna_summary = state.dna_summary if state else ""
        files_explored = state.files_explored if state else "[]"
        
        # Check if handoff session already exists, or create a new one
        handoff = db.query(HandoffSession).filter_by(session_id=session_id).first()
        if not handoff:
            handoff = HandoffSession(session_id=session_id)
            db.add(handoff)
            
        handoff.repo_id = repo_id
        handoff.selected_issue = selected_issue
        handoff.user_background = user_background
        handoff.steering_instructions = steering_instructions
        handoff.dna_summary = dna_summary
        handoff.files_explored = files_explored
        handoff.status = "pending"
        handoff.progress_pct = 0
        handoff.logs = "[SYSTEM] Handoff initiated. Routing request to coding agent...\n"
        handoff.patch_diff = None
        db.commit()

        # Add Coding Agent loop execution to FastAPI background tasks
        background_tasks.add_task(run_coding_loop, session_id)

_orchestrator = None

def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator
