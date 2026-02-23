# Company Details Dataset Guide

This guide explains what to read, how to explore safely, and how to decide the Jira subset for RAG on a constrained machine (8 GB RAM).

## 1. What Is In `company_details/`

- `2025-06-23 ThePublicJiraDataset/ThePublicJiraDataset`
  - Large public Jira dataset.
  - Main dump file: `3. DataDump/mongodump-JiraReposAnon.archive` (very large).
  - Metadata files: `0. DataDefinition/*.json` (small, explore these first).
- `incident+management+process+enriched+event+log/incident_event_log.csv`
  - Medium CSV event log, practical to analyze locally.

## 2. Exploration Rules (Important)

- Start metadata-first: inspect size, schema, counts.
- Never read full dump/CSV into prompt context.
- Use bounded commands: `head`, `wc`, `jq`, filtered `awk`.
- For Jira dump, restore/export only selected collections.

## 3. Safe Exploration Commands

Run these from repository root (`/home/nik/Desktop/project`).

### 3.1 File size and structure

```bash
ls -lh company_details
du -sh "company_details/2025-06-23 ThePublicJiraDataset/ThePublicJiraDataset" \
       "company_details/incident+management+process+enriched+event+log"
ls -lh "company_details/2025-06-23 ThePublicJiraDataset/ThePublicJiraDataset/0. DataDefinition"
ls -lh "company_details/incident+management+process+enriched+event+log"
```

### 3.2 Jira metadata only (no heavy restore)

```bash
jq 'keys' "company_details/2025-06-23 ThePublicJiraDataset/ThePublicJiraDataset/0. DataDefinition/jira_data_sources.json"

jq -r 'to_entries[] | [.key, .value.rough_issue_count, .value.jira_url] | @tsv' \
  "company_details/2025-06-23 ThePublicJiraDataset/ThePublicJiraDataset/0. DataDefinition/jira_data_sources.json" \
  | sort -k2,2

jq -r 'to_entries[] | [.key, (.value|keys|length)] | @tsv' \
  "company_details/2025-06-23 ThePublicJiraDataset/ThePublicJiraDataset/0. DataDefinition/jira_issuetype_information.json" \
  | sort -k2,2nr

jq -r 'to_entries[] | [.key, (.value|length)] | @tsv' \
  "company_details/2025-06-23 ThePublicJiraDataset/ThePublicJiraDataset/0. DataDefinition/jira_field_information.json" \
  | sort -k2,2nr
```

### 3.3 Incident CSV quick profile

```bash
wc -l "company_details/incident+management+process+enriched+event+log/incident_event_log.csv"
head -n 3 "company_details/incident+management+process+enriched+event+log/incident_event_log.csv"
awk -F',' 'NR==1{print NF " columns"}' "company_details/incident+management+process+enriched+event+log/incident_event_log.csv"

tail -n +2 "company_details/incident+management+process+enriched+event+log/incident_event_log.csv" \
  | cut -d',' -f1 | sort -u | wc -l

tail -n +2 "company_details/incident+management+process+enriched+event+log/incident_event_log.csv" \
  | cut -d',' -f2 | sort | uniq -c
```

## 4. How To Decide What To Keep For RAG

Use this order:

1. Pick Jira sources with incident-relevant issue types (`Incident`, `Problem`, `Service Request`) and common engineering types (`Bug`, `Task`, `Story`).
2. Keep per-source quotas to avoid one large source dominating retrieval.
3. Keep only retrieval-relevant fields for text:
   - `summary`, `description`, `issuetype`, `priority`, `status`, `project`, `labels`.
4. Deduplicate incident CSV to one latest row per incident.
5. Start with 4k Jira + 10k incident docs, then adjust based on retrieval quality.

Recommended spec file:
- `data/rag_subset_spec_v1.json`

Guide for this spec:
- `data/RAG_SUBSET_SPEC.md`

RAG pipeline tutorial for the built corpus:
- `company_details/RAG_PIPELINE_TUTORIAL.md`

## 5. Three-Step Execution (Commands Only)

These are the exact three steps from the main workflow.

### Step 1: Install MongoDB tools and run local MongoDB

Option A (Docker Mongo + local tools from package manager):

```bash
sudo apt-get update
sudo apt-get install -y mongodb-database-tools
docker run -d --name jira-mongo -p 27017:27017 --restart unless-stopped mongo:7
```

Verify:

```bash
command -v mongorestore
command -v mongoexport
docker ps --filter "name=jira-mongo"
```

### Step 2: Build the subset corpus using the spec

```bash
source venv/bin/activate
python scripts/prepare_rag_subset.py \
  --spec-file data/rag_subset_spec_v1.json \
  --output data/rag_corpus_subset_v1.jsonl
```

Quick check:

```bash
wc -l data/rag_corpus_subset_v1.jsonl
head -n 3 data/rag_corpus_subset_v1.jsonl
```

### Step 3: If a source under-fills, increase `export_multiplier` and rerun

Edit spec:

```bash
nano data/rag_subset_spec_v1.json
```

Rerun without restore:

```bash
source venv/bin/activate
python scripts/prepare_rag_subset.py \
  --spec-file data/rag_subset_spec_v1.json \
  --skip-restore \
  --output data/rag_corpus_subset_v1.jsonl
```

## 6. Typical Troubleshooting

### `mongorestore not found` or `mongoexport not found`

```bash
command -v mongorestore
command -v mongoexport
```

If empty, reinstall `mongodb-database-tools`.

### Mongo not reachable on `127.0.0.1:27017`

```bash
docker ps --filter "name=jira-mongo"
docker logs jira-mongo --tail 50
```

### Output size too large for embeddings

Reduce limits in `data/rag_subset_spec_v1.json`:
- lower `target_docs` for Jira collections.
- lower `incident.limit`.
