from __future__ import annotations


def render_homepage() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Orchestrator API Console</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link
    href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&display=swap"
    rel="stylesheet"
  >
  <link
    href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&display=swap"
    rel="stylesheet"
  >
  <style>
    :root {
      --bg: #f3efe6;
      --panel: #fffaf0;
      --ink: #112433;
      --muted: #5c6b74;
      --accent: #0f8b8d;
      --accent-strong: #136f63;
      --line: #d7d1c3;
      --warn: #b00020;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Space Grotesk", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 10% 10%, #b6e3df 0%, transparent 45%),
        radial-gradient(circle at 90% 85%, #ffd3a8 0%, transparent 42%),
        var(--bg);
    }
    .wrap {
      max-width: 1000px;
      margin: 24px auto;
      padding: 0 16px 24px;
      display: grid;
      gap: 16px;
    }
    .hero, .card {
      background: color-mix(in srgb, var(--panel) 88%, white 12%);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: 0 8px 22px rgba(17, 36, 51, 0.08);
    }
    .hero {
      padding: 20px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .title {
      margin: 0;
      font-size: clamp(1.3rem, 2.5vw, 2rem);
      line-height: 1.1;
    }
    .sub { margin: 6px 0 0; color: var(--muted); }
    .pill {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.78rem;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 6px 10px;
      background: #fff;
    }
    .card { padding: 16px; }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }
    label {
      display: block;
      margin-bottom: 6px;
      font-weight: 700;
      font-size: 0.92rem;
    }
    textarea, input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.9rem;
      background: #fff;
      color: var(--ink);
    }
    textarea { min-height: 148px; resize: vertical; }
    .row { display: flex; gap: 10px; flex-wrap: wrap; }
    button {
      border: none;
      border-radius: 10px;
      padding: 10px 14px;
      font-family: "Space Grotesk", sans-serif;
      font-weight: 700;
      cursor: pointer;
      transition: transform 120ms ease, opacity 120ms ease;
    }
    button:hover { transform: translateY(-1px); }
    button:active { transform: translateY(0); }
    .primary { background: var(--accent); color: #fff; }
    .secondary { background: #edf6f5; color: var(--accent-strong); }
    .danger { background: #ffe8ec; color: var(--warn); }
    .hint {
      margin-top: 10px;
      font-size: 0.85rem;
      color: var(--muted);
    }
    .status {
      margin: 0;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.9rem;
    }
    .error { color: var(--warn); }
    pre {
      margin: 0;
      overflow: auto;
      max-height: 380px;
      background: #112433;
      color: #ebf7f7;
      border-radius: 12px;
      padding: 14px;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.82rem;
      line-height: 1.42;
    }
    @media (max-width: 780px) {
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main class="wrap">
    <section class="hero">
      <div>
        <h1 class="title">Orchestrator API Console</h1>
        <p class="sub">Create tasks, run orchestration, inspect outputs.</p>
      </div>
      <span class="pill">FastAPI + Planner + Tools + Verifier</span>
    </section>

    <section class="card">
      <div class="grid">
        <div>
          <label for="taskInput">Task</label>
          <textarea id="taskInput">
P1 alert: Checkout API latency and errors increased in production.
Analyze metrics and logs for saas-api between 2026-02-14T10:00:00Z and 2026-02-14T10:30:00Z.
Find related OPS Jira incidents and propose escalation + communication steps with policy citations.
          </textarea>
        </div>
        <div>
          <label for="contextInput">Context (JSON)</label>
          <textarea id="contextInput">{
  "service": "saas-api",
  "project_key": "OPS",
  "severity": "P1",
  "start_time": "2026-02-14T10:00:00Z",
  "end_time": "2026-02-14T10:30:00Z",
  "required_citations": [
    "policy_v2",
    "oncall_rota",
    "slack_config"
  ]
}</textarea>
        </div>
      </div>
      <div class="row" style="margin-top: 12px;">
        <button class="primary" id="createBtn">Create Task</button>
        <button class="secondary" id="runBtn">Run Task</button>
        <button class="secondary" id="fetchBtn">Fetch Task</button>
        <button class="danger" id="clearBtn">Clear Output</button>
      </div>
      <p class="hint">Task ID: <input id="taskIdInput" placeholder="auto-filled after create"></p>
      <p class="status" id="statusText">Ready.</p>
    </section>

    <section class="card">
      <label>Response</label>
      <pre id="output">No response yet.</pre>
    </section>
  </main>

  <script>
    const taskInput = document.getElementById("taskInput");
    const contextInput = document.getElementById("contextInput");
    const taskIdInput = document.getElementById("taskIdInput");
    const statusText = document.getElementById("statusText");
    const output = document.getElementById("output");

    function setStatus(message, isError = false) {
      statusText.textContent = message;
      statusText.classList.toggle("error", isError);
    }

    function writeOutput(data) {
      output.textContent = JSON.stringify(data, null, 2);
    }

    function parseContext() {
      try {
        const raw = contextInput.value.trim();
        return raw ? JSON.parse(raw) : {};
      } catch (err) {
        throw new Error("Context must be valid JSON.");
      }
    }

    async function sendJson(url, method, body) {
      const response = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(JSON.stringify(data));
      }
      return data;
    }

    document.getElementById("createBtn").addEventListener("click", async () => {
      try {
        setStatus("Creating task...");
        const payload = {
          task: taskInput.value.trim(),
          context: parseContext(),
        };
        const data = await sendJson("/tasks", "POST", payload);
        taskIdInput.value = data.task_id;
        writeOutput(data);
        setStatus("Task created.");
      } catch (err) {
        setStatus(String(err.message || err), true);
      }
    });

    document.getElementById("runBtn").addEventListener("click", async () => {
      try {
        const taskId = taskIdInput.value.trim();
        if (!taskId) {
          throw new Error("Task ID is required.");
        }
        setStatus("Running task...");
        const data = await sendJson(`/tasks/${taskId}/run`, "POST", {});
        writeOutput(data);
        setStatus(`Run completed with status: ${data.status}`);
      } catch (err) {
        setStatus(String(err.message || err), true);
      }
    });

    document.getElementById("fetchBtn").addEventListener("click", async () => {
      try {
        const taskId = taskIdInput.value.trim();
        if (!taskId) {
          throw new Error("Task ID is required.");
        }
        setStatus("Fetching task...");
        const response = await fetch(`/tasks/${taskId}`);
        const data = await response.json();
        if (!response.ok) {
          throw new Error(JSON.stringify(data));
        }
        writeOutput(data);
        setStatus(`Fetched task with status: ${data.status}`);
      } catch (err) {
        setStatus(String(err.message || err), true);
      }
    });

    document.getElementById("clearBtn").addEventListener("click", () => {
      output.textContent = "No response yet.";
      setStatus("Cleared.");
    });
  </script>
</body>
</html>
"""
