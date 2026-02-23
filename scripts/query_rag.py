from __future__ import annotations

import argparse
import json
from pathlib import Path

from orchestrator_api.app.rag_sqlite import search_rag_index, summarize_rag_hits


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query the local SQLite RAG index.")
    parser.add_argument("--index", type=Path, default=Path("data/rag_index.sqlite"))
    parser.add_argument("--query", required=True, help="Natural language query.")
    parser.add_argument("--top-k", type=int, default=8, help="Number of hits to return.")
    parser.add_argument(
        "--source",
        default=None,
        help="Filter by source (jira or incident_event_log).",
    )
    parser.add_argument("--collection", default=None, help="Filter Jira collection.")
    parser.add_argument("--issue-type", default=None, help="Filter Jira issue type.")
    parser.add_argument("--priority", default=None, help="Filter priority.")
    parser.add_argument("--project", default=None, help="Filter Jira project key.")
    parser.add_argument("--incident-state", default=None, help="Filter incident state.")
    parser.add_argument("--created-from", default=None, help="Filter Jira created >= datetime.")
    parser.add_argument("--created-to", default=None, help="Filter Jira created <= datetime.")
    parser.add_argument(
        "--opened-from",
        default=None,
        help="Filter incident opened_at >= datetime.",
    )
    parser.add_argument("--opened-to", default=None, help="Filter incident opened_at <= datetime.")
    parser.add_argument(
        "--show-text-chars",
        type=int,
        default=260,
        help="Maximum chars of raw text shown per hit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output instead of human-readable output.",
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
        created_from=args.created_from,
        created_to=args.created_to,
        opened_from=args.opened_from,
        opened_to=args.opened_to,
    )

    if args.json:
        payload = {
            "query": result.query,
            "applied_filters": result.applied_filters,
            "total_hits": len(result.hits),
            "hits": [
                {
                    "chunk_id": hit.chunk_id,
                    "doc_id": hit.doc_id,
                    "source": hit.source,
                    "bm25_score": hit.bm25_score,
                    "snippet": hit.snippet,
                    "metadata": hit.metadata,
                }
                for hit in result.hits
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=True))
        return

    print(summarize_rag_hits(query=result.query, hits=result.hits, max_points=min(5, args.top_k)))
    print("")
    print(f"Total hits: {len(result.hits)}")
    if result.applied_filters:
        print("Applied filters:")
        for key, value in result.applied_filters.items():
            print(f"  - {key}: {value}")
    print("")
    for index, hit in enumerate(result.hits, start=1):
        snippet = " ".join((hit.snippet or "").split())
        raw_text = " ".join(hit.text.split())[: max(args.show_text_chars, 80)]
        print(
            f"{index}. {hit.doc_id} | source={hit.source} | bm25={hit.bm25_score:.4f} | "
            f"metadata={hit.metadata}"
        )
        print(f"   snippet: {snippet}")
        print(f"   text: {raw_text}")


if __name__ == "__main__":
    main()
