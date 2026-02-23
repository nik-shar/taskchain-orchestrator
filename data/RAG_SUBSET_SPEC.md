# RAG Subset Spec (V1)

This spec defines a controlled extraction plan for building an initial RAG corpus from:
- Jira subset (target: 4,000 issues total)
- Incident dataset subset (target: 10,000 deduplicated incidents)

## Spec File

- `data/rag_subset_spec_v1.json`

Key controls:
- Per-source quotas (`target_docs`)
- Issue-type filters per Jira source (`issue_types`)
- Export oversampling (`export_multiplier`) to reduce post-filter shortfalls
- Incident cap (`incident.limit`)

## Run

```bash
source venv/bin/activate
python scripts/prepare_rag_subset.py \
  --spec-file data/rag_subset_spec_v1.json \
  --output data/rag_corpus_subset_v1.jsonl
```

## What The Script Produces

Each line in output is one JSON document:

```json
{"doc_id":"...","source":"jira|incident_event_log","text":"...","metadata":{...}}
```

## Notes

- Requires MongoDB tools for Jira path: `mongorestore` and `mongoexport`.
- For a rerun without restore, use `--skip-restore` once `JiraSubset` DB already exists.
- If a Jira collection under-fills after filters, increase that collection's `export_multiplier` in the spec.
