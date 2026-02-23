from agent_orchestrator.retrieval.incident_knowledge import search_incident_knowledge
from agent_orchestrator.retrieval.previous_issues import search_previous_issues
import agent_orchestrator.retrieval.previous_issues as previous_issues_module


def test_incident_knowledge_returns_grounded_results() -> None:
    results = search_incident_knowledge(
        "payments incident with latency and errors",
        limit=3,
    )

    assert results
    assert all("title" in item and "snippet" in item for item in results)
    assert any(str(item.get("source_id", "")).strip() for item in results)
    assert all(float(item.get("score", 0.0)) >= 0.0 for item in results)
    assert any(str(item.get("why_selected", "")).strip() for item in results)
    assert any(
        ("policy" in item["title"].lower()) or ("runbook" in item["title"].lower())
        for item in results
    )


def test_previous_issues_fts_search_returns_hits() -> None:
    hits = search_previous_issues(
        "username changes are not read",
        limit=3,
    )

    assert hits
    assert hits[0].ticket
    assert hits[0].relevance >= 0.0
    assert hits[0].retrieval_mode in {"lexical", "vector", "hybrid", ""}
    assert hits[0].score >= 0.0
    assert isinstance(hits[0].why_selected, str)


def test_previous_issues_relaxed_fallback_when_filters_are_too_strict() -> None:
    hits = search_previous_issues(
        "user profile picture does not display",
        limit=3,
        service="nonexistent-service-filter",
        severity="nonexistent-severity-filter",
    )

    assert hits


def test_previous_issues_hybrid_fuses_lexical_and_vector(monkeypatch, tmp_path) -> None:
    index_path = tmp_path / "rag_index.sqlite"
    index_path.touch()
    monkeypatch.setattr(previous_issues_module, "rag_index_path", lambda _index: index_path)
    monkeypatch.setattr(
        previous_issues_module,
        "_search_with_relaxation",
        lambda **kwargs: [
            previous_issues_module.PreviousIssueHit(
                ticket="WLC-43",
                summary="User profile picture doesn't display",
                relevance=0.41,
                chunk_id="lex-1",
                doc_id="jira:JiraEcosystem:WLC-43",
                source="jira",
            )
        ],
    )
    monkeypatch.setattr(
        previous_issues_module,
        "_search_chroma_vector_hits",
        lambda **kwargs: [
            previous_issues_module.PreviousIssueHit(
                ticket="WLC-99",
                summary="Avatar rendering regression in profile view",
                relevance=0.92,
                chunk_id="vec-1",
                doc_id="jira:JiraEcosystem:WLC-99",
                source="chroma",
            )
        ],
    )

    hits = previous_issues_module.search_previous_issues(
        "profile avatar rendering issues",
        limit=3,
        use_hybrid=True,
    )

    tickets = [hit.ticket for hit in hits]
    assert "WLC-43" in tickets
    assert "WLC-99" in tickets


def test_previous_issues_lexical_mode_skips_vector_branch(monkeypatch, tmp_path) -> None:
    index_path = tmp_path / "rag_index.sqlite"
    index_path.touch()
    monkeypatch.setattr(previous_issues_module, "rag_index_path", lambda _index: index_path)
    monkeypatch.setattr(
        previous_issues_module,
        "_search_with_relaxation",
        lambda **kwargs: [
            previous_issues_module.PreviousIssueHit(
                ticket="WLC-43",
                summary="User profile picture doesn't display",
                relevance=0.41,
                chunk_id="lex-1",
                doc_id="jira:JiraEcosystem:WLC-43",
                source="jira",
            )
        ],
    )
    monkeypatch.setattr(
        previous_issues_module,
        "_search_chroma_vector_hits",
        lambda **kwargs: [
            previous_issues_module.PreviousIssueHit(
                ticket="WLC-99",
                summary="Avatar rendering regression in profile view",
                relevance=0.92,
                chunk_id="vec-1",
                doc_id="jira:JiraEcosystem:WLC-99",
                source="chroma",
            )
        ],
    )

    hits = previous_issues_module.search_previous_issues(
        "profile avatar rendering issues",
        limit=1,
        use_hybrid=False,
    )

    assert len(hits) == 1
    assert hits[0].ticket == "WLC-43"
