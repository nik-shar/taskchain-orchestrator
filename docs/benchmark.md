# Retrieval Benchmark

`make bench` reports what is in the index and how fast retrieval returns, so performance
claims can be reproduced rather than taken on trust.

```bash
# Ingest a repository first, then measure
make bench ARGS="--repo-url https://github.com/tiangolo/fastapi"

# Or reuse an existing index
make bench ARGS="--repo-id tiangolo/fastapi --skip-ingest"

# Add HitRate@k / MRR@k from a JSONL of {"query", "expected_path"}
make bench ARGS="--repo-id tiangolo/fastapi --skip-ingest \
  --eval-file data/retrieval_eval.jsonl --out docs/retrieval_report.md"
```

## Reference run

Measured on this repository at commit `de9894d` (37 indexed files, 5 queries, local SQLite):

| Source | Count |
| --- | ---: |
| Repository files indexed (FTS5 `files_fts`) | 37 |
| Files in the read-only workspace | 37 |
| Documentation files injected | 2 |
| Issues / PRs indexed | 0 -- ingestion needed a `GITHUB_TOKEN` |

| Retriever | P50 (ms) | P95 (ms) | Hits |
| --- | ---: | ---: | ---: |
| Code (FTS5 `files_fts`) | 0.72 | 1.04 | 16 |
| History (FTS5 `issues_fts`) | 0.17 | 0.21 | 0 |

This is a sample, not a benchmark suite: one small repository, five queries. The value is
that `make bench` regenerates it on demand for any repository.

## Ingesting requires a token

Without `GITHUB_TOKEN`, the unauthenticated hourly quota (60 requests) trips
`check_rate_limit`, which fails fast with an actionable error rather than stalling the
pipeline for an hour.
