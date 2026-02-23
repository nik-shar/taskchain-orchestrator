from __future__ import annotations

import argparse
from pathlib import Path

from orchestrator_api.app.rag_sqlite import build_rag_sqlite_index


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a SQLite FTS index for local RAG over a JSONL corpus."
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("data/rag_corpus_subset_v1.jsonl"),
        help="Input JSONL corpus path.",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("data/rag_index.sqlite"),
        help="Output SQLite index path.",
    )
    parser.add_argument(
        "--chunk-chars",
        type=int,
        default=900,
        help="Maximum characters per chunk.",
    )
    parser.add_argument(
        "--overlap-chars",
        type=int,
        default=120,
        help="Chunk overlap characters.",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Append/replace rows without dropping existing tables.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    stats = build_rag_sqlite_index(
        corpus_jsonl_path=args.corpus,
        index_db_path=args.index,
        chunk_chars=args.chunk_chars,
        overlap_chars=args.overlap_chars,
        reset=not args.no_reset,
    )
    print(f"Index built at: {stats.index_path}")
    print(f"Corpus read: {stats.corpus_path}")
    print(f"Documents read: {stats.documents_read}")
    print(f"Chunks indexed: {stats.chunks_indexed}")
    print("Source counts:")
    for source, count in stats.source_counts.items():
        print(f"  - {source}: {count}")


if __name__ == "__main__":
    main()
