from __future__ import annotations

# Pipeline overview:
# 1) Restore/export a scoped Jira subset (optional; can be skipped).
# 2) Normalize Jira + incident rows into one canonical JSONL schema:
#    {"doc_id","source","text","metadata"}.
# 3) Write merged corpus for downstream chunking/indexing.

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_JIRA_EXPORT_FIELDS = [
    "key",
    "fields.summary",
    "fields.description",
    "fields.issuetype.name",
    "fields.priority.name",
    "fields.status.name",
    "fields.project.key",
    "fields.created",
    "fields.updated",
    "fields.labels",
]


def _run(cmd: list[str]) -> None:
    print("Running:", " ".join(cmd))
    completed = subprocess.run(cmd, text=True, capture_output=True)
    if completed.returncode != 0:
        if completed.stdout:
            print(completed.stdout.strip())
        if completed.stderr:
            print(completed.stderr.strip(), file=sys.stderr)
        raise RuntimeError(f"Command failed with code {completed.returncode}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a RAM-friendly RAG corpus from a small Jira subset + incident event log."
        )
    )
    parser.add_argument(
        "--jira-archive",
        type=Path,
        default=Path(
            "company_details/2025-06-23 ThePublicJiraDataset/"
            "ThePublicJiraDataset/3. DataDump/mongodump-JiraReposAnon.archive"
        ),
        help="Path to the Jira mongodump archive.",
    )
    parser.add_argument(
        "--incident-csv",
        type=Path,
        default=Path(
            "company_details/incident+management+process+enriched+event+log/"
            "incident_event_log.csv"
        ),
        help="Path to incident event log CSV.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/rag_corpus_subset.jsonl"),
        help="Output JSONL path.",
    )
    parser.add_argument(
        "--mongo-uri",
        default="mongodb://127.0.0.1:27017",
        help="Mongo URI used by mongorestore/mongoexport.",
    )
    parser.add_argument(
        "--source-db",
        default="JiraReposAnon",
        help="Database namespace in the source archive.",
    )
    parser.add_argument(
        "--restore-db",
        default="JiraSubset",
        help="Temporary local database name to restore subset into.",
    )
    parser.add_argument(
        "--collections",
        nargs="+",
        default=["Mindville", "SecondLife", "IntelDAOS", "JFrog", "Hyperledger"],
        help="Collections/repos to restore and sample from.",
    )
    parser.add_argument(
        "--jira-per-collection",
        type=int,
        default=800,
        help="Issues to export per Jira collection (default 800 -> 4,000 total for 5 collections).",
    )
    parser.add_argument(
        "--incident-limit",
        type=int,
        default=25000,
        help="Maximum number of deduplicated incidents to emit.",
    )
    parser.add_argument(
        "--skip-restore",
        action="store_true",
        help="Skip mongorestore (use if subset DB already exists).",
    )
    parser.add_argument(
        "--skip-jira-export",
        action="store_true",
        help="Skip Jira export and include incidents only.",
    )
    parser.add_argument(
        "--tmp-dir",
        type=Path,
        default=Path("data/.jira_subset_tmp"),
        help="Temporary folder for mongoexport output.",
    )
    parser.add_argument(
        "--spec-file",
        type=Path,
        default=None,
        help=(
            "Optional JSON spec for per-collection quotas/filters. "
            "If provided, it overrides --collections, --jira-per-collection, and --incident-limit."
        ),
    )
    return parser.parse_args()


def _ensure_tools(skip_restore: bool, skip_jira_export: bool) -> None:
    if not skip_jira_export and not skip_restore and _tool_missing("mongorestore"):
        raise RuntimeError("mongorestore not found. Install MongoDB Database Tools first.")
    if not skip_jira_export and _tool_missing("mongoexport"):
        raise RuntimeError("mongoexport not found. Install MongoDB Database Tools first.")


def _tool_missing(tool_name: str) -> bool:
    check = subprocess.run(
        ["bash", "-lc", f"command -v {tool_name} >/dev/null 2>&1"],
        text=True,
        capture_output=True,
    )
    return check.returncode != 0


def _resolve_extraction_plan(
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    # When no spec file is provided, fall back to simple CLI-level defaults.
    # With a spec file, we use per-collection quotas + issue type filters.
    if args.spec_file is None:
        collections = [
            {
                "name": collection,
                "target_docs": args.jira_per_collection,
                "issue_types": None,
                "export_multiplier": 1,
            }
            for collection in args.collections
        ]
        return collections, args.incident_limit, list(DEFAULT_JIRA_EXPORT_FIELDS)

    spec = json.loads(args.spec_file.read_text(encoding="utf-8"))

    jira_spec = spec.get("jira", {})
    incident_spec = spec.get("incident", {})
    collections_spec = jira_spec.get("collections")
    if not isinstance(collections_spec, list) or not collections_spec:
        raise RuntimeError("Spec file must define jira.collections as a non-empty list.")

    resolved_collections: list[dict[str, Any]] = []
    for item in collections_spec:
        name = str(item.get("name", "")).strip()
        if not name:
            raise RuntimeError("Each jira.collections entry must contain a non-empty 'name'.")
        target_docs = int(item.get("target_docs", 0))
        if target_docs <= 0:
            raise RuntimeError(f"Collection '{name}' must define target_docs > 0.")
        issue_types = item.get("issue_types")
        if issue_types is not None:
            if not isinstance(issue_types, list):
                raise RuntimeError(f"Collection '{name}' issue_types must be a list if present.")
            issue_types = {str(t).strip() for t in issue_types if str(t).strip()}
        export_multiplier = int(item.get("export_multiplier", 2))
        if export_multiplier < 1:
            export_multiplier = 1
        resolved_collections.append(
            {
                "name": name,
                "target_docs": target_docs,
                "issue_types": issue_types,
                "export_multiplier": export_multiplier,
            }
        )

    incident_limit = int(incident_spec.get("limit", args.incident_limit))
    if incident_limit <= 0:
        raise RuntimeError("incident.limit in spec must be > 0.")

    jira_fields = jira_spec.get("fields", DEFAULT_JIRA_EXPORT_FIELDS)
    if not isinstance(jira_fields, list) or not jira_fields:
        raise RuntimeError("jira.fields in spec must be a non-empty list if present.")
    jira_fields = [str(field).strip() for field in jira_fields if str(field).strip()]
    if not jira_fields:
        raise RuntimeError("jira.fields in spec resolved to an empty list.")

    return resolved_collections, incident_limit, jira_fields


def _restore_subset(
    archive: Path,
    mongo_uri: str,
    source_db: str,
    restore_db: str,
    collections: list[str],
) -> None:
    for collection in collections:
        ns_include = f"{source_db}.{collection}"
        ns_from = ns_include
        ns_to = f"{restore_db}.{collection}"
        cmd = [
            "mongorestore",
            f"--uri={mongo_uri}",
            "--gzip",
            f"--archive={archive}",
            f"--nsInclude={ns_include}",
            f"--nsFrom={ns_from}",
            f"--nsTo={ns_to}",
        ]
        _run(cmd)


def _export_collection(
    mongo_uri: str,
    restore_db: str,
    collection: str,
    out_file: Path,
    limit: int,
    fields: list[str],
) -> None:
    cmd = [
        "mongoexport",
        f"--uri={mongo_uri}",
        f"--db={restore_db}",
        f"--collection={collection}",
        "--type=json",
        f"--out={out_file}",
        f"--limit={limit}",
        f"--fields={','.join(fields)}",
    ]
    _run(cmd)


def _coerce_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _build_jira_text(issue: dict[str, Any]) -> str:
    fields = issue.get("fields", {})
    summary = _coerce_string(fields.get("summary"))
    description = _coerce_string(fields.get("description"))
    issue_type = _coerce_string(fields.get("issuetype", {}).get("name"))
    priority = _coerce_string(fields.get("priority", {}).get("name"))
    status = _coerce_string(fields.get("status", {}).get("name"))
    project = _coerce_string(fields.get("project", {}).get("key"))
    labels = fields.get("labels", [])
    labels_str = ", ".join(lbl for lbl in labels if isinstance(lbl, str))
    parts = [
        f"Project: {project}" if project else "",
        f"IssueType: {issue_type}" if issue_type else "",
        f"Priority: {priority}" if priority else "",
        f"Status: {status}" if status else "",
        f"Summary: {summary}" if summary else "",
        f"Description: {description}" if description else "",
        f"Labels: {labels_str}" if labels_str else "",
    ]
    return "\n".join(p for p in parts if p)


def _load_jira_docs(
    export_path: Path,
    collection: str,
    allowed_issue_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    # Convert each exported Jira issue line into the canonical RAG doc format.
    docs: list[dict[str, Any]] = []
    with export_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            issue = json.loads(line)
            fields = issue.get("fields", {})
            issue_type = _coerce_string(fields.get("issuetype", {}).get("name"))
            if allowed_issue_types and issue_type not in allowed_issue_types:
                continue
            issue_key = _coerce_string(issue.get("key"))
            if not issue_key:
                issue_key = _coerce_string(issue.get("_id"))
            text = _build_jira_text(issue)
            if not text:
                continue
            docs.append(
                {
                    "doc_id": f"jira:{collection}:{issue_key}",
                    "source": "jira",
                    "text": text,
                    "metadata": {
                        "collection": collection,
                        "issue_key": issue_key,
                        "issue_type": issue_type,
                        "priority": _coerce_string(fields.get("priority", {}).get("name")),
                        "status": _coerce_string(fields.get("status", {}).get("name")),
                        "project": _coerce_string(fields.get("project", {}).get("key")),
                        "created": _coerce_string(fields.get("created")),
                        "updated": _coerce_string(fields.get("updated")),
                    },
                }
            )
    return docs


def _safe_int(raw: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return -1


def _dedup_incidents(incident_csv: Path, incident_limit: int) -> list[dict[str, str]]:
    # Incident logs often contain multiple lifecycle rows per incident number.
    # Keep the latest version by highest sys_mod_count, then cap by incident_limit.
    latest_by_incident: dict[str, dict[str, str]] = {}
    with incident_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            incident_id = row.get("number", "").strip()
            if not incident_id:
                continue
            existing = latest_by_incident.get(incident_id)
            if existing is None:
                latest_by_incident[incident_id] = row
                continue
            existing_mod = _safe_int(existing.get("sys_mod_count", ""))
            new_mod = _safe_int(row.get("sys_mod_count", ""))
            if new_mod >= existing_mod:
                latest_by_incident[incident_id] = row
    rows = list(latest_by_incident.values())
    rows.sort(key=lambda r: (r.get("opened_at", ""), r.get("number", "")))
    return rows[:incident_limit]


def _build_incident_text(row: dict[str, str]) -> str:
    fields = [
        ("Incident", row.get("number", "")),
        ("State", row.get("incident_state", "")),
        ("Priority", row.get("priority", "")),
        ("Impact", row.get("impact", "")),
        ("Urgency", row.get("urgency", "")),
        ("Category", row.get("category", "")),
        ("Subcategory", row.get("subcategory", "")),
        ("AssignmentGroup", row.get("assignment_group", "")),
        ("AssignedTo", row.get("assigned_to", "")),
        ("OpenedAt", row.get("opened_at", "")),
        ("ResolvedAt", row.get("resolved_at", "")),
        ("ClosedAt", row.get("closed_at", "")),
        ("ClosedCode", row.get("closed_code", "")),
    ]
    cleaned = []
    for name, value in fields:
        text = _coerce_string(value)
        if not text or text == "?":
            continue
        cleaned.append(f"{name}: {text}")
    return "\n".join(cleaned)


def _build_incident_docs(incident_csv: Path, incident_limit: int) -> list[dict[str, Any]]:
    # Convert incident CSV rows into canonical docs after deduplication.
    docs: list[dict[str, Any]] = []
    for row in _dedup_incidents(incident_csv=incident_csv, incident_limit=incident_limit):
        incident_id = _coerce_string(row.get("number"))
        text = _build_incident_text(row)
        if not incident_id or not text:
            continue
        docs.append(
            {
                "doc_id": f"incident:{incident_id}",
                "source": "incident_event_log",
                "text": text,
                "metadata": {
                    "incident_number": incident_id,
                    "state": _coerce_string(row.get("incident_state")),
                    "opened_at": _coerce_string(row.get("opened_at")),
                    "closed_at": _coerce_string(row.get("closed_at")),
                    "priority": _coerce_string(row.get("priority")),
                },
            }
        )
    return docs


def main() -> None:
    args = _parse_args()
    collection_plan, incident_limit, jira_fields = _resolve_extraction_plan(args)
    _ensure_tools(skip_restore=args.skip_restore, skip_jira_export=args.skip_jira_export)

    # Output paths are created up-front so partial runs fail less often due to missing dirs.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.tmp_dir.mkdir(parents=True, exist_ok=True)

    # Stage 1: optionally restore selected Jira collections from archive into a local DB.
    if not args.skip_jira_export and not args.skip_restore:
        _restore_subset(
            archive=args.jira_archive,
            mongo_uri=args.mongo_uri,
            source_db=args.source_db,
            restore_db=args.restore_db,
            collections=[item["name"] for item in collection_plan],
        )

    jira_docs: list[dict[str, Any]] = []
    # Stage 2: export and normalize Jira docs using per-collection quotas/filters.
    if not args.skip_jira_export:
        for item in collection_plan:
            collection = item["name"]
            target_docs = int(item["target_docs"])
            export_multiplier = int(item["export_multiplier"])
            export_limit = max(target_docs, target_docs * export_multiplier)
            allowed_issue_types = item["issue_types"]
            export_path = args.tmp_dir / f"{collection}.jsonl"
            _export_collection(
                mongo_uri=args.mongo_uri,
                restore_db=args.restore_db,
                collection=collection,
                out_file=export_path,
                limit=export_limit,
                fields=jira_fields,
            )
            loaded_docs = _load_jira_docs(
                export_path=export_path,
                collection=collection,
                allowed_issue_types=allowed_issue_types,
            )
            trimmed_docs = loaded_docs[:target_docs]
            jira_docs.extend(trimmed_docs)
            print(
                f"Collection {collection}: exported up to {export_limit}, "
                f"after filters {len(loaded_docs)}, kept {len(trimmed_docs)}"
            )

    # Stage 3: normalize incident CSV into canonical docs.
    incident_docs = _build_incident_docs(
        incident_csv=args.incident_csv,
        incident_limit=incident_limit,
    )

    # Stage 4: merge all sources into a single JSONL corpus for index building.
    all_docs = jira_docs + incident_docs
    with args.output.open("w", encoding="utf-8") as out:
        for doc in all_docs:
            out.write(json.dumps(doc, ensure_ascii=True))
            out.write("\n")

    print(f"Wrote {len(all_docs)} docs to {args.output}")
    print(f"Jira docs: {len(jira_docs)}")
    print(f"Incident docs: {len(incident_docs)}")


if __name__ == "__main__":
    main()
