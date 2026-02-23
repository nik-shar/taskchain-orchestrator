from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RagBuildStats:
    corpus_path: str
    index_path: str
    documents_read: int
    chunks_indexed: int
    source_counts: dict[str, int]


@dataclass(frozen=True)
class RagSearchHit:
    chunk_id: str
    doc_id: str
    source: str
    bm25_score: float
    snippet: str
    text: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class RagSearchResult:
    query: str
    applied_filters: dict[str, str]
    hits: list[RagSearchHit]


def build_rag_sqlite_index(
    *,
    corpus_jsonl_path: Path,
    index_db_path: Path,
    chunk_chars: int = 900,
    overlap_chars: int = 120,
    reset: bool = True,
) -> RagBuildStats:
    corpus_path = corpus_jsonl_path.expanduser().resolve()
    index_path = index_db_path.expanduser().resolve()
    index_path.parent.mkdir(parents=True, exist_ok=True)

    if not corpus_path.exists():
        raise RuntimeError(f"Corpus file not found: {corpus_path}")

    conn = sqlite3.connect(index_path)
    try:
        _prepare_database(conn, reset=reset)
        documents_read = 0
        chunks_indexed = 0
        source_counts: Counter[str] = Counter()
        with corpus_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                raw = json.loads(line)
                doc_id = str(raw.get("doc_id", "")).strip()
                source = str(raw.get("source", "")).strip()
                text = str(raw.get("text", "")).strip()
                metadata = _normalize_metadata(raw.get("metadata", {}))
                if not doc_id or not source or not text:
                    continue

                documents_read += 1
                source_counts[source] += 1

                for chunk_index, chunk_text in enumerate(
                    _chunk_text(text=text, max_chunk_chars=chunk_chars, overlap_chars=overlap_chars)
                ):
                    chunk_id = f"{doc_id}#c{chunk_index}"
                    _insert_chunk(
                        conn=conn,
                        chunk_id=chunk_id,
                        doc_id=doc_id,
                        source=source,
                        text=chunk_text,
                        metadata=metadata,
                    )
                    chunks_indexed += 1
        conn.commit()
    finally:
        conn.close()

    return RagBuildStats(
        corpus_path=str(corpus_path),
        index_path=str(index_path),
        documents_read=documents_read,
        chunks_indexed=chunks_indexed,
        source_counts=dict(sorted(source_counts.items())),
    )


def search_rag_index(
    *,
    index_db_path: Path,
    query: str,
    top_k: int = 8,
    source: str | None = None,
    collection: str | None = None,
    issue_type: str | None = None,
    priority: str | None = None,
    project: str | None = None,
    incident_state: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    opened_from: str | None = None,
    opened_to: str | None = None,
) -> RagSearchResult:
    query_text = query.strip()
    if not query_text:
        raise RuntimeError("Query must be non-empty.")

    fts_query = _build_fts_query(query_text)
    if not fts_query:
        raise RuntimeError("Query does not contain searchable tokens.")

    index_path = index_db_path.expanduser().resolve()
    if not index_path.exists():
        raise RuntimeError(f"Index DB not found: {index_path}")

    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row
    try:
        where_clauses = ["chunks_fts MATCH ?"]
        params: list[Any] = [fts_query]
        applied_filters: dict[str, str] = {}

        if source:
            where_clauses.append("c.source = ?")
            params.append(source.strip())
            applied_filters["source"] = source.strip()
        if collection:
            where_clauses.append("c.collection = ?")
            params.append(collection.strip())
            applied_filters["collection"] = collection.strip()
        if issue_type:
            where_clauses.append("c.issue_type = ?")
            params.append(issue_type.strip())
            applied_filters["issue_type"] = issue_type.strip()
        if priority:
            where_clauses.append("c.priority = ?")
            params.append(priority.strip())
            applied_filters["priority"] = priority.strip()
        if project:
            where_clauses.append("c.project = ?")
            params.append(project.strip())
            applied_filters["project"] = project.strip()
        if incident_state:
            where_clauses.append("c.incident_state = ?")
            params.append(incident_state.strip())
            applied_filters["incident_state"] = incident_state.strip()

        created_from_iso = _parse_datetime_to_utc_iso(created_from)
        created_to_iso = _parse_datetime_to_utc_iso(created_to)
        opened_from_iso = _parse_datetime_to_utc_iso(opened_from)
        opened_to_iso = _parse_datetime_to_utc_iso(opened_to)
        if created_from_iso:
            where_clauses.append("c.created_at_iso >= ?")
            params.append(created_from_iso)
            applied_filters["created_from"] = created_from
        if created_to_iso:
            where_clauses.append("c.created_at_iso <= ?")
            params.append(created_to_iso)
            applied_filters["created_to"] = created_to
        if opened_from_iso:
            where_clauses.append("c.opened_at_iso >= ?")
            params.append(opened_from_iso)
            applied_filters["opened_from"] = opened_from
        if opened_to_iso:
            where_clauses.append("c.opened_at_iso <= ?")
            params.append(opened_to_iso)
            applied_filters["opened_to"] = opened_to

        sql = f"""
            SELECT
                c.chunk_id,
                c.doc_id,
                c.source,
                c.text,
                c.metadata_json,
                bm25(chunks_fts) AS bm25_score,
                snippet(chunks_fts, 1, '[', ']', ' ... ', 22) AS snippet
            FROM chunks_fts
            JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
            WHERE {' AND '.join(where_clauses)}
            ORDER BY bm25_score ASC
            LIMIT ?
        """
        params.append(max(top_k, 1))
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    hits = [
        RagSearchHit(
            chunk_id=str(row["chunk_id"]),
            doc_id=str(row["doc_id"]),
            source=str(row["source"]),
            bm25_score=float(row["bm25_score"]),
            snippet=str(row["snippet"] or ""),
            text=str(row["text"]),
            metadata=_load_metadata_json(str(row["metadata_json"])),
        )
        for row in rows
    ]
    return RagSearchResult(query=query_text, applied_filters=applied_filters, hits=hits)


def summarize_rag_hits(
    *,
    query: str,
    hits: list[RagSearchHit],
    max_points: int = 5,
) -> str:
    if not hits:
        return "No evidence retrieved. Try a broader query or fewer filters."

    limited = hits[: max(max_points, 1)]
    source_counts = Counter(hit.source for hit in limited)
    lines = [
        f"Question: {query}",
        "Answer (grounded in retrieved evidence):",
    ]
    for idx, hit in enumerate(limited, start=1):
        preview = hit.snippet.strip() or hit.text[:220].strip()
        preview = _normalize_whitespace(preview)
        citation = hit.doc_id
        lines.append(f"{idx}. {preview} [{citation}]")
    lines.append("Evidence mix: " + ", ".join(f"{k}={v}" for k, v in sorted(source_counts.items())))
    lines.append("Citations: " + ", ".join(hit.doc_id for hit in limited))
    return "\n".join(lines)


def _prepare_database(conn: sqlite3.Connection, *, reset: bool) -> None:
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    if reset:
        conn.execute("DROP TABLE IF EXISTS chunks;")
        conn.execute("DROP TABLE IF EXISTS chunks_fts;")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            source TEXT NOT NULL,
            text TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            collection TEXT,
            issue_type TEXT,
            priority TEXT,
            status TEXT,
            project TEXT,
            incident_state TEXT,
            created_at_iso TEXT,
            opened_at_iso TEXT
        );
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
        USING fts5(chunk_id UNINDEXED, text);
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_collection ON chunks(collection);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_issue_type ON chunks(issue_type);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_priority ON chunks(priority);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_project ON chunks(project);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_state ON chunks(incident_state);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_created ON chunks(created_at_iso);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_opened ON chunks(opened_at_iso);")
    conn.commit()


def _insert_chunk(
    *,
    conn: sqlite3.Connection,
    chunk_id: str,
    doc_id: str,
    source: str,
    text: str,
    metadata: dict[str, str],
) -> None:
    metadata_json = json.dumps(metadata, ensure_ascii=True, sort_keys=True)
    created_at_iso = _parse_datetime_to_utc_iso(metadata.get("created"))
    opened_at_iso = _parse_datetime_to_utc_iso(metadata.get("opened_at"))
    conn.execute(
        """
        INSERT OR REPLACE INTO chunks (
            chunk_id, doc_id, source, text, metadata_json, collection, issue_type,
            priority, status, project, incident_state, created_at_iso, opened_at_iso
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chunk_id,
            doc_id,
            source,
            text,
            metadata_json,
            metadata.get("collection"),
            metadata.get("issue_type"),
            metadata.get("priority"),
            metadata.get("status"),
            metadata.get("project"),
            metadata.get("state"),
            created_at_iso,
            opened_at_iso,
        ),
    )
    conn.execute(
        "INSERT OR REPLACE INTO chunks_fts (chunk_id, text) VALUES (?, ?)",
        (chunk_id, text),
    )


def _normalize_metadata(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        key_text = str(key).strip()
        if not key_text:
            continue
        normalized[key_text] = _stringify(value)
    return normalized


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value).strip()


def _load_metadata_json(raw: str) -> dict[str, str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    output: dict[str, str] = {}
    for key, value in parsed.items():
        output[str(key)] = _stringify(value)
    return output


def _build_fts_query(query: str) -> str:
    tokens = _tokenize(query)
    if not tokens:
        return ""
    return " OR ".join(f'"{token}"' for token in tokens)


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9_:-]+", text.lower())
    unique = []
    seen: set[str] = set()
    for word in words:
        if len(word) <= 1:
            continue
        if word in seen:
            continue
        seen.add(word)
        unique.append(word)
    return unique


def _parse_datetime_to_utc_iso(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None

    # incident format: 1/1/2017 01:14
    try:
        incident_dt = datetime.strptime(value, "%d/%m/%Y %H:%M")
        return incident_dt.replace(tzinfo=UTC).isoformat()
    except ValueError:
        pass

    normalized = value
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        iso_dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if iso_dt.tzinfo is None:
        iso_dt = iso_dt.replace(tzinfo=UTC)
    return iso_dt.astimezone(UTC).isoformat()


def _chunk_text(*, text: str, max_chunk_chars: int, overlap_chars: int) -> list[str]:
    cleaned = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if not cleaned:
        return []

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    chunks: list[str] = []
    current = ""
    max_chars = max(200, max_chunk_chars)
    overlap = max(0, min(overlap_chars, max_chars // 2))

    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current.strip())
            tail = current[-overlap:] if overlap > 0 else ""
            current = f"{tail}\n\n{paragraph}".strip()
        else:
            chunks.extend(_slice_long_paragraph(paragraph, max_chunk_chars=max_chars))
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


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())
