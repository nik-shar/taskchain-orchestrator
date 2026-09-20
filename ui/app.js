// TaskChain minimal dashboard controller

const state = {
  owner: "",
  repo: "",
  polling: null,
  lastProgress: null, // { pct, msg } — used for stall detection
  lastChange: 0, // timestamp of last progress change
};

const STALL_TIMEOUT_MS = 45000; // no progress change for 45s → warn

const $ = (sel) => document.querySelector(sel);

function setStatus(message, type = "info") {
  const el = $("#ingestMessage");
  el.textContent = message;
  el.className = `status-message ${type}`;
}

function showProgress(percent, label) {
  $("#ingestProgress").classList.remove("hidden");
  $("#progressFill").style.width = `${percent}%`;
  $("#progressLabel").textContent = label || `${percent}%`;
}

function hideProgress() {
  $("#ingestProgress").classList.add("hidden");
}

function parseRepoId(url) {
  const match = url.match(/github\.com\/([^/]+)\/([^/]+)/);
  if (!match) return null;
  return { owner: match[1], repo: match[2].replace(/\.git$/, "").replace(/\/$/, "") };
}

async function pollStatus(owner, repo) {
  try {
    const res = await fetch(`/repos/${owner}/${repo}/status`);
    const data = await res.json();

    if (data.status === "not_found") {
      setStatus(
        "No ingestion record found — the background task may have crashed on startup. Check the server logs and try again.",
        "error"
      );
      clearInterval(state.polling);
      state.polling = null;
      return;
    }

    showProgress(data.progress_pct || 0, data.status_message || `${data.progress_pct || 0}%`);

    // Stall detection: same progress + message for too long while pending.
    const signature = `${data.progress_pct}|${data.status_message}`;
    const now = Date.now();
    if (!state.lastProgress || state.lastProgress.signature !== signature) {
      state.lastProgress = { signature };
      state.lastChange = now;
    } else if (
      data.status === "pending" &&
      now - state.lastChange > STALL_TIMEOUT_MS
    ) {
      setStatus(
        `Stalled at "${data.status_message}" for over ${STALL_TIMEOUT_MS / 1000}s — check the server logs. Common cause: GitHub API rate limiting (set GITHUB_TOKEN in .env).`,
        "error"
      );
      clearInterval(state.polling);
      state.polling = null;
      return;
    }

    if (data.status === "complete" || data.status === "cached") {
      setStatus(`Ingestion complete: ${data.issue_count} issues, ${data.pr_count} PRs indexed.`, "success");
      hideProgress();
      clearInterval(state.polling);
      state.polling = null;
    } else if (data.status === "failed") {
      setStatus(`Ingestion failed: ${data.status_message}`, "error");
      hideProgress();
      clearInterval(state.polling);
      state.polling = null;
    }
  } catch (err) {
    setStatus(`Status check failed: ${err.message}`, "error");
  }
}

$("#ingestForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = $("#repoUrlInput").value.trim();
  const parsed = parseRepoId(url);
  if (!parsed) {
    setStatus("Invalid GitHub repository URL.", "error");
    return;
  }
  state.owner = parsed.owner;
  state.repo = parsed.repo;

  $("#ingestButton").disabled = true;
  setStatus("Queueing ingestion...", "info");
  showProgress(5, "Queueing...");

  try {
    const res = await fetch("/repos/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_url: url }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Ingestion request failed");

    if (data.status === "cached") {
      setStatus("Repository already indexed (cached).", "success");
      hideProgress();
    } else {
      setStatus("Ingestion started. This may take a minute...", "info");
      state.lastProgress = null;
      state.lastChange = Date.now();
      if (state.polling) clearInterval(state.polling);
      state.polling = setInterval(() => pollStatus(state.owner, state.repo), 2000);
    }
  } catch (err) {
    setStatus(err.message, "error");
    hideProgress();
  } finally {
    $("#ingestButton").disabled = false;
  }
});

// ---- Q&A with live pipeline progress (SSE) ----

const STAGE_LABELS = {
  summary: "Loading repository summary",
  docs: "Injecting documentation context",
  history: "Searching issue & PR history",
  file_selection: "Selecting relevant code files",
  code_read: "Reading code files",
  answering: "Generating answer",
};
const STAGE_ORDER = Object.keys(STAGE_LABELS);

let askTimerInterval = null;

function renderStageList() {
  const container = $("#askPipelineStages");
  container.innerHTML = "";
  for (const stage of STAGE_ORDER) {
    const row = document.createElement("div");
    row.className = "stage pending";
    row.id = `stage-${stage}`;
    row.innerHTML = `
      <span class="stage-icon"></span>
      <span class="stage-label">${STAGE_LABELS[stage]}</span>
      <span class="stage-detail"></span>
    `;
    container.appendChild(row);
  }
}

function setStage(stage, status, detail = "") {
  const row = $(`#stage-${stage}`);
  if (!row) return;
  row.className = `stage ${status}`;
  row.querySelector(".stage-detail").textContent = detail;
}

function startAskTimer() {
  const start = Date.now();
  $("#askTimer").textContent = "0.0s";
  askTimerInterval = setInterval(() => {
    $("#askTimer").textContent = `${((Date.now() - start) / 1000).toFixed(1)}s`;
  }, 100);
}

function stopAskTimer() {
  clearInterval(askTimerInterval);
  askTimerInterval = null;
}

function resetAskPipeline() {
  $("#askPipeline").classList.remove("hidden");
  $("#answerBox").classList.add("hidden");
  renderStageList();
  startAskTimer();
}

function formatStageDetail(stage, event) {
  if (stage === "history" && event.status === "done") {
    return `${event.hits} related item${event.hits === 1 ? "" : "s"}`;
  }
  if (stage === "docs" && event.status === "done") {
    return event.chars > 0 ? `${event.chars.toLocaleString()} chars` : "none found";
  }
  if (stage === "file_selection" && event.status === "done") {
    return event.selected.length
      ? event.selected.join(", ")
      : "no files selected";
  }
  if (stage === "code_read" && event.status === "done") {
    return `${event.files.length} file${event.files.length === 1 ? "" : "s"} read`;
  }
  if (stage === "code_read" && event.status === "skipped") {
    return "no code workspace";
  }
  return "";
}

function renderAnswer(data) {
  const box = $("#answerBox");
  box.classList.remove("hidden");
  const sources = data.sources || {};
  const files = (sources.code_files_read || []).join(", ") || "none";
  const hits = (sources.history || []).length;
  box.innerHTML = `
    <div class="answer-text">${escapeHtml(data.answer)}</div>
    <div class="answer-sources">
      <span class="source-chip">Docs: ${(sources.docs_chars || 0).toLocaleString()} chars</span>
      <span class="source-chip">Code: ${escapeHtml(files)}</span>
      <span class="source-chip">History: ${hits} hit${hits === 1 ? "" : "s"}</span>
    </div>
  `;
}

$("#askForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.owner || !state.repo) {
    alert("Please ingest a repository first.");
    return;
  }
  const question = $("#askInput").value.trim();
  const button = $("#askButton");
  button.disabled = true;
  button.textContent = "Thinking...";
  resetAskPipeline();

  const es = new EventSource(
    `/repos/${state.owner}/${state.repo}/ask/stream?question=${encodeURIComponent(question)}`
  );

  const finish = () => {
    stopAskTimer();
    es.close();
    button.disabled = false;
    button.textContent = "Ask";
  };

  es.onmessage = (msg) => {
    if (msg.data === "[DONE]") {
      finish();
      return;
    }
    let event;
    try {
      event = JSON.parse(msg.data);
    } catch {
      return;
    }
    const { stage, status } = event;

    if (stage === "error") {
      setStage("answering", "error", "failed");
      $("#answerBox").classList.remove("hidden");
      $("#answerBox").textContent = `Error: ${event.detail || "Q&A failed"}`;
      finish();
      return;
    }
    if (stage === "done") {
      renderAnswer(event.result);
      finish();
      return;
    }
    setStage(stage, status, formatStageDetail(stage, event));
  };

  es.onerror = () => {
    $("#answerBox").classList.remove("hidden");
    $("#answerBox").textContent = "Error: connection to the agent was lost.";
    finish();
  };
});

$("#fixForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.owner || !state.repo) {
    alert("Please ingest a repository first.");
    return;
  }
  const issue = $("#fixInput").value.trim();
  const button = $("#fixButton");
  button.disabled = true;
  button.textContent = "Planning...";

  try {
    const res = await fetch(`/repos/${state.owner}/${state.repo}/fix`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ issue_description: issue }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Fix generation failed");

    const box = $("#fixResult");
    box.classList.remove("hidden");
    box.innerHTML = `
      <h3>Summary</h3>
      <pre class="code-block">${escapeHtml(data.summary)}</pre>
      <h3>Plan</h3>
      <pre class="code-block">${escapeHtml(data.plan)}</pre>
      <h3>Proposed Diff</h3>
      <pre class="code-block">${escapeHtml(data.diff)}</pre>
      <h3>Verification</h3>
      <pre class="code-block">${escapeHtml(data.verification.review)}</pre>
    `;
  } catch (err) {
    const box = $("#fixResult");
    box.classList.remove("hidden");
    box.textContent = `Error: ${err.message}`;
  } finally {
    button.disabled = false;
    button.textContent = "Plan & Verify Fix";
  }
});

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
