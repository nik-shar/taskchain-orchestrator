from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

ConfidenceLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    source_type: str
    source_id: str
    text: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class RetrievalHit:
    chunk_id: str
    source_type: str
    source_id: str
    text: str
    metadata: dict[str, str]
    score: float


@dataclass(frozen=True)
class RetrievalResult:
    hits: list[RetrievalHit]
    confidence: ConfidenceLevel
    recommend_fallback: bool
    fallback_reason: str | None = None


def search_incident_knowledge(
    query: str,
    *,
    service: str | None = None,
    severity: str | None = None,
    time_start: str | None = None,
    time_end: str | None = None,
    top_k: int = 5,
    min_score: float = 0.08,
    company_sim_root: Path | None = None,
) -> RetrievalResult:
    corpus = build_incident_corpus(company_sim_root=company_sim_root)
    query_tokens = _tokenize(query)
    if not query_tokens:
        return RetrievalResult(
            hits=[],
            confidence="low",
            recommend_fallback=True,
            fallback_reason="Query is empty after tokenization.",
        )

    ranked: list[RetrievalHit] = []
    for chunk in corpus:
        if not _matches_metadata_filters(
            chunk=chunk,
            service=service,
            severity=severity,
            time_start=time_start,
            time_end=time_end,
        ):
            continue
        score = _lexical_overlap_score(query_tokens, chunk.text)
        if score < min_score:
            continue
        ranked.append(
            RetrievalHit(
                chunk_id=chunk.chunk_id,
                source_type=chunk.source_type,
                source_id=chunk.source_id,
                text=chunk.text,
                metadata=dict(chunk.metadata),
                score=round(score, 4),
            )
        )

    ranked.sort(key=lambda item: item.score, reverse=True)
    hits = ranked[: max(top_k, 1)]

    confidence, recommend_fallback, fallback_reason = _confidence_and_fallback(hits)
    return RetrievalResult(
        hits=hits,
        confidence=confidence,
        recommend_fallback=recommend_fallback,
        fallback_reason=fallback_reason,
    )


def build_incident_corpus(
    *,
    company_sim_root: Path | None = None,
    max_chunk_chars: int = 700,
    overlap_chars: int = 120,
) -> list[KnowledgeChunk]:
    root = _company_sim_root(company_sim_root)
    chunks: list[KnowledgeChunk] = []

    policies_dir = root / "policies"
    docs_dir = root / "docs"

    for file_path in sorted(policies_dir.glob("*.md")):
        chunks.extend(
            _chunk_document_file(
                file_path=file_path,
                source_type="policy",
                source_prefix="policy",
                max_chunk_chars=max_chunk_chars,
                overlap_chars=overlap_chars,
            )
        )

    for file_path in sorted(docs_dir.glob("*.md")):
        chunks.extend(
            _chunk_document_file(
                file_path=file_path,
                source_type="doc",
                source_prefix="doc",
                max_chunk_chars=max_chunk_chars,
                overlap_chars=overlap_chars,
            )
        )

    jira_path = root / "mock_systems" / "data" / "jira_tickets.json"
    if jira_path.exists():
        raw = json.loads(jira_path.read_text(encoding="utf-8"))
        tickets = raw.get("tickets", [])
        if isinstance(tickets, list):
            for ticket in tickets:
                if not isinstance(ticket, dict):
                    continue
                chunks.extend(_chunks_from_jira_ticket(ticket=ticket))

    return chunks


def corpus_to_json_serializable(corpus: list[KnowledgeChunk]) -> list[dict[str, object]]:
    return [asdict(item) for item in corpus]


def _chunks_from_jira_ticket(ticket: dict[str, object]) -> list[KnowledgeChunk]:
    key = str(ticket.get("key", "UNKNOWN"))
    summary = str(ticket.get("summary", "")).strip()
    description = str(ticket.get("description", "")).strip()
    labels = ticket.get("labels", [])
    labels_text = ", ".join(labels) if isinstance(labels, list) else ""

    text = (
        f"Ticket {key}. "
        f"Summary: {summary}. "
        f"Description: {description}. "
        f"Status: {ticket.get('status', '')}. "
        f"Issue type: {ticket.get('issue_type', '')}. "
        f"Labels: {labels_text}."
    ).strip()
    metadata: dict[str, str] = {
        "ticket_key": key,
        "project_key": str(ticket.get("project_key", "")).upper(),
        "severity": str(ticket.get("severity", "")).upper(),
        "service": _infer_service(ticket),
        "created_at": str(ticket.get("created_at", "")),
        "updated_at": str(ticket.get("updated_at", "")),
        "event_time": str(ticket.get("updated_at", "") or ticket.get("created_at", "")),
    }
    chunk = KnowledgeChunk(
        chunk_id=f"jira:{key}:0",
        source_type="jira_ticket",
        source_id=key,
        text=text,
        metadata=metadata,
    )
    return [chunk]


def _chunk_document_file(
    *,
    file_path: Path,
    source_type: str,
    source_prefix: str,
    max_chunk_chars: int,
    overlap_chars: int,
) -> list[KnowledgeChunk]:
    text = file_path.read_text(encoding="utf-8")
    unit = file_path.name
    chunk_texts = _chunk_text(
        text=text,
        max_chunk_chars=max_chunk_chars,
        overlap_chars=overlap_chars,
    )
    chunks: list[KnowledgeChunk] = []
    for index, chunk_text in enumerate(chunk_texts):
        chunks.append(
            KnowledgeChunk(
                chunk_id=f"{source_prefix}:{unit}:{index}",
                source_type=source_type,
                source_id=str(file_path),
                text=chunk_text,
                metadata={
                    "file_name": unit,
                    "file_path": str(file_path),
                },
            )
        )
    return chunks


def _chunk_text(*, text: str, max_chunk_chars: int, overlap_chars: int) -> list[str]:
    cleaned = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if not cleaned:
        return []

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chunk_chars:
            current = candidate
            continue

        if current:
            chunks.append(current.strip())
            tail = current[-overlap_chars:] if overlap_chars > 0 else ""
            current = f"{tail}\n\n{paragraph}".strip()
        else:
            for segment in _slice_long_paragraph(paragraph, max_chunk_chars=max_chunk_chars):
                chunks.append(segment)
            current = ""

    if current:
        chunks.append(current.strip())

    return [chunk for chunk in chunks if chunk]


def _slice_long_paragraph(paragraph: str, *, max_chunk_chars: int) -> list[str]:
    words = paragraph.split()
    if not words:
        return []
    output: list[str] = []
    current: list[str] = []
    for word in words:
        tentative = " ".join(current + [word]).strip()
        if len(tentative) <= max_chunk_chars:
            current.append(word)
            continue
        if current:
            output.append(" ".join(current).strip())
        current = [word]
    if current:
        output.append(" ".join(current).strip())
    return output


def _lexical_overlap_score(query_tokens: set[str], chunk_text: str) -> float:
    chunk_tokens = _tokenize(chunk_text)
    if not chunk_tokens:
        return 0.0
    overlap = len(query_tokens & chunk_tokens)
    if overlap == 0:
        return 0.0
    base = overlap / math.sqrt(len(query_tokens) * len(chunk_tokens))
    return min(base, 1.0)


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9_:-]+", text.lower())
    return {word for word in words if len(word) > 1}


def _matches_metadata_filters(
    *,
    chunk: KnowledgeChunk,
    service: str | None,
    severity: str | None,
    time_start: str | None,
    time_end: str | None,
) -> bool:
    metadata = chunk.metadata
    if service is not None:
        chunk_service = metadata.get("service", "").lower().strip()
        if not chunk_service or chunk_service != service.lower().strip():
            return False
    if severity is not None:
        chunk_severity = metadata.get("severity", "").upper().strip()
        if not chunk_severity or chunk_severity != severity.upper().strip():
            return False
    if time_start is not None or time_end is not None:
        event_time = metadata.get("event_time")
        if not event_time:
            return False
        parsed_event = _parse_iso_utc(event_time)
        if parsed_event is None:
            return False
        if time_start is not None:
            parsed_start = _parse_iso_utc(time_start)
            if parsed_start is not None and parsed_event < parsed_start:
                return False
        if time_end is not None:
            parsed_end = _parse_iso_utc(time_end)
            if parsed_end is not None and parsed_event > parsed_end:
                return False
    return True


def _confidence_and_fallback(
    hits: list[RetrievalHit],
) -> tuple[ConfidenceLevel, bool, str | None]:
    if not hits:
        return "low", True, "No relevant incident or runbook evidence found."

    top_score = hits[0].score
    if top_score >= 0.5:
        return "high", False, None
    if top_score >= 0.22:
        return "medium", False, None
    return "low", True, "Retrieved evidence is weak; trigger deterministic fallback."


def _parse_iso_utc(value: str) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _company_sim_root(explicit_root: Path | None) -> Path:
    if explicit_root is not None:
        return explicit_root.expanduser().resolve()

    configured = os.getenv("ORCHESTRATOR_COMPANY_SIM_ROOT")
    if configured:
        configured_path = Path(configured).expanduser().resolve()
        if configured_path.exists():
            return configured_path
    return Path(__file__).resolve().parents[3] / "company_details" / "company_sim"


def _infer_service(ticket: dict[str, object]) -> str:
    labels = ticket.get("labels", [])
    label_values = [str(value).lower() for value in labels] if isinstance(labels, list) else []
    combined = " ".join(
        [
            str(ticket.get("summary", "")).lower(),
            str(ticket.get("description", "")).lower(),
            " ".join(label_values),
        ]
    )
    if "webhook" in combined:
        return "webhook-worker"
    if "api" in combined or "gateway" in combined:
        return "saas-api"
    return "unknown"
