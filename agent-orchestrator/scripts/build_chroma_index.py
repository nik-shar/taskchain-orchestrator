from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any
from urllib import error, request


def _parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description=(
            "Build a Chroma vector store from SQLite RAG chunks for hybrid retrieval "
            "(lexical + vector)."
        )
    )
    parser.add_argument(
        "--sqlite-index",
        type=Path,
        default=project_root / "data" / "rag_index.sqlite",
        help="Path to source SQLite index (must contain chunks table).",
    )
    parser.add_argument(
        "--chroma-path",
        type=Path,
        default=project_root / "data" / "rag_chroma",
        help="Persistent Chroma directory.",
    )
    parser.add_argument(
        "--collection",
        default=(
            os.getenv("AGENT_ORCHESTRATOR_CHROMA_COLLECTION")
            or os.getenv("ORCHESTRATOR_CHROMA_COLLECTION")
            or "rag_chunks_v1"
        ),
        help="Chroma collection name.",
    )
    parser.add_argument(
        "--embedding-model",
        default=(
            os.getenv("AGENT_ORCHESTRATOR_EMBEDDING_MODEL")
            or os.getenv("ORCHESTRATOR_EMBEDDING_MODEL")
            or "text-embedding-3-small"
        ),
        help="Embedding model name.",
    )
    parser.add_argument(
        "--embedding-base-url",
        default=(
            os.getenv("AGENT_ORCHESTRATOR_EMBEDDING_BASE_URL")
            or os.getenv("ORCHESTRATOR_EMBEDDING_BASE_URL")
            or os.getenv("AGENT_ORCHESTRATOR_LLM_BASE_URL")
            or os.getenv("ORCHESTRATOR_LLM_BASE_URL")
            or "https://api.openai.com/v1"
        ),
        help="Embeddings API base URL.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=128,
        help="Number of chunks per embedding/upsert batch.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap for number of chunks to index.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate collection before indexing.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    api_key = (
        os.getenv("AGENT_ORCHESTRATOR_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    ).strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY (or AGENT_ORCHESTRATOR_OPENAI_API_KEY) is required.")
    if not args.sqlite_index.exists():
        raise RuntimeError(f"SQLite index not found: {args.sqlite_index}")

    try:
        import chromadb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "chromadb is not installed. Install agent-orchestrator dependencies first."
        ) from exc

    args.chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(args.chroma_path))

    if args.reset:
        try:
            client.delete_collection(name=args.collection)
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=args.collection,
        metadata={"hnsw:space": "cosine"},
    )

    conn = sqlite3.connect(args.sqlite_index)
    conn.row_factory = sqlite3.Row
    try:
        sql = (
            "SELECT chunk_id, doc_id, source, text, project, priority "
            "FROM chunks ORDER BY chunk_id"
        )
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()

    if args.limit is not None and args.limit > 0:
        rows = rows[: args.limit]
    total = len(rows)
    if total == 0:
        print("No rows found in chunks table. Nothing to index.")
        return

    print(
        f"Building Chroma collection '{args.collection}' from {total} chunks "
        f"(batch_size={max(1, args.batch_size)})"
    )

    processed = 0
    batch_size = max(1, args.batch_size)
    for start in range(0, total, batch_size):
        batch = rows[start : start + batch_size]
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for row in batch:
            chunk_id = str(row["chunk_id"])
            doc_id = str(row["doc_id"])
            source = str(row["source"])
            text = str(row["text"])
            project = _as_text(row["project"])
            priority = _as_text(row["priority"])

            ids.append(chunk_id)
            documents.append(text)
            metadatas.append(
                {
                    "chunk_id": chunk_id,
                    "doc_id": doc_id,
                    "source": source,
                    "issue_key": _ticket_from_doc_id(doc_id),
                    "project_lc": project.lower(),
                    "priority_lc": priority.lower(),
                }
            )

        embeddings = _embed_batch_openai(
            texts=documents,
            api_key=api_key,
            model=args.embedding_model,
            base_url=args.embedding_base_url,
        )
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        processed += len(batch)
        print(f"Indexed {processed}/{total} chunks")

    print("Chroma index build complete.")
    print(f"Path: {args.chroma_path}")
    print(f"Collection: {args.collection}")


def _embed_batch_openai(
    *,
    texts: list[str],
    api_key: str,
    model: str,
    base_url: str,
) -> list[list[float]]:
    req = request.Request(
        url=f"{base_url.rstrip('/')}/embeddings",
        method="POST",
        data=json.dumps({"model": model, "input": texts}, ensure_ascii=True).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=30.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Embedding batch failed with status {exc.code}: {raw[:300]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Embedding batch failed: {exc.reason}") from exc

    rows = payload.get("data", [])
    if not isinstance(rows, list) or len(rows) != len(texts):
        raise RuntimeError("Embedding response length mismatch.")
    output: list[list[float]] = []
    for row in rows:
        vector = row.get("embedding")
        if not isinstance(vector, list):
            raise RuntimeError("Embedding response missing vector.")
        output.append([float(value) for value in vector])
    return output


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _ticket_from_doc_id(doc_id: str) -> str:
    if ":" in doc_id:
        return doc_id.rsplit(":", 1)[-1]
    return doc_id


if __name__ == "__main__":
    main()
