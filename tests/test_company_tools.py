from __future__ import annotations

import json
from urllib import request

import pytest

from orchestrator_api.app import company_tools
from orchestrator_api.app.company_tools import (
    FetchCompanyReferenceInput,
    JiraSearchTicketsInput,
    SearchIncidentKnowledgeInput,
    SearchPreviousIssuesInput,
    jira_search_tickets,
    search_incident_knowledge,
    search_previous_issues,
)
from orchestrator_api.app.models import Plan, Step, ToolCall
from orchestrator_api.app.planner import Planner
from orchestrator_api.app.rag_sqlite import build_rag_sqlite_index
from orchestrator_api.app.retrieval import RetrievalHit, RetrievalResult


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._raw_body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw_body

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        _ = (exc_type, exc, tb)
        return False


def test_fetch_company_reference_returns_matching_excerpt() -> None:
    output = company_tools.fetch_company_reference(
        FetchCompanyReferenceInput(source="policy_v2", query="rollback", max_chars=500)
    )

    assert output.path == "company_sim/policies/policy_v2.md"
    assert output.matched is True
    assert "rollback" in output.excerpt.lower()


def test_jira_search_tickets_uses_configured_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def fake_urlopen(req: request.Request, timeout: float):
        captured["url"] = req.full_url
        captured["timeout"] = str(timeout)
        return _FakeHTTPResponse(
            {
                "total": 1,
                "tickets": [
                    {
                        "key": "OPS-101",
                        "project_key": "OPS",
                        "issue_type": "Incident",
                        "summary": "Latency spike",
                        "description": "Synthetic issue for tests",
                        "severity": "P1",
                        "status": "Investigating",
                        "assignee": "Jordan Patel",
                        "labels": ["incident"],
                        "created_at": "2026-02-14T10:00:00Z",
                        "updated_at": "2026-02-14T10:05:00Z",
                    }
                ],
            }
        )

    monkeypatch.setenv("COMPANY_JIRA_BASE_URL", "http://jira.example:9001")
    monkeypatch.setenv("ORCHESTRATOR_COMPANY_TOOL_TIMEOUT_S", "4.5")
    monkeypatch.setattr(company_tools.request, "urlopen", fake_urlopen)

    result = jira_search_tickets(
        JiraSearchTicketsInput(project_key="OPS", status="Investigating", severity="P1")
    )

    assert result.total == 1
    assert result.tickets[0].key == "OPS-101"
    assert (
        captured["url"]
        == "http://jira.example:9001/tickets/search?project_key=OPS&status=Investigating&severity=P1"
    )
    assert captured["timeout"] == "4.5"


def test_planner_accepts_company_tools_in_llm_mode() -> None:
    class CompanyAwareAdapter:
        def generate_structured(self, **kwargs):
            response_model = kwargs["response_model"]
            if response_model is Plan:
                return Plan(
                    steps=[
                        Step(
                            step_id="reference_lookup",
                            description="Get policy excerpt",
                            tool_calls=[
                                ToolCall(
                                    tool="fetch_company_reference",
                                    args={"source": "policy_v2", "query": "escalation"},
                                )
                            ],
                        ),
                        Step(
                            step_id="summarize",
                            description="Summarize findings",
                            tool_calls=[
                                ToolCall(
                                    tool="summarize",
                                    args={"text": "Use policy evidence", "max_words": 20},
                                )
                            ],
                        ),
                    ]
                )
            raise AssertionError("Unexpected model requested")

    planner = Planner(mode="llm", llm_adapter=CompanyAwareAdapter(), timeout_s=2.0)
    plan = planner.build_plan("Find escalation policy details.")

    assert plan.steps[0].tool_calls[0].tool == "fetch_company_reference"
    assert plan.steps[1].tool_calls[0].tool == "summarize"


def test_search_incident_knowledge_returns_ranked_hits() -> None:
    output = search_incident_knowledge(
        SearchIncidentKnowledgeInput(
            query="rollback trigger error rate and escalation policy",
            top_k=4,
        )
    )

    assert output.total >= 1
    assert len(output.hits) >= 1
    assert output.hits[0].score >= output.hits[-1].score
    first = output.hits[0]
    assert first.source_id
    assert first.snippet
    assert first.citation_id
    assert first.citation_source
    assert isinstance(first.metadata, dict)


def test_search_incident_knowledge_respects_top_k() -> None:
    output = search_incident_knowledge(
        SearchIncidentKnowledgeInput(
            query="incident escalation communication cadence",
            top_k=1,
        )
    )

    assert output.total == 1
    assert len(output.hits) == 1


def test_search_incident_knowledge_relaxes_filters_when_strict_search_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_retrieval_search_incident_knowledge(**kwargs):
        calls.append(dict(kwargs))
        if kwargs.get("time_start") is not None or kwargs.get("time_end") is not None:
            return RetrievalResult(
                hits=[],
                confidence="low",
                recommend_fallback=True,
                fallback_reason="No relevant incident evidence found.",
            )
        return RetrievalResult(
            hits=[
                RetrievalHit(
                    chunk_id="jira:OPS-101:0",
                    source_type="jira_ticket",
                    source_id="OPS-101",
                    text="Ticket OPS-101 summary includes escalation guidance.",
                    metadata={"service": "saas-api", "severity": "P1"},
                    score=0.41,
                )
            ],
            confidence="medium",
            recommend_fallback=False,
            fallback_reason=None,
        )

    monkeypatch.setattr(
        company_tools,
        "retrieval_search_incident_knowledge",
        fake_retrieval_search_incident_knowledge,
    )

    output = search_incident_knowledge(
        SearchIncidentKnowledgeInput(
            query="P1 alert escalation guidance",
            service="saas-api",
            severity="P1",
            time_start="2026-02-14T10:00:00Z",
            time_end="2026-02-14T10:30:00Z",
            top_k=3,
        )
    )

    assert output.total == 1
    assert output.hits[0].citation_id == "jira:OPS-101:0"
    assert len(calls) == 2
    assert calls[0]["time_start"] == "2026-02-14T10:00:00Z"
    assert calls[1]["time_start"] is None
    assert calls[1]["time_end"] is None


def test_search_previous_issues_returns_hits_from_local_rag_index(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus_path = tmp_path / "subset.jsonl"
    corpus_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "doc_id": "jira:WLC-1",
                        "source": "jira",
                        "text": (
                            "Project: WLC\nIssueType: Bug\nPriority: Major\nStatus: To Do\n"
                            "Summary: Username changes are not read by WL"
                        ),
                        "metadata": {
                            "collection": "JiraEcosystem",
                            "project": "WLC",
                            "issue_type": "Bug",
                            "priority": "Major",
                            "created": "2018-03-25T23:04:58.826-0500",
                        },
                    }
                ),
                json.dumps(
                    {
                        "doc_id": "incident:INC1",
                        "source": "incident_event_log",
                        "text": (
                            "Incident: INC1\nState: Closed\nPriority: 2 - High\n"
                            "Category: Category 56"
                        ),
                        "metadata": {
                            "state": "Closed",
                            "priority": "2 - High",
                            "opened_at": "01/01/2017 01:43",
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    index_path = tmp_path / "rag.sqlite"
    build_rag_sqlite_index(
        corpus_jsonl_path=corpus_path,
        index_db_path=index_path,
        chunk_chars=900,
        overlap_chars=120,
        reset=True,
    )
    monkeypatch.setenv("ORCHESTRATOR_RAG_INDEX_PATH", str(index_path))

    output = search_previous_issues(
        SearchPreviousIssuesInput(
            query="username changes bug",
            source="jira",
            top_k=3,
            project="WLC",
        )
    )

    assert output.total >= 1
    assert output.hits[0].source == "jira"
    assert output.hits[0].citation_id
    assert output.confidence in {"medium", "high"}


def test_search_previous_issues_can_use_llm_reranking(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus_path = tmp_path / "subset.jsonl"
    corpus_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "doc_id": "jira:WLC-1",
                        "source": "jira",
                        "text": (
                            "Project: WLC\nIssueType: Bug\nPriority: Major\n"
                            "Summary: Username display issue"
                        ),
                        "metadata": {"project": "WLC", "issue_type": "Bug"},
                    }
                ),
                json.dumps(
                    {
                        "doc_id": "jira:WLC-2",
                        "source": "jira",
                        "text": (
                            "Project: WLC\nIssueType: Bug\nPriority: Major\n"
                            "Summary: Username changes are not read by WL"
                        ),
                        "metadata": {"project": "WLC", "issue_type": "Bug"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    index_path = tmp_path / "rag.sqlite"
    build_rag_sqlite_index(
        corpus_jsonl_path=corpus_path,
        index_db_path=index_path,
        chunk_chars=900,
        overlap_chars=120,
        reset=True,
    )
    monkeypatch.setenv("ORCHESTRATOR_RAG_INDEX_PATH", str(index_path))
    monkeypatch.setenv("ORCHESTRATOR_RAG_RERANK_MODE", "llm")

    class FakeRerankAdapter:
        def generate_structured(self, **kwargs):
            response_model = kwargs["response_model"]
            return response_model.model_validate(
                {
                    "ranked": [
                        {"citation_id": "jira:WLC-2#c0", "relevance": 0.94},
                        {"citation_id": "jira:WLC-1#c0", "relevance": 0.22},
                    ]
                }
            )

    monkeypatch.setattr(company_tools, "build_llm_adapter_from_env", lambda: FakeRerankAdapter())

    output = search_previous_issues(
        SearchPreviousIssuesInput(
            query="username issue",
            source="jira",
            top_k=2,
            project="WLC",
        )
    )

    assert output.ranking_mode == "llm"
    assert output.hits
    assert output.hits[0].doc_id == "jira:WLC-2"
    assert output.hits[0].score >= output.hits[1].score


def test_search_previous_issues_relaxes_over_restrictive_filters(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus_path = tmp_path / "subset.jsonl"
    corpus_path.write_text(
        json.dumps(
            {
                "doc_id": "jira:WLC-9",
                "source": "jira",
                "text": (
                    "Project: WLC\nIssueType: Bug\nPriority: Major\n"
                    "Summary: Username profile update not reflected"
                ),
                "metadata": {
                    "project": "WLC",
                    "issue_type": "Bug",
                    "priority": "Major",
                    "created": "2019-01-01T00:00:00.000+0000",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    index_path = tmp_path / "rag.sqlite"
    build_rag_sqlite_index(
        corpus_jsonl_path=corpus_path,
        index_db_path=index_path,
        chunk_chars=900,
        overlap_chars=120,
        reset=True,
    )
    monkeypatch.setenv("ORCHESTRATOR_RAG_INDEX_PATH", str(index_path))
    monkeypatch.setenv("ORCHESTRATOR_RAG_RERANK_MODE", "deterministic")

    output = search_previous_issues(
        SearchPreviousIssuesInput(
            query="username profile update",
            source="incident_event_log",
            project="OPS",
            opened_from="2026-02-14T10:00:00Z",
            opened_to="2026-02-14T10:30:00Z",
            top_k=3,
        )
    )

    assert output.total >= 1
    assert output.hits[0].doc_id == "jira:WLC-9"
