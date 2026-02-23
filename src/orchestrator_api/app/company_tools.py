from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal
from urllib import error, parse, request

from pydantic import BaseModel, ConfigDict, Field

from .llm import build_llm_adapter_from_env
from .rag_sqlite import search_rag_index
from .retrieval import search_incident_knowledge as retrieval_search_incident_knowledge


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ReferenceSource = Literal[
    "policy_v1",
    "policy_v2",
    "governance_notes",
    "company_profile",
    "jira_config",
    "slack_config",
    "oncall_rota",
    "github_actions",
    "postgres_config",
]


REFERENCE_SOURCE_PATHS: dict[ReferenceSource, str] = {
    "policy_v1": "policies/policy_v1.md",
    "policy_v2": "policies/policy_v2.md",
    "governance_notes": "docs/governance_notes.md",
    "company_profile": "docs/company_profile.md",
    "jira_config": "tool_configs/jira.yaml",
    "slack_config": "tool_configs/slack.yaml",
    "oncall_rota": "tool_configs/oncall_rota.yaml",
    "github_actions": "tool_configs/github_actions.yaml",
    "postgres_config": "tool_configs/postgres.yaml",
}

CompanyApiName = Literal["jira", "metrics", "logs"]
TicketSeverity = Literal["P1", "P2", "P3"]


class FetchCompanyReferenceInput(StrictModel):
    source: ReferenceSource
    query: str | None = None
    max_chars: int = Field(default=2000, ge=200, le=20000)


class FetchCompanyReferenceOutput(StrictModel):
    source: ReferenceSource
    path: str
    matched: bool
    excerpt: str


class JiraTicket(StrictModel):
    key: str
    project_key: str
    issue_type: str
    summary: str
    description: str
    severity: TicketSeverity
    status: str
    assignee: str | None = None
    labels: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class JiraSearchTicketsInput(StrictModel):
    project_key: str | None = None
    status: str | None = None
    severity: TicketSeverity | None = None
    text: str | None = None


class JiraSearchTicketsOutput(StrictModel):
    total: int
    tickets: list[JiraTicket] = Field(default_factory=list)


class MetricPoint(StrictModel):
    timestamp: str
    service: str
    latency_p95_ms: float
    error_rate: float


class MetricsQueryInput(StrictModel):
    service: str
    start_time: str
    end_time: str


class MetricsQueryOutput(StrictModel):
    service: str
    start_time: str
    end_time: str
    points_count: int
    latency_p95_ms_avg: float
    latency_p95_ms_max: float
    error_rate_avg: float
    error_rate_max: float
    points: list[MetricPoint] = Field(default_factory=list)


class LogEvent(StrictModel):
    timestamp: str
    service: str
    level: str
    pattern: str
    message: str
    trace_id: str


class LogsSearchInput(StrictModel):
    service: str
    start_time: str
    end_time: str
    pattern: str = ""


class LogsSearchOutput(StrictModel):
    service: str
    start_time: str
    end_time: str
    pattern: str
    total: int
    events: list[LogEvent] = Field(default_factory=list)


KnowledgeConfidence = Literal["low", "medium", "high"]


class SearchIncidentKnowledgeInput(StrictModel):
    query: str = Field(min_length=3)
    service: str | None = None
    severity: TicketSeverity | None = None
    time_start: str | None = None
    time_end: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    max_snippet_chars: int = Field(default=360, ge=120, le=2000)


class SearchIncidentKnowledgeHit(StrictModel):
    chunk_id: str
    source_type: str
    source_id: str
    score: float
    snippet: str
    metadata: dict[str, str] = Field(default_factory=dict)
    citation_id: str
    citation_source: str


class SearchIncidentKnowledgeOutput(StrictModel):
    total: int
    confidence: KnowledgeConfidence
    recommend_fallback: bool
    fallback_reason: str | None = None
    hits: list[SearchIncidentKnowledgeHit] = Field(default_factory=list)


RagSource = Literal["jira", "incident_event_log"]


class SearchPreviousIssuesInput(StrictModel):
    query: str = Field(min_length=3)
    top_k: int = Field(default=5, ge=1, le=20)
    source: RagSource | None = None
    collection: str | None = None
    issue_type: str | None = None
    priority: str | None = None
    project: str | None = None
    incident_state: str | None = None
    created_from: str | None = None
    created_to: str | None = None
    opened_from: str | None = None
    opened_to: str | None = None
    max_snippet_chars: int = Field(default=360, ge=120, le=2000)
    index_path: str | None = None
    use_llm_rerank: bool | None = None


class SearchPreviousIssuesHit(StrictModel):
    chunk_id: str
    doc_id: str
    source: str
    score: float
    bm25_score: float
    snippet: str
    metadata: dict[str, str] = Field(default_factory=dict)
    citation_id: str
    citation_source: str


class SearchPreviousIssuesOutput(StrictModel):
    total: int
    ranking_mode: Literal["deterministic", "llm"] = "deterministic"
    confidence: KnowledgeConfidence
    recommend_fallback: bool
    fallback_reason: str | None = None
    hits: list[SearchPreviousIssuesHit] = Field(default_factory=list)


class _RagRerankItem(StrictModel):
    citation_id: str
    relevance: float = Field(ge=0.0, le=1.0)


class _RagRerankOutput(StrictModel):
    ranked: list[_RagRerankItem] = Field(default_factory=list)


def fetch_company_reference(payload: FetchCompanyReferenceInput) -> FetchCompanyReferenceOutput:
    relative_path = REFERENCE_SOURCE_PATHS[payload.source]
    source_path = _company_sim_root() / relative_path
    if not source_path.exists():
        raise RuntimeError(f"Company reference file not found: {source_path}")

    text = source_path.read_text(encoding="utf-8")
    excerpt, matched = _extract_excerpt(text, query=payload.query, max_chars=payload.max_chars)
    return FetchCompanyReferenceOutput(
        source=payload.source,
        path=f"company_sim/{relative_path}",
        matched=matched,
        excerpt=excerpt,
    )


def jira_search_tickets(payload: JiraSearchTicketsInput) -> JiraSearchTicketsOutput:
    raw = _request_json(
        service="jira",
        path="/tickets/search",
        params={
            "project_key": payload.project_key,
            "status": payload.status,
            "severity": payload.severity,
            "text": payload.text,
        },
    )
    return JiraSearchTicketsOutput.model_validate(raw)


def metrics_query(payload: MetricsQueryInput) -> MetricsQueryOutput:
    raw = _request_json(
        service="metrics",
        path="/metrics/query",
        params={
            "service": payload.service,
            "start_time": payload.start_time,
            "end_time": payload.end_time,
        },
    )
    return MetricsQueryOutput.model_validate(raw)


def logs_search(payload: LogsSearchInput) -> LogsSearchOutput:
    raw = _request_json(
        service="logs",
        path="/logs/search",
        params={
            "service": payload.service,
            "start_time": payload.start_time,
            "end_time": payload.end_time,
            "pattern": payload.pattern,
        },
    )
    return LogsSearchOutput.model_validate(raw)


def search_incident_knowledge(
    payload: SearchIncidentKnowledgeInput,
) -> SearchIncidentKnowledgeOutput:
    result = retrieval_search_incident_knowledge(
        query=payload.query,
        service=payload.service,
        severity=payload.severity,
        time_start=payload.time_start,
        time_end=payload.time_end,
        top_k=payload.top_k,
    )
    hits = [
        SearchIncidentKnowledgeHit(
            chunk_id=hit.chunk_id,
            source_type=hit.source_type,
            source_id=hit.source_id,
            score=hit.score,
            snippet=_snippet(hit.text, max_chars=payload.max_snippet_chars),
            metadata=hit.metadata,
            citation_id=hit.chunk_id,
            citation_source=hit.source_id,
        )
        for hit in result.hits
    ]
    return SearchIncidentKnowledgeOutput(
        total=len(hits),
        confidence=result.confidence,
        recommend_fallback=result.recommend_fallback,
        fallback_reason=result.fallback_reason,
        hits=hits,
    )


def search_previous_issues(payload: SearchPreviousIssuesInput) -> SearchPreviousIssuesOutput:
    index_path = _rag_index_path(payload.index_path)
    search_kwargs: dict[str, Any] = {
        "index_db_path": index_path,
        "query": payload.query,
        "top_k": _rag_candidate_top_k(payload.top_k),
        "source": payload.source,
        "collection": payload.collection,
        "issue_type": payload.issue_type,
        "priority": payload.priority,
        "project": payload.project,
        "incident_state": payload.incident_state,
        "created_from": payload.created_from,
        "created_to": payload.created_to,
        "opened_from": payload.opened_from,
        "opened_to": payload.opened_to,
    }
    try:
        result = _search_rag_with_relaxation(search_kwargs)
    except Exception as exc:  # noqa: BLE001
        return SearchPreviousIssuesOutput(
            total=0,
            confidence="low",
            recommend_fallback=True,
            fallback_reason=f"RAG index search unavailable: {exc}",
            hits=[],
        )

    hits = [
        SearchPreviousIssuesHit(
            chunk_id=hit.chunk_id,
            doc_id=hit.doc_id,
            source=hit.source,
            score=round(max(-hit.bm25_score, 0.0), 4),
            bm25_score=round(hit.bm25_score, 4),
            snippet=_snippet(hit.snippet or hit.text, max_chars=payload.max_snippet_chars),
            metadata=hit.metadata,
            citation_id=hit.chunk_id,
            citation_source=hit.doc_id,
        )
        for hit in result.hits
    ]

    ranking_mode: Literal["deterministic", "llm"] = "deterministic"
    if _should_use_llm_rerank(payload):
        hits, ranking_mode = _apply_llm_rerank(payload.query, hits, top_k=payload.top_k)
    else:
        hits = hits[: payload.top_k]

    confidence, recommend_fallback, fallback_reason = _rag_confidence(
        hits,
        ranking_mode=ranking_mode,
    )
    return SearchPreviousIssuesOutput(
        total=len(hits),
        ranking_mode=ranking_mode,
        confidence=confidence,
        recommend_fallback=recommend_fallback,
        fallback_reason=fallback_reason,
        hits=hits,
    )


def _search_rag_with_relaxation(search_kwargs: dict[str, Any]):
    result = search_rag_index(**search_kwargs)
    if result.hits:
        return result

    relaxed = dict(search_kwargs)
    if relaxed.get("source") == "incident_event_log":
        relaxed["project"] = None
        relaxed["collection"] = None
        relaxed["issue_type"] = None
        relaxed["created_from"] = None
        relaxed["created_to"] = None
        relaxed["opened_from"] = None
        relaxed["opened_to"] = None
        result = search_rag_index(**relaxed)
        if result.hits:
            return result

    if search_kwargs.get("source") is not None:
        broader = dict(search_kwargs)
        broader["source"] = None
        broader["created_from"] = None
        broader["created_to"] = None
        broader["opened_from"] = None
        broader["opened_to"] = None
        result = search_rag_index(**broader)
        if result.hits:
            return result

    if search_kwargs.get("project") is not None:
        broadest = dict(search_kwargs)
        broadest["project"] = None
        broadest["source"] = None
        broadest["created_from"] = None
        broadest["created_to"] = None
        broadest["opened_from"] = None
        broadest["opened_to"] = None
        return search_rag_index(**broadest)

    return result


def _company_sim_root() -> Path:
    configured = os.getenv("ORCHESTRATOR_COMPANY_SIM_ROOT")
    if configured:
        configured_path = Path(configured).expanduser().resolve()
        if configured_path.exists():
            return configured_path
    return Path(__file__).resolve().parents[3] / "company_details" / "company_sim"


def _rag_index_path(explicit_path: str | None) -> Path:
    if explicit_path:
        return Path(explicit_path).expanduser().resolve()
    configured = os.getenv("ORCHESTRATOR_RAG_INDEX_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "data" / "rag_index.sqlite"


def _rag_confidence(
    hits: list[SearchPreviousIssuesHit],
    *,
    ranking_mode: Literal["deterministic", "llm"],
) -> tuple[KnowledgeConfidence, bool, str | None]:
    if not hits:
        return "low", True, "No previous-issue evidence matched the query."
    top_score = hits[0].score
    if ranking_mode == "llm":
        if top_score >= 0.75:
            return "high", False, None
        if top_score >= 0.35:
            return "medium", False, None
        return "low", True, "Retrieved matches are weak; broaden query or filters."
    if top_score >= 12:
        return "high", False, None
    return "medium", False, None


def _rag_candidate_top_k(top_k: int) -> int:
    normalized = max(1, top_k)
    return min(max(normalized * 3, normalized), 60)


def _should_use_llm_rerank(payload: SearchPreviousIssuesInput) -> bool:
    if payload.use_llm_rerank is not None:
        return payload.use_llm_rerank
    mode = os.getenv("ORCHESTRATOR_RAG_RERANK_MODE", "auto").strip().lower()
    if mode == "deterministic":
        return False
    if mode == "llm":
        return True
    return build_llm_adapter_from_env() is not None


def _apply_llm_rerank(
    query: str,
    hits: list[SearchPreviousIssuesHit],
    *,
    top_k: int,
) -> tuple[list[SearchPreviousIssuesHit], Literal["deterministic", "llm"]]:
    if not hits:
        return [], "deterministic"

    llm = build_llm_adapter_from_env()
    if llm is None:
        return hits[:top_k], "deterministic"

    candidates = [
        {
            "citation_id": hit.citation_id,
            "source": hit.source,
            "metadata": hit.metadata,
            "snippet": hit.snippet,
        }
        for hit in hits
    ]
    system_prompt = (
        "You are a retrieval reranker. Rank candidates by relevance to the query. "
        "Return JSON only with key 'ranked'. Each item must include citation_id and relevance "
        "between 0 and 1. Include at most 20 items."
    )
    user_prompt = (
        f"Query: {query}\n\n"
        "Candidates JSON:\n"
        f"{json.dumps(candidates, ensure_ascii=True)}\n"
    )
    timeout_s = _env_float("ORCHESTRATOR_RAG_RERANK_TIMEOUT_S", default=8.0)
    try:
        reranked = llm.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=_RagRerankOutput,
            timeout_s=timeout_s,
        )
    except Exception:  # noqa: BLE001
        return hits[:top_k], "deterministic"

    score_map = {item.citation_id: item.relevance for item in reranked.ranked}
    if not score_map:
        return hits[:top_k], "deterministic"

    ordered = sorted(
        hits,
        key=lambda hit: (
            score_map.get(hit.citation_id, -1.0),
            hit.score,
        ),
        reverse=True,
    )
    reranked_hits: list[SearchPreviousIssuesHit] = []
    for hit in ordered[:top_k]:
        relevance = score_map.get(hit.citation_id)
        if relevance is None:
            reranked_hits.append(hit)
            continue
        reranked_hits.append(hit.model_copy(update={"score": round(relevance, 4)}))
    return reranked_hits, "llm"


def _extract_excerpt(text: str, *, query: str | None, max_chars: int) -> tuple[str, bool]:
    full_excerpt = text[:max_chars].strip()
    if not query:
        return full_excerpt, False

    lines = text.splitlines()
    query_lower = query.lower().strip()
    query_terms = [term for term in query_lower.split() if term]
    matched_lines: list[int] = []

    for index, line in enumerate(lines):
        lowered = line.lower()
        if query_lower in lowered or any(term in lowered for term in query_terms):
            matched_lines.append(index)

    if not matched_lines:
        return full_excerpt, False

    selected_indexes: set[int] = set()
    for idx in matched_lines[:12]:
        for candidate in range(max(0, idx - 1), min(len(lines), idx + 2)):
            selected_indexes.add(candidate)

    excerpt_lines = [lines[idx] for idx in sorted(selected_indexes)]
    excerpt = "\n".join(excerpt_lines).strip()
    return excerpt[:max_chars], True


def _request_json(
    *,
    service: CompanyApiName,
    path: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = _service_url(service, path, params=params)
    req = request.Request(url=url, method="GET", headers={"Accept": "application/json"})
    timeout_s = _env_float("ORCHESTRATOR_COMPANY_TOOL_TIMEOUT_S", default=10.0)

    try:
        with request.urlopen(req, timeout=timeout_s) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{service} tool request failed with status {exc.code}: {body[:300]}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"{service} tool request failed: {exc.reason}") from exc

    if not body:
        return {}
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{service} tool returned non-JSON response.") from exc
    if isinstance(parsed, dict):
        return parsed
    raise RuntimeError(f"{service} tool returned unsupported JSON shape: {type(parsed)!r}")


def _service_url(
    service: CompanyApiName,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> str:
    base = _service_base_url(service)
    url = f"{base}{path}"
    if not params:
        return url
    encoded = parse.urlencode(
        {key: value for key, value in params.items() if value is not None},
        doseq=True,
    )
    if not encoded:
        return url
    return f"{url}?{encoded}"


def _service_base_url(service: CompanyApiName) -> str:
    defaults = {
        "jira": "http://127.0.0.1:8001",
        "metrics": "http://127.0.0.1:8002",
        "logs": "http://127.0.0.1:8003",
    }
    env_vars = {
        "jira": "COMPANY_JIRA_BASE_URL",
        "metrics": "COMPANY_METRICS_BASE_URL",
        "logs": "COMPANY_LOGS_BASE_URL",
    }
    return os.getenv(env_vars[service], defaults[service]).rstrip("/")


def _env_float(name: str, *, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _snippet(text: str, *, max_chars: int) -> str:
    compact = " ".join(text.split()).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."
