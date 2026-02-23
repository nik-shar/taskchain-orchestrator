"""Deterministic tool implementations for V1."""

from __future__ import annotations

import re

from agent_orchestrator.retrieval import (
    search_incident_knowledge as adapter_search_incident_knowledge,
)
from agent_orchestrator.retrieval import (
    search_previous_issues as adapter_search_previous_issues,
)
from agent_orchestrator.tools.schemas import (
    BriefCitation,
    BuildIncidentBriefInput,
    BuildIncidentBriefOutput,
    ClassifyPriorityInput,
    ClassifyPriorityOutput,
    ExtractActionItemsInput,
    ExtractActionItemsOutput,
    ExtractDeadlinesInput,
    ExtractDeadlinesOutput,
    ExtractEntitiesInput,
    ExtractEntitiesOutput,
    IssueMatch,
    KnowledgeItem,
    SearchIncidentKnowledgeInput,
    SearchIncidentKnowledgeOutput,
    SearchPreviousIssuesInput,
    SearchPreviousIssuesOutput,
    SummarizeInput,
    SummarizeOutput,
)


def extract_entities(payload: ExtractEntitiesInput) -> ExtractEntitiesOutput:
    matches = re.findall(r"\b[A-Z][a-zA-Z0-9_-]*\b", payload.text)
    return ExtractEntitiesOutput(entities=_dedupe(matches))


def summarize(payload: SummarizeInput) -> SummarizeOutput:
    words = payload.text.split()
    summary = " ".join(words[: payload.max_words]).strip()
    return SummarizeOutput(summary=summary)


def extract_deadlines(payload: ExtractDeadlinesInput) -> ExtractDeadlinesOutput:
    patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",
        (
            r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
            r"[a-z]*\s+\d{1,2}(?:,\s*\d{4})?\b"
        ),
        r"\b(?:next|within)\s+\d{1,3}\s+(?:day|days|week|weeks|month|months)\b",
        r"\b(?:by|before)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b(?:eow|eom|end of week|end of month|q[1-4])\b",
    ]
    candidates: list[str] = []
    for pattern in patterns:
        candidates.extend(re.findall(pattern, payload.text, flags=re.IGNORECASE))
    return ExtractDeadlinesOutput(deadlines=_dedupe(candidates))


def extract_action_items(payload: ExtractActionItemsInput) -> ExtractActionItemsOutput:
    action_leads = {
        "prepare",
        "draft",
        "review",
        "send",
        "create",
        "update",
        "fix",
        "investigate",
        "deliver",
        "coordinate",
        "follow",
        "finalize",
        "publish",
    }
    items: list[str] = []
    lines = re.split(r"[\n.;]", payload.text)
    for raw_line in lines:
        line = raw_line.strip(" -*\\t")
        if not line:
            continue
        first_word = line.split(maxsplit=1)[0].lower()
        if (
            first_word in action_leads
            or "owner:" in line.lower()
            or "assignee:" in line.lower()
            or line.lower().startswith("action:")
            or line.lower().startswith("todo:")
        ):
            items.append(line)

    if not items:
        first_sentence = payload.text.split(".")[0].strip()
        if first_sentence:
            items.append(first_sentence)

    return ExtractActionItemsOutput(action_items=_dedupe(items)[:10])


def classify_priority(payload: ClassifyPriorityInput) -> ClassifyPriorityOutput:
    text = payload.text.lower()
    critical_terms = ["sev1", "p0", "outage", "production down", "security incident", "breach"]
    high_terms = ["urgent", "asap", "high priority", "deadline", "exec", "blocking"]
    medium_terms = ["important", "soon", "moderate", "follow up"]

    critical = [term for term in critical_terms if term in text]
    high = [term for term in high_terms if term in text]
    medium = [term for term in medium_terms if term in text]

    if critical:
        return ClassifyPriorityOutput(priority="critical", reasons=critical)
    if high:
        return ClassifyPriorityOutput(priority="high", reasons=high)
    if medium:
        return ClassifyPriorityOutput(priority="medium", reasons=medium)
    return ClassifyPriorityOutput(priority="low", reasons=["no urgency signals detected"])


def search_incident_knowledge(
    payload: SearchIncidentKnowledgeInput,
) -> SearchIncidentKnowledgeOutput:
    results = adapter_search_incident_knowledge(
        payload.query,
        limit=payload.limit,
        service=payload.service,
        severity=payload.severity,
    )
    return SearchIncidentKnowledgeOutput(
        results=[
            KnowledgeItem(
                title=str(item.get("title", "")),
                snippet=str(item.get("snippet", "")),
                source_type=_optional_text(item.get("source_type")),
                source_id=_optional_text(item.get("source_id")),
                score=_optional_float(item.get("score")),
                why_selected=_optional_text(item.get("why_selected")),
            )
            for item in results
        ]
    )


def search_previous_issues(payload: SearchPreviousIssuesInput) -> SearchPreviousIssuesOutput:
    hits = adapter_search_previous_issues(
        payload.query,
        limit=payload.limit,
        service=payload.service,
        severity=payload.severity,
        use_llm_rerank=payload.use_llm_rerank,
        use_hybrid=payload.use_hybrid,
    )
    return SearchPreviousIssuesOutput(
        results=[
            IssueMatch(
                ticket=hit.ticket,
                summary=hit.summary,
                relevance=hit.relevance,
                source=_optional_text(hit.source),
                doc_id=_optional_text(hit.doc_id),
                chunk_id=_optional_text(hit.chunk_id),
                score=_optional_float(hit.score),
                retrieval_mode=_optional_text(hit.retrieval_mode),
                why_selected=_optional_text(hit.why_selected),
            )
            for hit in hits
        ]
    )


def build_incident_brief(payload: BuildIncidentBriefInput) -> BuildIncidentBriefOutput:
    previous = payload.previous_issues
    knowledge = payload.incident_knowledge

    similar_incidents = [
        f"{item.ticket}: {_compact(item.summary, max_chars=120)}"
        for item in previous[:3]
        if item.ticket and item.summary
    ]

    probable_causes = _derive_probable_causes(
        query=payload.query,
        incident_knowledge=knowledge,
        previous_issues=previous,
    )
    recommended_actions = _derive_recommended_actions(
        query=payload.query,
        incident_knowledge=knowledge,
        previous_issues=previous,
    )
    escalation = _derive_escalation_recommendation(payload.query)

    citations = _build_brief_citations(incident_knowledge=knowledge, previous_issues=previous)
    confidence = _estimate_confidence(incident_knowledge=knowledge, previous_issues=previous)

    summary = (
        f"Incident brief for: {payload.query.strip()}. "
        f"Retrieved {len(knowledge)} policy/runbook references and {len(previous)} similar issues. "
        f"Top likely cause: {probable_causes[0] if probable_causes else 'insufficient evidence'}."
    )

    return BuildIncidentBriefOutput(
        summary=summary,
        similar_incidents=similar_incidents,
        probable_causes=probable_causes,
        recommended_actions=recommended_actions,
        escalation_recommendation=escalation,
        confidence=confidence,
        citations=citations,
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = " ".join(value.split()).strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        output.append(normalized)
    return output


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _derive_probable_causes(
    *,
    query: str,
    incident_knowledge: list[KnowledgeItem],
    previous_issues: list[IssueMatch],
) -> list[str]:
    text = " ".join(
        [
            query,
            " ".join(item.snippet for item in incident_knowledge if item.snippet),
            " ".join(item.summary for item in previous_issues if item.summary),
        ]
    ).lower()

    causes: list[str] = []
    if any(token in text for token in ("profile", "avatar", "picture", "image")):
        causes.append("Profile media rendering path may be failing or timing out.")
    if any(token in text for token in ("latency", "slow", "timeout", "timed out")):
        causes.append("Upstream latency or timeout thresholds are likely contributing to failures.")
    if any(token in text for token in ("cache", "stale", "inconsistent")):
        causes.append("Cache inconsistency may be causing stale or missing profile state.")
    if any(token in text for token in ("auth", "permission", "anonymous", "access")):
        causes.append(
            "Authentication or permission context mismatch may block profile asset access."
        )

    if not causes:
        causes.append("No single dominant root cause; further log/trace correlation is required.")
    return causes[:4]


def _derive_recommended_actions(
    *,
    query: str,
    incident_knowledge: list[KnowledgeItem],
    previous_issues: list[IssueMatch],
) -> list[str]:
    actions: list[str] = [
        "Validate current error rate/latency against incident policy thresholds and confirm severity.",
    ]

    if previous_issues:
        top = previous_issues[0]
        actions.append(f"Reproduce against prior incident pattern from ticket {top.ticket}.")
    else:
        actions.append(
            "Run targeted reproduction for affected users and collect request/response traces."
        )

    if any(item.source_type == "policy" for item in incident_knowledge):
        actions.append(
            "Apply policy/runbook escalation steps and notify on-call ownership immediately."
        )
    else:
        actions.append("Gather runbook/policy references before final escalation recommendation.")

    if "profile" in query.lower() or "avatar" in query.lower():
        actions.append(
            "Check media service dependencies and CDN/cache invalidation for profile assets."
        )

    return _dedupe(actions)[:5]


def _derive_escalation_recommendation(query: str) -> str:
    lowered = query.lower()
    if any(token in lowered for token in ("p0", "p1", "sev1", "outage", "production down")):
        return "Escalate immediately to primary and secondary on-call as a high-severity incident."
    if any(token in lowered for token in ("p2", "sev2", "degraded", "intermittent")):
        return "Escalate to service owner and on-call with active monitoring until stabilized."
    return "Use standard triage escalation path and reassess severity after initial diagnostics."


def _build_brief_citations(
    *,
    incident_knowledge: list[KnowledgeItem],
    previous_issues: list[IssueMatch],
) -> list[BriefCitation]:
    citations: list[BriefCitation] = []
    for item in incident_knowledge[:3]:
        reference = item.source_id or item.title
        if not reference:
            continue
        citations.append(
            BriefCitation(
                source_tool="search_incident_knowledge",
                reference=reference,
                snippet=item.snippet,
                score=item.score,
                why_selected=item.why_selected,
            )
        )
    for item in previous_issues[:3]:
        reference = item.ticket or item.doc_id or item.chunk_id
        if not reference:
            continue
        citations.append(
            BriefCitation(
                source_tool="search_previous_issues",
                reference=reference,
                snippet=item.summary,
                score=item.score if item.score is not None else item.relevance,
                why_selected=item.why_selected,
            )
        )
    return citations


def _estimate_confidence(
    *,
    incident_knowledge: list[KnowledgeItem],
    previous_issues: list[IssueMatch],
) -> float:
    if not incident_knowledge and not previous_issues:
        return 0.2

    evidence_count = min(len(incident_knowledge) + len(previous_issues), 6)
    evidence_factor = evidence_count / 6.0

    issue_scores = [
        float(item.score if item.score is not None else item.relevance)
        for item in previous_issues
        if (item.score is not None or item.relevance is not None)
    ]
    knowledge_scores = [float(item.score) for item in incident_knowledge if item.score is not None]
    all_scores = issue_scores + knowledge_scores
    avg_score = sum(all_scores) / len(all_scores) if all_scores else 0.35

    confidence = 0.35 * evidence_factor + 0.65 * max(0.0, min(avg_score, 1.0))
    return round(max(0.0, min(confidence, 1.0)), 4)


def _compact(text: str, *, max_chars: int) -> str:
    compacted = " ".join(text.split()).strip()
    if len(compacted) <= max_chars:
        return compacted
    return compacted[: max_chars - 3].rstrip() + "..."
