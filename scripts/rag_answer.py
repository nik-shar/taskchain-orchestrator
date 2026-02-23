from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import BaseModel, Field

from orchestrator_api.app.llm import build_llm_adapter_from_env
from orchestrator_api.app.rag_sqlite import search_rag_index, summarize_rag_hits


class GroundedAnswer(BaseModel):
    answer: str = Field(min_length=1)
    key_points: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Answer a question using local RAG retrieval and optional LLM synthesis."
    )
    parser.add_argument("--index", type=Path, default=Path("data/rag_index.sqlite"))
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--source", default=None)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--issue-type", default=None)
    parser.add_argument("--priority", default=None)
    parser.add_argument("--project", default=None)
    parser.add_argument("--incident-state", default=None)
    parser.add_argument(
        "--llm-timeout-s",
        type=float,
        default=25.0,
        help="Timeout for optional LLM answer generation.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = search_rag_index(
        index_db_path=args.index,
        query=args.query,
        top_k=args.top_k,
        source=args.source,
        collection=args.collection,
        issue_type=args.issue_type,
        priority=args.priority,
        project=args.project,
        incident_state=args.incident_state,
    )

    if not result.hits:
        print("No evidence retrieved. Try a broader query or fewer filters.")
        return

    evidence_lines = []
    for hit in result.hits:
        payload = {
            "doc_id": hit.doc_id,
            "source": hit.source,
            "metadata": hit.metadata,
            "snippet": hit.snippet or hit.text[:320],
        }
        evidence_lines.append(json.dumps(payload, ensure_ascii=True))

    adapter = build_llm_adapter_from_env()
    if adapter is None:
        print("LLM adapter not configured; returning deterministic grounded summary.")
        print("")
        print(summarize_rag_hits(query=args.query, hits=result.hits, max_points=min(5, args.top_k)))
        return

    system_prompt = (
        "You are a grounded assistant. Use only the provided evidence. "
        "Do not invent facts. Include citations as doc_id values."
    )
    user_prompt = (
        f"Question: {args.query}\n\n"
        "Evidence JSON lines:\n"
        + "\n".join(evidence_lines)
        + "\n\n"
        "Return JSON with fields: answer (string), key_points (list of strings), "
        "citations (list of doc_id strings used in the answer)."
    )
    response = adapter.generate_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=GroundedAnswer,
        timeout_s=args.llm_timeout_s,
    )
    print("Answer:")
    print(response.answer)
    if response.key_points:
        print("")
        print("Key points:")
        for item in response.key_points:
            print(f"- {item}")
    if response.citations:
        print("")
        print("Citations:")
        for citation in response.citations:
            print(f"- {citation}")


if __name__ == "__main__":
    main()
