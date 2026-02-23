"""Deterministic incident knowledge retrieval over company_sim docs/policies/tickets."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent_orchestrator.retrieval.shared_paths import company_sim_root


@dataclass(frozen=True)
class KnowledgeChunk:
    title: str
    text: str
    source_type: str
    source_id: str
    service: str | None = None
    severity: str | None = None


def search_incident_knowledge(
    query: str,
    *,
    limit: int = 3,
    service: str | None = None,
    severity: str | None = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    corpus = _incident_corpus(str((root or company_sim_root()).resolve()))
    tokens = _tokenize(query)
    if not tokens:
        return []

    ranked: list[tuple[float, KnowledgeChunk]] = []
    for chunk in corpus:
        if service and chunk.service and chunk.service.lower() != service.lower():
            continue
        if severity and chunk.severity and chunk.severity.upper() != severity.upper():
            continue
        score = _lexical_overlap(tokens, chunk.text)
        if score <= 0:
            continue
        ranked.append((score, chunk))

    ranked.sort(key=lambda item: item[0], reverse=True)
    chosen_ranked = ranked[: max(limit, 1)]
    chosen = [chunk for _, chunk in chosen_ranked]

    if chosen and not _has_policy_or_runbook(chosen):
        policy_candidate = _best_policy_or_runbook(ranked)
        if policy_candidate is not None:
            chosen_ranked = chosen_ranked[:-1] + [
                (_score_for_chunk(ranked, policy_candidate), policy_candidate)
            ]
            chosen = [chunk for _, chunk in chosen_ranked]

    if not chosen:
        fallback = _best_policy_or_runbook(ranked)
        if fallback is not None:
            chosen_ranked = [(_score_for_chunk(ranked, fallback), fallback)]
            chosen = [fallback]

    query_tokens = _tokenize(query)
    output: list[dict[str, Any]] = []
    for score, chunk in chosen_ranked[: max(limit, 1)]:
        output.append(
            {
                "title": chunk.title,
                "snippet": _snippet(chunk.text),
                "source_type": chunk.source_type,
                "source_id": chunk.source_id,
                "score": round(max(score, 0.0), 4),
                "why_selected": _build_incident_why_selected(query_tokens, chunk),
            }
        )
    return output


@lru_cache(maxsize=4)
def _incident_corpus(root_text: str) -> tuple[KnowledgeChunk, ...]:
    root = Path(root_text)
    chunks: list[KnowledgeChunk] = []

    for path in sorted((root / "policies").glob("*.md")):
        chunks.extend(_chunks_from_markdown(path, source_type="policy"))

    for path in sorted((root / "docs").glob("*.md")):
        chunks.extend(_chunks_from_markdown(path, source_type="doc"))

    tickets_path = root / "mock_systems" / "data" / "jira_tickets.json"
    if tickets_path.exists():
        try:
            raw = json.loads(tickets_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raw = {}
        tickets = raw.get("tickets", []) if isinstance(raw, dict) else []
        if isinstance(tickets, list):
            for ticket in tickets:
                if not isinstance(ticket, dict):
                    continue
                chunks.append(_chunk_from_ticket(ticket))

    return tuple(chunks)


def _chunks_from_markdown(path: Path, *, source_type: str) -> list[KnowledgeChunk]:
    text = path.read_text(encoding="utf-8")
    pieces = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    output: list[KnowledgeChunk] = []

    base_title = path.stem.replace("_", " ").title()
    prefix = "Policy" if source_type == "policy" else "Runbook"

    for idx, piece in enumerate(pieces):
        title = f"{prefix}: {base_title}"
        if idx > 0:
            title = f"{title} (section {idx + 1})"
        output.append(
            KnowledgeChunk(
                title=title,
                text=piece,
                source_type=source_type,
                source_id=str(path),
            )
        )
    return output


def _chunk_from_ticket(ticket: dict[str, object]) -> KnowledgeChunk:
    key = str(ticket.get("key", "UNKNOWN"))
    summary = str(ticket.get("summary", "")).strip()
    description = str(ticket.get("description", "")).strip()
    status = str(ticket.get("status", "")).strip()
    project = str(ticket.get("project_key", "")).strip()
    severity = str(ticket.get("severity", "")).strip()

    text = (
        f"Ticket {key}. Summary: {summary}. Description: {description}. "
        f"Status: {status}. Project: {project}. Severity: {severity}."
    )

    return KnowledgeChunk(
        title=f"Ticket {key}: {summary}",
        text=text,
        source_type="jira_ticket",
        source_id=key,
        service=project,
        severity=severity,
    )


def _tokenize(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-z0-9_:-]+", text.lower()) if len(tok) > 1}


def _lexical_overlap(query_tokens: set[str], text: str) -> float:
    tokens = _tokenize(text)
    if not tokens:
        return 0.0
    overlap = len(query_tokens & tokens)
    if overlap == 0:
        return 0.0
    return overlap / math.sqrt(len(query_tokens) * len(tokens))


def _snippet(text: str, max_chars: int = 260) -> str:
    compact = " ".join(text.split()).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _has_policy_or_runbook(chunks: list[KnowledgeChunk]) -> bool:
    return any(
        "policy" in chunk.title.lower() or "runbook" in chunk.title.lower() for chunk in chunks
    )


def _best_policy_or_runbook(ranked: list[tuple[float, KnowledgeChunk]]) -> KnowledgeChunk | None:
    for _, chunk in ranked:
        title = chunk.title.lower()
        if "policy" in title or "runbook" in title:
            return chunk
    return None


def _score_for_chunk(ranked: list[tuple[float, KnowledgeChunk]], target: KnowledgeChunk) -> float:
    for score, chunk in ranked:
        if chunk == target:
            return float(score)
    return 0.0


def _build_incident_why_selected(query_tokens: set[str], chunk: KnowledgeChunk) -> str:
    overlap_terms = _overlap_terms(query_tokens, chunk.text)
    if overlap_terms:
        return f"lexical overlap on terms: {', '.join(overlap_terms)}"
    if chunk.source_type == "policy":
        return "selected as policy grounding evidence for incident response."
    if chunk.source_type == "doc":
        return "selected as runbook/reference context for incident response."
    return "selected as incident-related context."


def _overlap_terms(query_tokens: set[str], text: str, *, limit: int = 5) -> list[str]:
    terms = sorted(query_tokens & _tokenize(text))
    return terms[:limit]
