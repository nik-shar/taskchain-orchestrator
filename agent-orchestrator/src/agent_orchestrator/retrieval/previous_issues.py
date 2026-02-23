"""Hybrid retrieval for previous issues: SQLite FTS + optional Chroma vectors."""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from agent_orchestrator.retrieval.chroma_previous_issues import (
    query_chroma_previous_issues,
)
from agent_orchestrator.retrieval.shared_paths import rag_index_path


@dataclass(frozen=True)
class PreviousIssueHit:
    ticket: str
    summary: str
    relevance: float
    chunk_id: str = ""
    doc_id: str = ""
    source: str = ""
    score: float = 0.0
    retrieval_mode: str = ""
    why_selected: str = ""


def search_previous_issues(
    query: str,
    *,
    limit: int = 3,
    service: str | None = None,
    severity: str | None = None,
    index_path: str | None = None,
    use_llm_rerank: bool | None = None,
    use_hybrid: bool | None = None,
) -> list[PreviousIssueHit]:
    normalized_limit = max(limit, 1)
    candidate_limit = max(normalized_limit * 3, normalized_limit)

    lexical_hits: list[PreviousIssueHit] = []
    db_path = rag_index_path(index_path)
    if db_path.exists():
        try:
            lexical_hits = _search_with_relaxation(
                db_path=db_path,
                query=query,
                limit=candidate_limit,
                service=service,
                severity=severity,
            )
        except Exception:
            lexical_hits = []

    vector_hits: list[PreviousIssueHit] = []
    if _hybrid_enabled(use_hybrid):
        vector_hits = _search_chroma_vector_hits(
            query=query,
            limit=candidate_limit,
            service=service,
            severity=severity,
        )

    hits = _fuse_hybrid_hits(lexical_hits=lexical_hits, vector_hits=vector_hits)
    if not hits:
        hits = lexical_hits if lexical_hits else vector_hits

    if use_llm_rerank:
        # Keep deterministic rerank semantics while allowing hybrid candidate pooling.
        hits = _deterministic_rerank(query, hits)

    deduped = _dedupe_hits(hits)
    return deduped[:normalized_limit]


def _search_with_relaxation(
    *,
    db_path: Path,
    query: str,
    limit: int,
    service: str | None,
    severity: str | None,
) -> list[PreviousIssueHit]:
    attempts = [
        {"service": service, "severity": severity},
        {"service": service, "severity": None},
        {"service": None, "severity": None},
    ]

    for filters in attempts:
        hits = _search_once(
            db_path=db_path,
            query=query,
            limit=limit,
            service=filters["service"],
            severity=filters["severity"],
            relaxed_query=False,
        )
        if not hits:
            hits = _search_once(
                db_path=db_path,
                query=query,
                limit=limit,
                service=filters["service"],
                severity=filters["severity"],
                relaxed_query=True,
            )
        if hits:
            return _dedupe_hits(hits)
    return []


def _search_once(
    *,
    db_path: Path,
    query: str,
    limit: int,
    service: str | None,
    severity: str | None,
    relaxed_query: bool,
) -> list[PreviousIssueHit]:
    fts_query = _build_fts_query(query, relaxed=relaxed_query)
    if not fts_query:
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        where_clauses = ["chunks_fts MATCH ?"]
        params: list[Any] = [fts_query]

        where_clauses.append("c.source IN ('jira', 'incident_event_log')")

        if service:
            where_clauses.append("(LOWER(c.project) = LOWER(?) OR LOWER(c.text) LIKE ?)")
            params.extend([service, f"%{service.lower()}%"])
        if severity:
            where_clauses.append("(LOWER(c.priority) = LOWER(?) OR LOWER(c.text) LIKE ?)")
            params.extend([severity, f"%{severity.lower()}%"])

        sql = f"""
            SELECT
                c.chunk_id,
                c.doc_id,
                c.text,
                c.source,
                bm25(chunks_fts) AS bm25_score,
                snippet(chunks_fts, 1, '[', ']', ' ... ', 18) AS snippet
            FROM chunks_fts
            JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
            WHERE {' AND '.join(where_clauses)}
            ORDER BY bm25_score ASC
            LIMIT ?
        """
        params.append(max(limit, 1))
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    output: list[PreviousIssueHit] = []
    query_tokens = _tokenize(query)
    for row in rows:
        doc_id = str(row["doc_id"])
        ticket = _ticket_from_doc_id(doc_id)
        text = str(row["text"])
        snippet = str(row["snippet"] or text)
        relevance = _bm25_to_relevance(float(row["bm25_score"]))
        why_selected = _build_lexical_why_selected(
            query_tokens=query_tokens,
            text=text,
            relaxed_query=relaxed_query,
        )
        output.append(
            PreviousIssueHit(
                ticket=ticket,
                summary=_compact(snippet, max_chars=220),
                relevance=relevance,
                chunk_id=str(row["chunk_id"]),
                doc_id=doc_id,
                source=str(row["source"]),
                score=relevance,
                retrieval_mode="lexical",
                why_selected=why_selected,
            )
        )
    return output


def _search_chroma_vector_hits(
    *,
    query: str,
    limit: int,
    service: str | None,
    severity: str | None,
) -> list[PreviousIssueHit]:
    try:
        raw_hits = query_chroma_previous_issues(
            query=query,
            limit=limit,
            service=service,
            severity=severity,
        )
    except Exception:
        return []

    return [
        PreviousIssueHit(
            ticket=hit.ticket,
            summary=hit.summary,
            relevance=hit.relevance,
            chunk_id=hit.chunk_id,
            doc_id=hit.doc_id,
            source=hit.source,
            score=hit.relevance,
            retrieval_mode="vector",
            why_selected=_build_vector_why_selected(query=query, summary=hit.summary),
        )
        for hit in raw_hits
    ]


def _hybrid_enabled(use_hybrid: bool | None) -> bool:
    if use_hybrid is not None:
        return use_hybrid
    mode = (
        (
            os.getenv("AGENT_ORCHESTRATOR_RAG_RETRIEVAL_MODE")
            or os.getenv("ORCHESTRATOR_RAG_RETRIEVAL_MODE")
            or "hybrid"
        )
        .strip()
        .lower()
    )
    return mode not in {"lexical", "fts", "deterministic"}


def _fuse_hybrid_hits(
    *,
    lexical_hits: list[PreviousIssueHit],
    vector_hits: list[PreviousIssueHit],
) -> list[PreviousIssueHit]:
    if not lexical_hits and not vector_hits:
        return []
    if not lexical_hits:
        return list(vector_hits)
    if not vector_hits:
        return list(lexical_hits)

    # Reciprocal rank fusion (RRF): robustly combine heterogeneous retrievers.
    k = 60.0
    scored: dict[str, dict[str, Any]] = {}

    def add_hit(hit: PreviousIssueHit, rank: int, source_kind: str) -> None:
        key = hit.chunk_id or hit.doc_id or hit.ticket.strip().upper()
        if not key:
            return
        item = scored.get(key)
        if item is None:
            scored[key] = {
                "score": 0.0,
                "hit": hit,
                "lexical_seen": source_kind == "lexical",
                "sources_seen": {source_kind},
            }
            item = scored[key]
        item["score"] += 1.0 / (k + rank + 1.0)
        if hit.relevance > item["hit"].relevance:
            item["hit"] = hit
        if source_kind == "lexical":
            item["lexical_seen"] = True
        item["sources_seen"].add(source_kind)

    for rank, hit in enumerate(lexical_hits):
        add_hit(hit, rank, "lexical")
    for rank, hit in enumerate(vector_hits):
        add_hit(hit, rank, "vector")

    ranked = sorted(
        scored.values(),
        key=lambda item: (
            float(item["score"]),
            1.0 if item.get("lexical_seen", False) else 0.0,
            float(item["hit"].relevance),
        ),
        reverse=True,
    )
    output: list[PreviousIssueHit] = []
    for item in ranked:
        base_hit: PreviousIssueHit = item["hit"]
        sources_seen = item.get("sources_seen", set())
        score = round(float(item["score"]), 4)
        if len(sources_seen) >= 2:
            mode = "hybrid"
            why_selected = "fused lexical and vector candidates via reciprocal-rank fusion."
        else:
            mode = "lexical" if item.get("lexical_seen", False) else "vector"
            why_selected = _append_reason(
                base_hit.why_selected,
                "kept after hybrid candidate fusion.",
            )
        output.append(
            replace(
                base_hit,
                score=score,
                retrieval_mode=mode,
                why_selected=why_selected,
            )
        )
    return output


def _deterministic_rerank(query: str, hits: list[PreviousIssueHit]) -> list[PreviousIssueHit]:
    q_tokens = _tokenize(query)

    def score(hit: PreviousIssueHit) -> tuple[float, float]:
        overlap = len(q_tokens & _tokenize(hit.summary))
        return (float(overlap), hit.relevance)

    reranked = sorted(hits, key=score, reverse=True)
    output: list[PreviousIssueHit] = []
    for hit in reranked:
        overlap = len(q_tokens & _tokenize(hit.summary))
        output.append(
            replace(
                hit,
                why_selected=_append_reason(
                    hit.why_selected,
                    f"reranked by lexical overlap (matched_terms={overlap}).",
                ),
            )
        )
    return output


def _build_fts_query(text: str, *, relaxed: bool) -> str:
    tokens = _ordered_tokens(text)
    if not tokens:
        return ""
    selected = tokens[:8]
    operator = " OR " if relaxed else " AND "
    return operator.join(f"{token}*" for token in selected)


def _tokenize(text: str) -> set[str]:
    return {
        normalized
        for token in re.findall(r"[a-z0-9_:-]+", text.lower())
        for normalized in [_normalize_token(token)]
        if len(normalized) > 1
    }


def _ordered_tokens(text: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for token in re.findall(r"[a-z0-9_:-]+", text.lower()):
        normalized = _normalize_token(token)
        if len(normalized) <= 1 or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _normalize_token(token: str) -> str:
    return token.strip(":-_")


def _ticket_from_doc_id(doc_id: str) -> str:
    if ":" in doc_id:
        return doc_id.rsplit(":", 1)[-1]
    return doc_id


def _bm25_to_relevance(score: float) -> float:
    # bm25() in SQLite FTS5 is lower-is-better; convert to [0,1] relevance.
    normalized = 1.0 / (1.0 + max(score, 0.0))
    return round(normalized, 4)


def _compact(text: str, *, max_chars: int) -> str:
    compacted = " ".join(text.split()).strip()
    if len(compacted) <= max_chars:
        return compacted
    return compacted[: max_chars - 3].rstrip() + "..."


def _dedupe_hits(hits: list[PreviousIssueHit]) -> list[PreviousIssueHit]:
    seen: set[str] = set()
    output: list[PreviousIssueHit] = []
    for hit in hits:
        key = hit.ticket.strip().upper()
        if key in seen:
            continue
        seen.add(key)
        output.append(hit)
    return output


def _build_lexical_why_selected(
    *,
    query_tokens: set[str],
    text: str,
    relaxed_query: bool,
) -> str:
    overlap_terms = sorted(query_tokens & _tokenize(text))
    if overlap_terms:
        terms = ", ".join(overlap_terms[:5])
        mode = "relaxed FTS query" if relaxed_query else "strict FTS query"
        return f"{mode} matched terms: {terms}."
    return "selected by FTS lexical matching."


def _build_vector_why_selected(*, query: str, summary: str) -> str:
    overlap = len(_tokenize(query) & _tokenize(summary))
    return f"selected by vector similarity search (lexical_overlap_hint={overlap})."


def _append_reason(existing: str, suffix: str) -> str:
    base = (existing or "").strip()
    if not base:
        return suffix
    return f"{base} {suffix}"
