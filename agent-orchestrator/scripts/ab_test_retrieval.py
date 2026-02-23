from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agent_orchestrator.retrieval.chroma_previous_issues import query_chroma_previous_issues
from agent_orchestrator.retrieval.previous_issues import search_previous_issues

Mode = Literal["lexical", "vector", "hybrid_rerank"]


@dataclass(frozen=True)
class EvalExample:
    query: str
    expected_tickets: list[str]
    service: str | None = None
    severity: str | None = None


@dataclass(frozen=True)
class RetrievedHit:
    ticket: str
    score: float
    summary: str
    source: str


def main() -> None:
    args = _parse_args()
    examples = _load_eval_examples(args.dataset)
    if not examples:
        raise RuntimeError(f"No evaluation examples found in {args.dataset}")

    limit = max(args.limit, args.k)
    requested_modes: list[Mode]
    if args.mode == "all":
        requested_modes = ["lexical", "vector", "hybrid_rerank"]
    else:
        requested_modes = [args.mode]

    report = {
        "dataset": str(args.dataset),
        "k": args.k,
        "limit": limit,
        "examples": len(examples),
        "modes": {},
    }

    for mode in requested_modes:
        report["modes"][mode] = _evaluate_mode(
            examples=examples,
            mode=mode,
            k=args.k,
            limit=limit,
        )

    markdown = _render_markdown(report)
    print(markdown)

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.output_md.write_text(markdown + "\n", encoding="utf-8")
    print(f"\nSaved JSON report: {args.output_json}")
    print(f"Saved Markdown report: {args.output_md}")


def _parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description=(
            "Run retrieval A/B evaluation over a query set for lexical-only, "
            "vector-only, and hybrid+rerank modes."
        )
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=project_root / "data" / "retrieval_eval_queries.sample.jsonl",
        help="JSONL file with fields: query, expected_tickets, optional service, optional severity.",
    )
    parser.add_argument(
        "--mode",
        choices=["all", "lexical", "vector", "hybrid_rerank"],
        default="all",
        help="Which retrieval mode to evaluate.",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=3,
        help="Top-k cutoff for HitRate/Recall/MRR.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=6,
        help="Retriever result count per query (must be >= k).",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=project_root / "data" / "retrieval_ab_report.json",
        help="Path to write JSON report.",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=project_root / "data" / "retrieval_ab_report.md",
        help="Path to write Markdown report.",
    )
    return parser.parse_args()


def _load_eval_examples(path: Path) -> list[EvalExample]:
    if not path.exists():
        raise RuntimeError(
            f"Dataset not found: {path}. Create JSONL rows like: "
            '{"query":"...","expected_tickets":["WLC-43"]}'
        )

    examples: list[EvalExample] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON at {path}:{line_no}") from exc

        query = str(row.get("query", "")).strip()
        if not query:
            continue
        expected_raw = row.get("expected_tickets", [])
        expected = _normalized_ticket_list(expected_raw)
        examples.append(
            EvalExample(
                query=query,
                expected_tickets=expected,
                service=_optional_text(row.get("service")),
                severity=_optional_text(row.get("severity")),
            )
        )
    return examples


def _evaluate_mode(
    *,
    examples: list[EvalExample],
    mode: Mode,
    k: int,
    limit: int,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    hit_count = 0
    recall_sum = 0.0
    mrr_sum = 0.0
    scored_examples = 0
    latencies_ms: list[float] = []

    for example in examples:
        started = time.perf_counter()
        hits = _run_retrieval(example=example, mode=mode, limit=limit)
        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        latencies_ms.append(latency_ms)

        retrieved_topk = [hit.ticket for hit in hits[:k]]
        expected_set = {ticket.upper() for ticket in example.expected_tickets}
        overlap = expected_set.intersection({ticket.upper() for ticket in retrieved_topk})

        recall_at_k = 0.0
        mrr_at_k = 0.0
        hit_at_k = False
        if expected_set:
            scored_examples += 1
            hit_at_k = bool(overlap)
            recall_at_k = len(overlap) / float(len(expected_set))
            mrr_at_k = _mrr_at_k(retrieved_topk, expected_set, k=k)
            hit_count += 1 if hit_at_k else 0
            recall_sum += recall_at_k
            mrr_sum += mrr_at_k

        rows.append(
            {
                "query": example.query,
                "expected_tickets": example.expected_tickets,
                "retrieved_tickets_topk": retrieved_topk,
                "latency_ms": latency_ms,
                "hit_at_k": hit_at_k,
                "recall_at_k": round(recall_at_k, 4),
                "mrr_at_k": round(mrr_at_k, 4),
            }
        )

    denom = max(scored_examples, 1)
    return {
        "examples_total": len(examples),
        "examples_scored": scored_examples,
        "k": k,
        "hit_rate_at_k": round(hit_count / denom, 4),
        "recall_at_k": round(recall_sum / denom, 4),
        "mrr_at_k": round(mrr_sum / denom, 4),
        "latency_ms": {
            "p50": _percentile(latencies_ms, 50.0),
            "p95": _percentile(latencies_ms, 95.0),
            "avg": round(sum(latencies_ms) / max(len(latencies_ms), 1), 2),
        },
        "queries": rows,
    }


def _run_retrieval(*, example: EvalExample, mode: Mode, limit: int) -> list[RetrievedHit]:
    if mode == "lexical":
        hits = search_previous_issues(
            example.query,
            limit=limit,
            service=example.service,
            severity=example.severity,
            use_hybrid=False,
            use_llm_rerank=False,
        )
        return [
            RetrievedHit(
                ticket=hit.ticket,
                score=float(hit.score or hit.relevance),
                summary=hit.summary,
                source=hit.source or "lexical",
            )
            for hit in hits
        ]

    if mode == "vector":
        hits = query_chroma_previous_issues(
            query=example.query,
            limit=limit,
            service=example.service,
            severity=example.severity,
        )
        return [
            RetrievedHit(
                ticket=hit.ticket,
                score=float(hit.relevance),
                summary=hit.summary,
                source=hit.source,
            )
            for hit in hits
        ]

    hits = search_previous_issues(
        example.query,
        limit=limit,
        service=example.service,
        severity=example.severity,
        use_hybrid=True,
        use_llm_rerank=True,
    )
    return [
        RetrievedHit(
            ticket=hit.ticket,
            score=float(hit.score or hit.relevance),
            summary=hit.summary,
            source=hit.source or "hybrid",
        )
        for hit in hits
    ]


def _render_markdown(report: dict[str, object]) -> str:
    dataset = report.get("dataset", "unknown")
    examples = report.get("examples", 0)
    k = report.get("k", 0)
    lines = [
        "# Retrieval A/B Report",
        "",
        f"- Dataset: `{dataset}`",
        f"- Examples: `{examples}`",
        f"- k: `{k}`",
        "",
        "| Mode | HitRate@k | Recall@k | MRR@k | P50 Latency (ms) | P95 Latency (ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    modes = report.get("modes", {})
    if isinstance(modes, dict):
        for mode_name, payload in modes.items():
            if not isinstance(payload, dict):
                continue
            latency = payload.get("latency_ms", {})
            p50 = latency.get("p50", 0.0) if isinstance(latency, dict) else 0.0
            p95 = latency.get("p95", 0.0) if isinstance(latency, dict) else 0.0
            lines.append(
                "| {mode} | {hit:.4f} | {recall:.4f} | {mrr:.4f} | {p50:.2f} | {p95:.2f} |".format(
                    mode=mode_name,
                    hit=float(payload.get("hit_rate_at_k", 0.0)),
                    recall=float(payload.get("recall_at_k", 0.0)),
                    mrr=float(payload.get("mrr_at_k", 0.0)),
                    p50=float(p50),
                    p95=float(p95),
                )
            )
    return "\n".join(lines)


def _mrr_at_k(retrieved: list[str], expected: set[str], *, k: int) -> float:
    for rank, ticket in enumerate(retrieved[:k], start=1):
        if ticket.upper() in expected:
            return 1.0 / float(rank)
    return 0.0


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return round(sorted_values[0], 2)
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return round(sorted_values[int(rank)], 2)
    weight = rank - lower
    interpolated = sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight
    return round(interpolated, 2)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalized_ticket_list(value: object) -> list[str]:
    if isinstance(value, list):
        candidates = value
    elif isinstance(value, str):
        candidates = [part.strip() for part in value.split(",")]
    else:
        candidates = []
    output: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        ticket = str(item).strip().upper()
        if not ticket or ticket in seen:
            continue
        seen.add(ticket)
        output.append(ticket)
    return output


if __name__ == "__main__":
    main()
