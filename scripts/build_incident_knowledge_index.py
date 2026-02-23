from __future__ import annotations

import argparse
import json
from pathlib import Path

from orchestrator_api.app.retrieval import build_incident_corpus, corpus_to_json_serializable


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a deterministic local incident knowledge index "
            "from company simulation data."
        )
    )
    parser.add_argument(
        "--company-sim-root",
        type=Path,
        default=None,
        help=(
            "Path to company_sim root. Defaults to ORCHESTRATOR_COMPANY_SIM_ROOT "
            "or repository company_details/company_sim."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/incident_knowledge_index.json"),
        help="Output JSON file path (default: data/incident_knowledge_index.json).",
    )
    parser.add_argument(
        "--max-chunk-chars",
        type=int,
        default=700,
        help="Maximum characters per document chunk (default: 700).",
    )
    parser.add_argument(
        "--overlap-chars",
        type=int,
        default=120,
        help="Chunk overlap in characters (default: 120).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    corpus = build_incident_corpus(
        company_sim_root=args.company_sim_root,
        max_chunk_chars=args.max_chunk_chars,
        overlap_chars=args.overlap_chars,
    )
    output_payload = {
        "chunks": corpus_to_json_serializable(corpus),
        "count": len(corpus),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output_payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(corpus)} knowledge chunks to {args.output}")


if __name__ == "__main__":
    main()
