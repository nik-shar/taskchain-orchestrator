from __future__ import annotations

from orchestrator_api.app.retrieval import search_incident_knowledge


def test_search_incident_knowledge_ranks_relevant_chunks() -> None:
    result = search_incident_knowledge(
        query="rollback trigger error rate 2.5 percent for production incident",
        top_k=3,
    )

    assert result.hits
    top_hit = result.hits[0]
    assert top_hit.source_type == "policy"
    assert "rollback" in top_hit.text.lower()
    assert any("policy_v" in hit.source_id for hit in result.hits)
    assert result.confidence in {"medium", "high"}
    assert result.recommend_fallback is False


def test_search_incident_knowledge_applies_metadata_filters() -> None:
    result = search_incident_knowledge(
        query="intermittent api gateway errors and customer impact",
        service="saas-api",
        severity="P2",
        time_start="2026-02-14T09:59:00Z",
        time_end="2026-02-14T10:04:00Z",
        top_k=5,
    )

    assert result.hits
    for hit in result.hits:
        assert hit.source_type == "jira_ticket"
        assert hit.metadata.get("service") == "saas-api"
        assert hit.metadata.get("severity") == "P2"
        event_time = hit.metadata.get("event_time")
        assert event_time is not None
        assert "2026-02-14T10:03:00Z" == event_time


def test_search_incident_knowledge_low_confidence_when_no_match() -> None:
    result = search_incident_knowledge(
        query="qzxv nonexisting signal quantum rainbow parser fault",
        top_k=3,
    )

    assert result.hits == []
    assert result.confidence == "low"
    assert result.recommend_fallback is True
    assert result.fallback_reason is not None
