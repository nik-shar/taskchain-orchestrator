# MCP Tool Reference

TaskChain exposes 18 tools over the [Model Context Protocol](https://modelcontextprotocol.io/).
They fall into two groups:

- **Context tools (read-only)** — grounding for the calling agent. None of them modify
  anything.
- **Execution tools** — an isolated worktree plus a hardened Docker sandbox, so the agent
  can change and test a repository without TaskChain performing the edit.

## Running the server

```bash
make mcp                  # stdio transport (default), for desktop and CLI clients
make mcp ARGS="--http"    # streamable HTTP on 127.0.0.1:8080
```

Equivalent to `python -m mcp_server.server [--http] [--host H] [--port P]`.

Client configuration (Claude Desktop / Cline style):

```json
{
  "mcpServers": {
    "taskchain": {
      "command": "/absolute/path/venv/bin/python",
      "args": ["-m", "mcp_server.server"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/taskchain-orchestrator",
        "DATABASE_URL": "sqlite:///data/rag_index.sqlite",
        "GITHUB_TOKEN": "ghp_..."
      }
    }
  }
}
```

## Recommended session

```
index_repository   →  list_files / search_code / read_file   (grounding)
create_worktree    →  write_file / apply_patch               (act)
sandbox_run        →  diff                                   (verify)
open_pull_request  →  discard_worktree                       (deliver, clean up)
```

## Security model

1. **No tool accepts a host filesystem path.** Execution tools take a `worktree_id`
   returned by `create_worktree`, resolved under `config.WORKTREES_DIR` and checked to be
   inside that root. An id such as `../../..` is rejected.
2. **Paths inside a worktree are resolved and re-checked** before any read or write, so a
   `path` argument cannot escape the worktree either.
3. **`sandbox_run` fails closed.** With no Docker daemon it refuses to execute rather than
   running on the host. `SANDBOX_ALLOW_HOST_FALLBACK=1` opts into host execution for local
   development only.
4. **The indexed workspace is read-only.** Every change lands in a per-run worktree.

## Error semantics

| Situation | Behaviour |
|---|---|
| `worktree_id` outside the worktree root, or unknown | tool raises `ValueError` |
| `path` escapes the worktree | returns `{"applied": [], "errors": [...]}` |
| Patch does not apply | returns `{"applied": [], "errors": [...]}`; nothing is written |
| Docker unavailable | `{"ran": false, "passed": false, "skipped_reason": "docker unavailable (host fallback disabled)"}` |
| Command exceeds its timeout | `{"ran": true, "passed": false, "timed_out": true, "exit_code": -2}` |
| Repository not indexed | context tools return empty results; `create_worktree` raises |


---

## Context tools (read-only)

### `list_indexed_repos`

List repositories that have been ingested, with index sizes.

| | |
|---|---|
| Parameters | none |
| Returns | `list[{repo_id, status, issues, pull_requests, files_indexed}]` |

### `index_repository`

Ingest a public GitHub repository: metadata, documentation, file tree, issues and pull
requests. Long-running — it calls the GitHub API and downloads the repository tarball — and
requires `GITHUB_TOKEN` in the server environment.

| | |
|---|---|
| Parameters | `repo_url` (str) — a GitHub URL, with or without `.git` |
| Returns | `{repo_id, status, issue_count, pr_count, files_indexed}` |
| Side effects | writes the index, `data/workspaces/<owner>/<repo>/` and documentation rows |

### `repo_summary`

The stored repository summary: what it does, detected tech stack, entry points, activity.

| | |
|---|---|
| Parameters | `repo_id` (str) |
| Returns | `str` — the summary, or a message explaining that the repo is not indexed yet |

### `list_files`

Text files available in the repository's read-only workspace, sorted by path.

| | |
|---|---|
| Parameters | `repo_id` (str), `limit` (int, default `500`) |
| Returns | `list[str]` — repository-relative paths; `[]` if the repo is not indexed |

### `read_file`

Read a single file, bounded by a character cap.

| | |
|---|---|
| Parameters | `repo_id` (str), `path` (str), `max_chars` (int, optional; default `CODE_FILE_MAX_CHARS` = 8000) |
| Returns | `{path, content, truncated, total_chars}` or `null` |
| Notes | Returns `null` for a missing file, a path escape, or a file over 100 KB |

### `search_code`

Keyword search over the indexed source files, backed by the SQLite FTS5 `files_fts` table.

| | |
|---|---|
| Parameters | `repo_id` (str), `query` (str), `top_k` (int, default `5`) |
| Returns | `list[{path, snippet}]`, ranked by relevance |
| Notes | The query is tokenised and quoted, so punctuation cannot break the match; `[]` for an unindexed repo |

### `search_issues`

Keyword search over indexed issues and pull requests (`issues_fts`).

| | |
|---|---|
| Parameters | `repo_id` (str), `query` (str), `top_k` (int, default `5`) |
| Returns | `list[{repo_id, number, title, body, labels, state, type}]` where `type` is `issue` or `pr` |

### `repository_docs`

Curated documentation (README and similar), assembled under a character budget with the
most important documents first.

| | |
|---|---|
| Parameters | `repo_id` (str) |
| Returns | `str` — the budgeted documentation block, or `""` |

### `suggest_plan`

Ask the LLM for a suggested approach to an issue. Advisory context only: TaskChain returns
the plan and stops, and never acts on it.

| | |
|---|---|
| Parameters | `repo_id` (str), `issue_description` (str) |
| Returns | `{repo_id, issue, plan, context}` |
| Notes | Falls back to a generic plan when the LLM call fails, so it never raises |


---

## Execution tools

### `create_worktree`

Create an isolated, git-initialised copy of a repository to work in, with a baseline commit
so `diff` reports only the agent's changes.

| | |
|---|---|
| Parameters | `repo_id` (str), `run_id` (str, optional; a random id is generated if omitted) |
| Returns | `{worktree_id, files}` |
| Side effects | copies the workspace to `data/worktrees/<owner>/<repo>/<run_id>` |
| Errors | raises if the repository has not been indexed |

### `write_file`

Write a file inside the worktree, creating parent directories.

| | |
|---|---|
| Parameters | `worktree_id` (str), `path` (str), `content` (str) |
| Returns | `{applied: [path], errors: []}` |

### `delete_file`

Delete a file inside the worktree.

| | |
|---|---|
| Parameters | `worktree_id` (str), `path` (str) |
| Returns | `{applied, errors}` — an error if the file does not exist |

### `apply_patch`

Apply a unified diff. Validated with `git apply --check` first, so a patch that does not
apply leaves the worktree untouched.

| | |
|---|---|
| Parameters | `worktree_id` (str), `unified_diff` (str) |
| Returns | `{applied, errors}` — `applied` lists the files named by *this* diff |

### `sandbox_run`

Run a shell command in the sandboxed container, with the worktree mounted at `/workspace`.

| | |
|---|---|
| Parameters | `worktree_id` (str), `command` (str), `timeout` (int seconds, optional; default `SANDBOX_TIMEOUT_S` = 300) |
| Returns | `{command, ran, passed, exit_code, timed_out, skipped_reason, stdout, stderr}` |
| Isolation | `--network none`, `--read-only`, `--tmpfs /tmp`, `--memory`, `--cpus`, `--pids-limit`, non-root `--user` |
| Notes | `passed` is true only for a genuine zero exit; output is truncated to 8,000 characters |

### `suggested_test_command`

The test command TaskChain would infer for this repository, if its manifests allow.

| | |
|---|---|
| Parameters | `worktree_id` (str) |
| Returns | `str` or `null` — e.g. `python -m pytest -q`, `npm test --silent`, `go test ./...` |

### `diff`

Everything the agent has changed in the worktree, as a real git diff.

| | |
|---|---|
| Parameters | `worktree_id` (str) |
| Returns | `{files_changed: [path], diff: str}` — the diff is truncated to 8,000 characters |

### `discard_worktree`

Delete the worktree and everything in it.

| | |
|---|---|
| Parameters | `worktree_id` (str) |
| Returns | `str` — a confirmation message |

### `open_pull_request`

Open a pull request through the GitHub API, so the agent needs no GitHub write path of its
own.

| | |
|---|---|
| Parameters | `owner` (str), `repo` (str), `title` (str), `body` (str), `head_branch` (str), `base_branch` (str, default `"main"`) |
| Returns | `{pr_number, html_url}` |
| Notes | Requires `GITHUB_TOKEN` with repository write scope; the branch must already exist |

---

## Worked example

Verified end-to-end over stdio against a fixture repository with a genuine bug:

```
create_worktree   {repo_id: "demo/sandbox-demo"}
  -> {worktree_id: "demo/sandbox-demo/demo2", files: 2}

sandbox_run       {worktree_id, command: "python -m unittest discover -q"}
  -> {passed: false, exit_code: 1}          # FAILED (failures=1)

write_file        {worktree_id, path: "app.py", content: "def add(a, b):\n    return a + b\n"}
  -> {applied: ["app.py"], errors: []}

sandbox_run       {worktree_id, command: "python -m unittest discover -q"}
  -> {passed: true, exit_code: 0}           # OK

diff              {worktree_id}
  -> {files_changed: ["app.py"],
      diff: "-    return a - b\n+    return a + b"}

discard_worktree  {worktree_id}
  -> "Discarded demo/sandbox-demo/demo2"
```

The caller decided the edit; TaskChain supplied the context and the isolation.
