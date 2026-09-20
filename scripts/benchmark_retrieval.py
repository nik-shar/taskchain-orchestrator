"""Retrieval benchmark: index sizes, search latency, and optional hit-rate.

Produces the numbers quoted in the README and in the resume bullet, so they can be
reproduced rather than asserted:

    # Ingest a repo, then report index stats and search latency
    python scripts/benchmark_retrieval.py --repo-url https://github.com/tiangolo/fastapi

    # Reuse an existing index
    python scripts/benchmark_retrieval.py --repo-id tiangolo/fastapi --skip-ingest

    # Add labelled hit-rate metrics from a JSONL of {"query", "expected_path"}
    python scripts/benchmark_retrieval.py --repo-id tiangolo/fastapi --skip-ingest \
        --eval-file data/retrieval_eval.jsonl --out docs/retrieval_report.md
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from agent.code_tools import CodeReader  # noqa: E402
from ingestion.code_indexer import count_indexed_files, search_code  # noqa: E402
from ingestion.ingestion_pipeline import ingest_repository  # noqa: E402
from ingestion.sqlite_indexer import keyword_search  # noqa: E402
from ingestion.workspace import get_workspace  # noqa: E402
from utils.db import RepoDoc, RepoIngestion, SessionLocal  # noqa: E402

DEFAULT_QUESTIONS = [
    "Where is authentication handled?",
    "How are routes registered?",
    "Where is the database connection configured?",
    "How are tests structured?",
    "Where does the CLI entry point live?",
]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100)[max(0, int(pct) - 1)]


def _repo_stats(repo_id: str) -> dict:
    """Index + workspace sizes for a repo."""
    files_indexed = count_indexed_files(repo_id)

    owner, repo = repo_id.split("/", 1)
    db = SessionLocal()
    try:
        ingestion = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
        docs = db.query(RepoDoc).filter(RepoDoc.repo_id == repo_id).count()
        counts = {
            "issues": ingestion.issue_count if ingestion else 0,
            "prs": ingestion.pr_count if ingestion else 0,
        }
    finally:
        db.close()

    workspace = get_workspace(repo_id)
    workspace_files = len(CodeReader(workspace).list_files()) if workspace else 0

    return {
        "repo_id": repo_id,
        "files_indexed": files_indexed,
        "workspace_files": workspace_files,
        "docs_indexed": docs,
        **counts,
    }


def _measure(repo_id: str, questions: list[str], top_k: int) -> dict:
    """Time code search and issue/PR search for each question."""
    latencies: dict[str, list[float]] = {"code": [], "history": []}
    hits: dict[str, int] = {"code": 0, "history": 0}

    for question in questions:
        start = time.perf_counter()
        code_hits = search_code(repo_id, question, top_k=top_k)
        latencies["code"].append((time.perf_counter() - start) * 1000)

        start = time.perf_counter()
        history_hits = keyword_search(repo_id, question, top_k=top_k)
        latencies["history"].append((time.perf_counter() - start) * 1000)

        hits["code"] += len(code_hits)
        hits["history"] += len(history_hits)

    return {
        "questions": questions,
        "hits": hits,
        "latency_p50_ms": {k: round(_percentile(v, 50), 2) for k, v in latencies.items()},
        "latency_p95_ms": {k: round(_percentile(v, 95), 2) for k, v in latencies.items()},
    }


def _hit_rate(repo_id: str, eval_file: Path, top_k: int) -> dict:
    """HitRate@k / MRR@k for labelled queries (each with an expected file path)."""
    cases = [
        json.loads(line)
        for line in eval_file.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not cases:
        return {}

    hits = 0
    reciprocal_ranks = []
    for case in cases:
        paths = [hit["path"] for hit in search_code(repo_id, case["query"], top_k=top_k)]
        expected = case["expected_path"]
        if expected in paths:
            hits += 1
            reciprocal_ranks.append(1.0 / (paths.index(expected) + 1))
        else:
            reciprocal_ranks.append(0.0)

    return {
        "examples": len(cases),
        "k": top_k,
        "hit_rate": round(hits / len(cases), 4),
        "mrr": round(sum(reciprocal_ranks) / len(cases), 4),
    }


def _render(report: dict) -> str:
    stats = report["stats"]
    lines = [
        "# Retrieval Benchmark",
        "",
        f"- Repository: `{stats['repo_id']}`",
        f"- LLM provider: `{config.LLM_PROVIDER}`",
        "",
        "## Index size",
        "",
        "| Source | Count |",
        "| --- | ---: |",
        f"| Repository files indexed (FTS5) | {stats['files_indexed']} |",
        f"| Files in read-only workspace | {stats['workspace_files']} |",
        f"| Documentation files injected | {stats['docs_indexed']} |",
        f"| Issues indexed | {stats['issues']} |",
        f"| Pull requests indexed | {stats['prs']} |",
        "",
        "## Search latency (ms)",
        "",
        "| Retriever | P50 | P95 | Hits |",
        "| --- | ---: | ---: | ---: |",
        f"| Code (FTS5 `files_fts`) | {report['latency_p50_ms']['code']} "
        f"| {report['latency_p95_ms']['code']} | {report['hits']['code']} |",
        f"| History (FTS5 `issues_fts`) | {report['latency_p50_ms']['history']} "
        f"| {report['latency_p95_ms']['history']} | {report['hits']['history']} |",
        "",
        f"- Queries measured: {len(report['questions'])}",
    ]
    if report.get("hit_rate"):
        rates = report["hit_rate"]
        lines += [
            "",
            "## Hit-rate (labelled queries)",
            "",
            f"- Examples: {rates['examples']}, k: {rates['k']}",
            f"- HitRate@k: {rates['hit_rate']}",
            f"- MRR@k: {rates['mrr']}",
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-url", help="Repository to ingest before benchmarking")
    parser.add_argument("--repo-id", help="owner/repo of an already-ingested repository")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--question", action="append", default=None)
    parser.add_argument("--eval-file", type=Path)
    parser.add_argument("--out", type=Path, help="Write the markdown report here")
    parser.add_argument("--top-k", type=int, default=config.FINAL_TOP_K)
    args = parser.parse_args()

    if not args.repo_url and not args.repo_id:
        parser.error("provide --repo-url (ingest) or --repo-id (reuse existing index)")

    repo_id = args.repo_id
    if args.repo_url and not args.skip_ingest:
        from ingestion.github_indexer import parse_github_url

        owner, repo = parse_github_url(args.repo_url)
        repo_id = f"{owner}/{repo}"
        print(f"Ingested {repo_id}: {ingest_repository(args.repo_url)}")

    if not repo_id:
        parser.error("could not determine repo_id")

    questions = args.question or DEFAULT_QUESTIONS
    report = {"stats": _repo_stats(repo_id)}
    report.update(_measure(repo_id, questions, args.top_k))
    if args.eval_file:
        report["hit_rate"] = _hit_rate(repo_id, args.eval_file, args.top_k)

    markdown = _render(report)
    print(markdown)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown)
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
