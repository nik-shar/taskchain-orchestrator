from __future__ import annotations


def render_homepage(*, app_name: str) -> str:
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{app_name} Pipeline Explorer</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #eef2f3;
      --panel: #ffffff;
      --ink: #1c2a38;
      --muted: #5d6d79;
      --line: #d5dde2;
      --accent: #146c94;
      --accent-2: #19a7ce;
      --ok: #1f7a42;
      --err: #a4202c;
      --warn: #8a6a00;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Space Grotesk", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 10% 10%, #d8efff 0%, transparent 42%),
        radial-gradient(circle at 90% 80%, #fde3c5 0%, transparent 36%),
        var(--bg);
    }}
    .wrap {{
      max-width: 1150px;
      margin: 22px auto 40px;
      padding: 0 16px;
      display: grid;
      gap: 16px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: 0 10px 24px rgba(17, 34, 51, 0.06);
      padding: 16px;
    }}
    .hero {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
    }}
    .title {{
      margin: 0;
      font-size: clamp(1.2rem, 2.6vw, 2rem);
    }}
    .sub {{
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .pill {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 6px 10px;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.78rem;
      white-space: nowrap;
      background: #f7fbfd;
    }}
    .grid {{
      display: grid;
      gap: 12px;
      grid-template-columns: 1.2fr 1fr;
    }}
    @media (max-width: 900px) {{
      .grid {{ grid-template-columns: 1fr; }}
      .hero {{ flex-direction: column; align-items: flex-start; }}
    }}
    label {{
      display: block;
      font-weight: 700;
      margin-bottom: 6px;
      font-size: 0.9rem;
    }}
    textarea, input {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.86rem;
      color: var(--ink);
      background: #fff;
    }}
    textarea {{ min-height: 130px; resize: vertical; }}
    .actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 10px;
    }}
    button {{
      border: none;
      border-radius: 10px;
      padding: 10px 14px;
      font-family: "Space Grotesk", sans-serif;
      font-weight: 700;
      cursor: pointer;
      background: var(--accent);
      color: #fff;
    }}
    button.secondary {{
      background: #e9f6fb;
      color: var(--accent);
      border: 1px solid #c8e8f3;
    }}
    button.ghost {{
      background: #f8fafb;
      color: var(--muted);
      border: 1px solid var(--line);
    }}
    .status {{
      margin: 10px 0 0;
      font-size: 0.88rem;
      color: var(--muted);
      font-family: "IBM Plex Mono", monospace;
    }}
    .error {{ color: var(--err); }}
    .ok {{ color: var(--ok); }}
    .warn {{ color: var(--warn); }}
    .timeline {{
      display: grid;
      gap: 12px;
      margin-top: 8px;
    }}
    .step {{
      border: 1px solid var(--line);
      border-left: 6px solid var(--accent-2);
      border-radius: 12px;
      padding: 12px;
      background: #fcfeff;
      animation: reveal 220ms ease;
    }}
    .step.fail {{
      border-left-color: var(--err);
      background: #fff7f8;
    }}
    .step.ok {{
      border-left-color: var(--ok);
      background: #f5fff9;
    }}
    .step h4 {{
      margin: 0 0 8px;
      font-size: 0.95rem;
    }}
    .meta {{
      font-size: 0.8rem;
      color: var(--muted);
      margin-bottom: 8px;
      font-family: "IBM Plex Mono", monospace;
    }}
    pre {{
      margin: 0;
      padding: 10px;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: #1d2935;
      color: #e8f1f5;
      overflow: auto;
      max-height: 260px;
      font-size: 0.78rem;
      line-height: 1.4;
      font-family: "IBM Plex Mono", monospace;
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    @media (max-width: 900px) {{
      .summary-grid {{ grid-template-columns: 1fr; }}
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fafcfd;
      padding: 10px;
    }}
    .metric .k {{
      font-size: 0.76rem;
      color: var(--muted);
      font-family: "IBM Plex Mono", monospace;
    }}
    .metric .v {{
      font-size: 0.98rem;
      margin-top: 4px;
      font-weight: 700;
    }}
    .citations {{
      display: grid;
      gap: 10px;
    }}
    .citation {{
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #f9fcfe;
      padding: 10px;
    }}
    .citation .head {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-size: 0.82rem;
      font-family: "IBM Plex Mono", monospace;
      color: var(--muted);
      margin-bottom: 6px;
      flex-wrap: wrap;
    }}
    .citation .snippet {{
      font-size: 0.88rem;
      margin: 0 0 6px;
    }}
    .citation .why {{
      font-size: 0.82rem;
      color: var(--muted);
      margin: 0;
      font-family: "IBM Plex Mono", monospace;
    }}
    .trace-grid {{
      display: grid;
      gap: 10px;
      grid-template-columns: 1fr 1fr;
    }}
    @media (max-width: 900px) {{
      .trace-grid {{ grid-template-columns: 1fr; }}
    }}
    .trace-pane {{
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fafcfd;
      padding: 10px;
    }}
    .trace-pane h4 {{
      margin: 0 0 8px;
      font-size: 0.9rem;
    }}
    @keyframes reveal {{
      from {{ opacity: 0; transform: translateY(4px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="card hero">
      <div>
        <h1 class="title">Pipeline Explorer</h1>
        <p class="sub">Create a task, run it, and inspect each orchestration step and tool output.</p>
      </div>
      <span class="pill">LangGraph pipeline: plan -> retrieve -> execute -> verify -> finalize</span>
    </section>

    <section class="card">
      <div class="grid">
        <div>
          <label for="promptInput">Task Prompt</label>
          <textarea id="promptInput">P1 priority: general profile picture errors for users causing intermittent failures.</textarea>
        </div>
        <div>
          <label for="taskIdInput">Task ID</label>
          <input id="taskIdInput" placeholder="auto-filled after create">
          <div class="actions">
            <button id="createBtn">Create</button>
            <button id="runBtn">Run</button>
            <button id="inspectBtn" class="secondary">Inspect Latest Run</button>
            <button id="clearBtn" class="ghost">Clear</button>
          </div>
          <p id="statusText" class="status">Ready.</p>
        </div>
      </div>
    </section>

    <section class="card">
      <h3 style="margin:0 0 10px;">Run Summary</h3>
      <div id="summaryGrid" class="summary-grid"></div>
    </section>

    <section class="card">
      <h3 style="margin:0 0 10px;">Citations</h3>
      <p id="citationsEmpty" class="status" style="margin-top:0;">Run retrieval tools to view citation evidence.</p>
      <div id="citations" class="citations"></div>
    </section>

    <section class="card">
      <h3 style="margin:0 0 10px;">Incident Brief Trace</h3>
      <p id="briefTraceEmpty" class="status" style="margin-top:0;">Run an incident task to view brief fields vs raw evidence.</p>
      <div id="briefTrace" class="trace-grid"></div>
    </section>

    <section class="card">
      <h3 style="margin:0 0 10px;">Step-by-Step Timeline</h3>
      <div id="timeline" class="timeline"></div>
    </section>
  </main>

  <script>
    const promptInput = document.getElementById("promptInput");
    const taskIdInput = document.getElementById("taskIdInput");
    const statusText = document.getElementById("statusText");
    const timeline = document.getElementById("timeline");
    const summaryGrid = document.getElementById("summaryGrid");
    const citations = document.getElementById("citations");
    const citationsEmpty = document.getElementById("citationsEmpty");
    const briefTrace = document.getElementById("briefTrace");
    const briefTraceEmpty = document.getElementById("briefTraceEmpty");

    function setStatus(text, kind = "") {{
      statusText.textContent = text;
      statusText.className = "status";
      if (kind) statusText.classList.add(kind);
    }}

    function resetViews() {{
      timeline.innerHTML = "";
      summaryGrid.innerHTML = "";
      citations.innerHTML = "";
      citationsEmpty.style.display = "block";
      briefTrace.innerHTML = "";
      briefTraceEmpty.style.display = "block";
    }}

    function pretty(data) {{
      return JSON.stringify(data, null, 2);
    }}

    function addMetric(key, value) {{
      const box = document.createElement("div");
      box.className = "metric";
      box.innerHTML = `<div class="k">${{key}}</div><div class="v">${{value}}</div>`;
      summaryGrid.appendChild(box);
    }}

    async function sendJson(url, method, body) {{
      const res = await fetch(url, {{
        method,
        headers: {{"Content-Type": "application/json"}},
        body: body ? JSON.stringify(body) : undefined,
      }});
      const data = await res.json();
      if (!res.ok) throw new Error(pretty(data));
      return data;
    }}

    async function getJson(url) {{
      const res = await fetch(url);
      const data = await res.json();
      if (!res.ok) throw new Error(pretty(data));
      return data;
    }}

    function stepCard({{ title, meta, payload, status }}) {{
      const card = document.createElement("div");
      card.className = "step " + (status === "ok" ? "ok" : status === "failed" ? "fail" : "");
      const h4 = document.createElement("h4");
      h4.textContent = title;
      const m = document.createElement("div");
      m.className = "meta";
      m.textContent = meta;
      const pre = document.createElement("pre");
      pre.textContent = pretty(payload);
      card.appendChild(h4);
      card.appendChild(m);
      card.appendChild(pre);
      timeline.appendChild(card);
    }}

    function collectCitations(toolResults) {{
      const rows = [];
      const previous = toolResults?.search_previous_issues?.data?.results;
      if (Array.isArray(previous)) {{
        for (const item of previous) {{
          if (!item || typeof item !== "object") continue;
          rows.push({{
            tool: "search_previous_issues",
            ref: item.ticket || item.doc_id || item.chunk_id || "unknown",
            source: item.source || item.retrieval_mode || "unknown",
            score: item.score ?? item.relevance ?? null,
            snippet: item.summary || "",
            why: item.why_selected || "",
          }});
        }}
      }}

      const incident = toolResults?.search_incident_knowledge?.data?.results;
      if (Array.isArray(incident)) {{
        for (const item of incident) {{
          if (!item || typeof item !== "object") continue;
          rows.push({{
            tool: "search_incident_knowledge",
            ref: item.source_id || item.title || "unknown",
            source: item.source_type || "unknown",
            score: item.score ?? null,
            snippet: item.snippet || "",
            why: item.why_selected || "",
          }});
        }}
      }}
      return rows;
    }}

    function renderCitations(rows) {{
      citations.innerHTML = "";
      if (!rows.length) {{
        citationsEmpty.style.display = "block";
        return;
      }}
      citationsEmpty.style.display = "none";
      for (const row of rows) {{
        const box = document.createElement("article");
        box.className = "citation";
        const score = (typeof row.score === "number") ? row.score.toFixed(4) : "n/a";
        box.innerHTML = `
          <div class="head">
            <span>${{row.tool}}</span>
            <span>ref=${{row.ref}}</span>
            <span>source=${{row.source}}</span>
            <span>score=${{score}}</span>
          </div>
          <p class="snippet">${{row.snippet || "(empty snippet)"}}</p>
          <p class="why">${{row.why || "No selection rationale provided."}}</p>
        `;
        citations.appendChild(box);
      }}
    }}

    function renderBriefTrace(toolResults) {{
      briefTrace.innerHTML = "";
      const brief = toolResults?.build_incident_brief?.data;
      if (!brief || typeof brief !== "object") {{
        briefTraceEmpty.style.display = "block";
        return;
      }}
      briefTraceEmpty.style.display = "none";

      const briefView = {{
        summary: brief.summary || "",
        probable_causes: Array.isArray(brief.probable_causes) ? brief.probable_causes : [],
        recommended_actions: Array.isArray(brief.recommended_actions) ? brief.recommended_actions : [],
        escalation_recommendation: brief.escalation_recommendation || "",
        confidence: brief.confidence ?? null,
        similar_incidents: Array.isArray(brief.similar_incidents) ? brief.similar_incidents : [],
        citations: Array.isArray(brief.citations) ? brief.citations : [],
      }};

      const rawEvidence = {{
        search_incident_knowledge: toolResults?.search_incident_knowledge?.data?.results || [],
        search_previous_issues: toolResults?.search_previous_issues?.data?.results || [],
      }};

      const left = document.createElement("article");
      left.className = "trace-pane";
      left.innerHTML = `<h4>Brief Fields</h4><pre>${{pretty(briefView)}}</pre>`;

      const right = document.createElement("article");
      right.className = "trace-pane";
      right.innerHTML = `<h4>Raw Evidence Inputs</h4><pre>${{pretty(rawEvidence)}}</pre>`;

      briefTrace.appendChild(left);
      briefTrace.appendChild(right);
    }}

    async function renderLatestRun(taskId) {{
      resetViews();
      setStatus("Loading latest run details...");
      const run = await getJson(`/tasks/${{taskId}}/runs/latest`);
      const task = await getJson(`/tasks/${{taskId}}`);

      const plannerMode = task.verification?.runtime?.planner?.effective_mode || "unknown";
      const executorMode = task.verification?.runtime?.executor?.effective_mode || "unknown";
      const passed = task.verification?.passed === true ? "passed" : "failed";

      addMetric("Task Status", task.status || "unknown");
      addMetric("Verification", passed);
      addMetric("Planner/Executor", `${{plannerMode}} / ${{executorMode}}`);

      const plan = Array.isArray(run.plan_json) ? run.plan_json : [];
      const toolResults = (run.tool_results_json && typeof run.tool_results_json === "object")
        ? run.tool_results_json : {{}};
      const citationRows = collectCitations(toolResults);

      stepCard({{
        title: "Plan",
        meta: `steps=${{plan.length}}`,
        payload: plan,
        status: "ok",
      }});

      for (const step of plan) {{
        const tool = step.tool || "unknown";
        const args = step.args || {{}};
        const result = toolResults[tool] || {{}};
        const status = result.status || "missing";
        const stageHint = (tool === "search_previous_issues") ? " (hybrid retrieval: lexical + vector if enabled)" : "";
        stepCard({{
          title: `Tool: ${{tool}}${{stageHint}}`,
          meta: `step_id=${{step.id || "n/a"}} | status=${{status}}`,
          payload: {{
            args,
            result
          }},
          status: status === "ok" ? "ok" : (status === "failed" ? "failed" : ""),
        }});
      }}

      stepCard({{
        title: "Verification",
        meta: "quality gates and retry summary",
        payload: run.verification_json || task.verification || {{}},
        status: task.verification?.passed ? "ok" : "failed",
      }});

      stepCard({{
        title: "Final Output",
        meta: "what the user receives",
        payload: {{ output: run.output || task.output || "" }},
        status: "ok",
      }});

      addMetric("Citations", String(citationRows.length));
      renderCitations(citationRows);
      renderBriefTrace(toolResults);

      setStatus("Run inspection loaded.", "ok");
    }}

    document.getElementById("createBtn").addEventListener("click", async () => {{
      try {{
        resetViews();
        setStatus("Creating task...");
        const task = await sendJson("/tasks", "POST", {{ prompt: promptInput.value.trim() }});
        taskIdInput.value = task.task_id;
        setStatus("Task created. You can run it now.", "ok");
      }} catch (err) {{
        setStatus(String(err.message || err), "error");
      }}
    }});

    document.getElementById("runBtn").addEventListener("click", async () => {{
      try {{
        const taskId = taskIdInput.value.trim();
        if (!taskId) throw new Error("Task ID required.");
        setStatus("Running task...");
        await sendJson(`/tasks/${{taskId}}/run`, "POST");
        await renderLatestRun(taskId);
      }} catch (err) {{
        setStatus(String(err.message || err), "error");
      }}
    }});

    document.getElementById("inspectBtn").addEventListener("click", async () => {{
      try {{
        const taskId = taskIdInput.value.trim();
        if (!taskId) throw new Error("Task ID required.");
        await renderLatestRun(taskId);
      }} catch (err) {{
        setStatus(String(err.message || err), "error");
      }}
    }});

    document.getElementById("clearBtn").addEventListener("click", () => {{
      resetViews();
      setStatus("Cleared.");
    }});
  </script>
</body>
</html>
"""
