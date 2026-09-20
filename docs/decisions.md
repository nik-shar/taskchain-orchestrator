# Design Decisions

Short records of the non-obvious calls in this repo, and what each one cost. Read this
before changing the architecture: several of these decisions are load-bearing.

| # | Decision |
|---|---|
| [1](#1-taskchain-does-not-edit-code) | TaskChain does not edit code |
| [2](#2-mechanism-stays-agency-goes) | Mechanism stays, agency goes |
| [3](#3-edits-go-to-a-worktree-never-the-workspace) | Edits go to a worktree, never the workspace |
| [4](#4-mcp-tools-take-a-worktree_id-never-a-path) | MCP tools take a `worktree_id`, never a path |
| [5](#5-the-sandbox-fails-closed) | The sandbox fails closed |
| [6](#6-sqlite-fts5-for-retrieval-not-a-vector-database) | SQLite FTS5 for retrieval, not a vector database |
| [7](#7-fts5-requires-sqlite-which-constrains-deployment) | FTS5 requires SQLite, which constrains deployment |

Each entry follows the same shape: the decision, why it was made, and its cost.


---

## 1. TaskChain does not edit code

**Decision.** The project provides repository context and a sandboxed execution substrate.
It does not generate patches, apply them, or decide when a change is good enough.

**Context.** An earlier iteration implemented the full loop — Planner → Executor → Verifier,
with a bounded verify-and-retry cycle that re-ran the repository's own test suite and fed
failures back to the executor (`archive/editing-agent`). It worked: a fixture repo with a
genuine bug went from failing tests to passing across two attempts, gated on the test exit
code rather than the model's opinion.

**Why it was removed.** It made this another coding agent. The interesting problem here is
*what an agent needs to work on an unfamiliar repository* — grounded context, and somewhere
safe to act. Competing on patch quality means competing with every other agent framework;
supplying context and isolation is complementary to all of them.

**Consequence.** The interface becomes MCP, so any agent can consume it. Two claims were
retired: "multi-agent orchestrator with verify-retry" and "gated patch acceptance". The
implementation remains checkable at the git tag.

## 2. Mechanism stays, agency goes

The line is *who decides*, not *what is technically possible*.

| Kept (mechanism) | Removed (agency) |
|---|---|
| `write_file`, `delete_file`, `apply_patch` | the `{path, find, replace}` edit-schema an LLM was asked to emit |
| `sandbox_run` — run a command safely | choosing *which* command proves the work is done |
| `suggest_plan` — advisory text | acting on the plan |
| `open_pull_request` — a tool | deciding that a PR should be opened |

A caller with write tools is not an editing agent; a caller that is *told to produce edits*
is. That distinction keeps the substrate useful without pulling the product back into
patch generation.

## 3. Edits go to a worktree, never the workspace

`agent/code_tools.py` promises the indexed workspace is read-only. Editing that directory
would break retrieval for every later question and make runs non-reproducible.

So `create_worktree` copies the workspace into
`data/worktrees/<owner>/<repo>/<run_id>`, initialises git and commits a baseline. Every later
operation is a git operation against that copy: `diff` is a real unified diff, and resetting
is deleting a directory.

**Cost.** A copy per run, and disk usage that grows until `discard_worktree`. Acceptable:
repositories are already filtered to text files under 100 KB by ingestion.

## 4. MCP tools take a `worktree_id`, never a path

If `sandbox_run` accepted a host path, a client could bind-mount any directory into a
container — `/`, `~/.ssh`, the Docker socket. The sandbox would be an escalation primitive
rather than a boundary.

`worktree_id` is a relative identifier resolved under `config.WORKTREES_DIR`, and the
resolved path is checked to be inside that root before use. A hostile id (`../../..`) is
rejected. This is verified over the real protocol in a smoke test, not just in unit tests.

## 5. The sandbox fails closed

`run_sandbox_command` refuses to execute when Docker is unavailable. The earlier
implementation silently fell back to `subprocess.run(shell=True, cwd=clone)` on the host,
because commands are LLM-authored, that is a remote-code-execution path with a friendly
name. `SANDBOX_ALLOW_HOST_FALLBACK=1` restores it for local development only, and logs
loudly when used.

Isolation flags are assembled in one testable function (`build_sandbox_command`):
`--network none`, `--read-only`, `--tmpfs /tmp`, `--memory`, `--cpus`, `--pids-limit`, and
`--user` set to the invoking host uid so files written back into the mounted worktree keep
sane ownership instead of becoming root-owned.

**Cost.** Dependency installation needs network, so a repository whose dependencies are not
in the image cannot run its tests. The intended path is `build_repo_image()`, which bakes
dependencies into a per-repo image at build time where network *is* available. Running with
`--network bridge` is possible but should not be the default.

## 6. SQLite FTS5 for retrieval, not a vector database

Keyword search over 500 files returns in under a millisecond (P50 0.72 ms measured) and
needs no embedding provider, no key, and no external service.

**Cost.** No semantic matching: a question phrased with different vocabulary than the code
will miss. That is a real limitation, and the reason semantic retrieval is the first item on
the roadmap rather than dismissed. `SEMANTIC_TOP_K`/`FINAL_TOP_K` and the hit-rate half of
`scripts/benchmark_retrieval.py` are already in place for it.

## 7. FTS5 requires SQLite, which constrains deployment

`ingestion/sqlite_indexer.py` raises for non-SQLite `DATABASE_URL`s, and FTS5 is a SQLite
feature. Cloud SQL (Postgres) is therefore not a drop-in for the index.

This is why a Cloud Run deployment has to choose between an ephemeral `/tmp` index with
`--min-instances=1`, a GCS-mounted volume, or moving full-text search to Postgres. The
decision is deliberately deferred to the deployment work rather than forced now; the failure
mode without a decision is an ingestion that raises at the indexing step.
