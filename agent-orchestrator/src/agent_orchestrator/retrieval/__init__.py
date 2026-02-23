"""Retrieval adapters for incident knowledge and previous issues."""

from agent_orchestrator.retrieval.incident_knowledge import search_incident_knowledge
from agent_orchestrator.retrieval.previous_issues import PreviousIssueHit, search_previous_issues

__all__ = [
    "PreviousIssueHit",
    "search_incident_knowledge",
    "search_previous_issues",
]
