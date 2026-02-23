"""Chroma-backed vector retrieval for previous issue search."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from agent_orchestrator.retrieval.shared_paths import chroma_collection_name, chroma_persist_path


@dataclass(frozen=True)
class VectorIssueHit:
    ticket: str
    summary: str
    relevance: float
    chunk_id: str = ""
    doc_id: str = ""
    source: str = "chroma"


def query_chroma_previous_issues(
    query: str,
    *,
    limit: int,
    service: str | None,
    severity: str | None,
) -> list[VectorIssueHit]:
    persist_path = chroma_persist_path()
    if not persist_path.exists():
        return []

    try:
        import chromadb
    except ImportError:
        return []

    try:
        client = chromadb.PersistentClient(path=str(persist_path))
        collection = client.get_collection(name=chroma_collection_name())
    except Exception:
        return []

    n_results = max(limit, 1)
    where = _where_filter(service=service, severity=severity)
    query_kwargs: dict[str, Any] = {
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        query_kwargs["where"] = where

    api_key = _resolved_openai_api_key()
    try:
        if api_key:
            query_kwargs["query_embeddings"] = [_openai_embed_query(query)]
        else:
            query_kwargs["query_texts"] = [query]
        raw = collection.query(**query_kwargs)
    except Exception:
        return []

    ids = _first_list(raw.get("ids"))
    docs = _first_list(raw.get("documents"))
    metadatas = _first_list(raw.get("metadatas"))
    distances = _first_list(raw.get("distances"))

    hits: list[VectorIssueHit] = []
    for idx, item_id in enumerate(ids):
        metadata_raw = metadatas[idx] if idx < len(metadatas) else {}
        metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
        doc_id = str(metadata.get("doc_id") or item_id or "")
        ticket = str(metadata.get("issue_key") or _ticket_from_doc_id(doc_id))
        if not ticket:
            continue

        document = str(docs[idx] if idx < len(docs) else "")
        if not document:
            continue

        distance = _safe_float(distances[idx] if idx < len(distances) else 1.0, default=1.0)
        hits.append(
            VectorIssueHit(
                ticket=ticket,
                summary=_compact(document, max_chars=220),
                relevance=_distance_to_relevance(distance),
                chunk_id=str(metadata.get("chunk_id") or item_id or ""),
                doc_id=doc_id,
                source=str(metadata.get("source") or "chroma"),
            )
        )

    return _dedupe_ticket_hits(hits)


def _openai_embed_query(text: str) -> list[float]:
    api_key = _resolved_openai_api_key()
    if not api_key:
        raise RuntimeError("OpenAI API key is missing for embedding query.")

    model = (
        os.getenv("AGENT_ORCHESTRATOR_EMBEDDING_MODEL")
        or os.getenv("ORCHESTRATOR_EMBEDDING_MODEL")
        or "text-embedding-3-small"
    )
    base_url = (
        os.getenv("AGENT_ORCHESTRATOR_EMBEDDING_BASE_URL")
        or os.getenv("ORCHESTRATOR_EMBEDDING_BASE_URL")
        or os.getenv("AGENT_ORCHESTRATOR_LLM_BASE_URL")
        or os.getenv("ORCHESTRATOR_LLM_BASE_URL")
        or "https://api.openai.com/v1"
    ).rstrip("/")

    req = request.Request(
        url=f"{base_url}/embeddings",
        method="POST",
        data=json.dumps({"model": model, "input": text}, ensure_ascii=True).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    timeout_s = _safe_float(
        os.getenv("AGENT_ORCHESTRATOR_EMBEDDING_TIMEOUT_S") or "12.0",
        default=12.0,
    )
    try:
        with request.urlopen(req, timeout=max(timeout_s, 1.0)) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Embedding request failed with status {exc.code}: {raw[:300]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Embedding request failed: {exc.reason}") from exc

    data = payload.get("data", [])
    if not isinstance(data, list) or not data:
        raise RuntimeError("Embedding response missing data.")
    embedding = data[0].get("embedding")
    if not isinstance(embedding, list):
        raise RuntimeError("Embedding response missing vector.")
    return [float(value) for value in embedding]


def _resolved_openai_api_key() -> str:
    return (
        os.getenv("AGENT_ORCHESTRATOR_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    ).strip()


def _where_filter(*, service: str | None, severity: str | None) -> dict[str, Any] | None:
    where: dict[str, Any] = {}
    if service and service.strip():
        where["project_lc"] = service.strip().lower()
    if severity and severity.strip():
        where["priority_lc"] = severity.strip().lower()
    return where or None


def _first_list(value: Any) -> list[Any]:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, list):
            return first
    return []


def _safe_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _distance_to_relevance(distance: float) -> float:
    # Chroma returns lower-is-better distance values.
    return round(1.0 / (1.0 + max(distance, 0.0)), 4)


def _ticket_from_doc_id(doc_id: str) -> str:
    if ":" in doc_id:
        return doc_id.rsplit(":", 1)[-1]
    return doc_id


def _compact(text: str, *, max_chars: int) -> str:
    compacted = " ".join(text.split()).strip()
    if len(compacted) <= max_chars:
        return compacted
    return compacted[: max_chars - 3].rstrip() + "..."


def _dedupe_ticket_hits(hits: list[VectorIssueHit]) -> list[VectorIssueHit]:
    seen: set[str] = set()
    output: list[VectorIssueHit] = []
    for hit in hits:
        key = hit.ticket.strip().upper()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(hit)
    return output
