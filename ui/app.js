// UI Elements
const themeToggle = document.querySelector("#themeToggle");

const ingestionForm = document.querySelector("#ingestionForm");
const repoUrlInput = document.querySelector("#repoUrlInput");
const ingestButton = document.querySelector("#ingestButton");
const repoStatusBadge = document.querySelector("#repoStatusBadge");
const ingestionLogs = document.querySelector("#ingestionLogs");
const progressBarContainer = document.querySelector("#progressBarContainer");
const progressBarLabel = document.querySelector("#progressBarLabel");
const progressBarPercent = document.querySelector("#progressBarPercent");
const progressBarFill = document.querySelector("#progressBarFill");

const profilePanel = document.querySelector("#profilePanel");
const onboardForm = document.querySelector("#onboardForm");
const profileInput = document.querySelector("#profileInput");
const onboardButton = document.querySelector("#onboardButton");

const resultsGrid = document.querySelector("#resultsGrid");
const guideText = document.querySelector("#guideText");
const issuesList = document.querySelector("#issuesList");
const guideStatusBadge = document.querySelector("#guideStatusBadge");

// Tab and Chat UI selectors
const tabIssuesBtn = document.querySelector("#tabIssuesBtn");
const tabChatBtn = document.querySelector("#tabChatBtn");
const tabConsoleBtn = document.querySelector("#tabConsoleBtn");
const tabIssuesContent = document.querySelector("#tabIssuesContent");
const tabChatContent = document.querySelector("#tabChatContent");
const tabConsoleContent = document.querySelector("#tabConsoleContent");
const chatMessageFeed = document.querySelector("#chatMessageFeed");
const chatInputForm = document.querySelector("#chatInputForm");
const chatInputField = document.querySelector("#chatInputField");
const chatSendBtn = document.querySelector("#chatSendBtn");

const onboardingFeedbackSection = document.querySelector("#onboardingFeedbackSection");
const saveOnboardFeedbackButton = document.querySelector("#saveOnboardFeedbackButton");
const feedbackSaveStatus = document.querySelector("#feedbackSaveStatus");

const onboardingTelemetrySection = document.querySelector("#onboardingTelemetrySection");
const queryPillsContainer = document.querySelector("#queryPillsContainer");
const cacheStatusContainer = document.querySelector("#cacheStatusContainer");

// Coding Console selectors
const consoleStatusBadge = document.querySelector("#consoleStatusBadge");
const consoleProgressLabel = document.querySelector("#consoleProgressLabel");
const consoleProgressPercent = document.querySelector("#consoleProgressPercent");
const consoleProgressFill = document.querySelector("#consoleProgressFill");
const consoleTerminal = document.querySelector("#consoleTerminal");
const consolePatchSection = document.querySelector("#consolePatchSection");
const consolePatchCode = document.querySelector("#consolePatchCode");
const btnCopyPatch = document.querySelector("#btnCopyPatch");

// State
let pollingInterval = null;
let consolePollInterval = null;
let currentOwner = "";
let currentRepo = "";
let currentBackgroundHash = "";

// Theme Helpers
function getSystemTheme() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function setTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("taskchain-theme", theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "light";
  setTheme(current === "light" ? "dark" : "light");
}

themeToggle.addEventListener("click", toggleTheme);
const savedTheme = localStorage.getItem("taskchain-theme") || getSystemTheme();
setTheme(savedTheme);

// Markdown Parser Helper
function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function formatInlineMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  return html;
}

function renderMarkdown(markdown) {
  if (!markdown) {
    return "";
  }
  if (window.marked && window.marked.parse) {
    return window.marked.parse(markdown);
  }
  return markdown.replace(/\n/g, "<br>");
}

function applyRichFormatting(element) {
  if (!element) return;

  // 1. Highlight code blocks using Highlight.js
  if (window.hljs) {
    element.querySelectorAll("pre code").forEach((block) => {
      window.hljs.highlightElement(block);
    });
  }

  // 2. Render math equations using KaTeX
  if (window.renderMathInElement) {
    window.renderMathInElement(element, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "$", right: "$", display: false },
        { left: "\\(", right: "\\)", display: false },
        { left: "\\[", right: "\\]", display: true }
      ],
      throwOnError: false
    });
  }
}

// Ingestion Form Handler
ingestionForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const repoUrl = repoUrlInput.value.trim();
  if (!repoUrl) return;

  ingestButton.disabled = true;
  ingestButton.textContent = "Connecting...";
  
  ingestionLogs.textContent = "Parsing repository URL...";
  ingestionLogs.className = "status-note";
  ingestionLogs.classList.remove("hidden");
  
  repoStatusBadge.className = "status-badge is-loading";
  repoStatusBadge.textContent = "Parsing...";
  repoStatusBadge.classList.remove("hidden");

  // Clear and hide telemetry
  const ingestionTelemetry = document.querySelector("#ingestionTelemetry");
  const ingestionTelemetryContent = document.querySelector("#ingestionTelemetryContent");
  if (ingestionTelemetry) ingestionTelemetry.classList.add("hidden");
  if (ingestionTelemetryContent) ingestionTelemetryContent.replaceChildren();

  // Reset and show progress bar
  progressBarFill.style.width = "5%";
  progressBarPercent.textContent = "5%";
  progressBarLabel.textContent = "Parsing repository URL...";
  progressBarContainer.classList.remove("hidden");

  try {
    const res = await fetch("/repos/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_url: repoUrl })
    });
    
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Ingestion request failed.");
    }
    
    const data = await res.json();
    const repoId = data.repo_id;
    const [owner, repo] = repoId.split("/");
    currentOwner = owner;
    currentRepo = repo;
    
    // Start status polling — works for both 'queued' and 'cached' status
    // (cached will immediately resolve to 'complete' on first poll)
    startStatusPolling();
  } catch (error) {
    ingestionLogs.textContent = `Error: ${error.message}`;
    ingestionLogs.className = "status-note is-error";
    ingestButton.disabled = false;
    ingestButton.textContent = "Connect";
    repoStatusBadge.className = "status-badge is-error";
    repoStatusBadge.textContent = "Failed";
  }
});

function startStatusPolling() {
  if (pollingInterval) clearInterval(pollingInterval);
  
  pollStatus(); // Poll immediately once
  pollingInterval = setInterval(pollStatus, 3000);
}

async function pollStatus() {
  try {
    const res = await fetch(`/repos/${currentOwner}/${currentRepo}/status`);
    if (!res.ok) throw new Error("Could not retrieve status");
    
    const data = await res.json();
    
    if (data.status === "not_found") {
      ingestionLogs.textContent = "Preparing database ingestion...";
      repoStatusBadge.textContent = "Queued";
      
      progressBarContainer.classList.remove("hidden");
      progressBarFill.style.width = "5%";
      progressBarPercent.textContent = "5%";
      progressBarLabel.textContent = "Preparing database ingestion...";
    } else if (data.status === "pending") {
      const pct = data.progress_pct || 5;
      const msg = data.status_message || "Ingesting repository...";
      ingestionLogs.textContent = msg;
      repoStatusBadge.textContent = "Indexing";
      repoStatusBadge.className = "status-badge is-loading";
      
      progressBarContainer.classList.remove("hidden");
      progressBarFill.style.width = `${pct}%`;
      progressBarPercent.textContent = `${pct}%`;
      progressBarLabel.textContent = msg;
    } else if (data.status === "complete") {
      clearInterval(pollingInterval);
      
      progressBarContainer.classList.remove("hidden");
      progressBarFill.style.width = "100%";
      progressBarPercent.textContent = "100%";
      progressBarLabel.textContent = "Connected!";
      
      ingestionLogs.textContent = `Successfully connected! Found ${data.issue_count} issues and ${data.pr_count} pull requests.`;
      ingestionLogs.className = "status-note is-success";
      
      repoStatusBadge.textContent = "Active";
      repoStatusBadge.className = "status-badge is-success";
      
      ingestButton.disabled = false;
      ingestButton.textContent = "Connected";

      // Render Ingestion Latency Breakdown
      if (data.latency_info) {
        const latencies = data.latency_info;
        const ingestionTelemetry = document.querySelector("#ingestionTelemetry");
        const ingestionTelemetryContent = document.querySelector("#ingestionTelemetryContent");
        
        if (ingestionTelemetry && ingestionTelemetryContent) {
          ingestionTelemetryContent.replaceChildren();
          
          const items = [
            { key: "fetch_repo", label: "GitHub Fetching" },
            { key: "generate_dna_summary", label: "DNA Summary Generation" },
            { key: "index_fts", label: "SQLite FTS5 Indexing" },
            { key: "index_chroma", label: "Chroma Embedding & Index" }
          ];
          
          items.forEach(item => {
            const val = latencies[item.key];
            if (val !== undefined) {
              const row = document.createElement("div");
              row.style.background = "var(--bg-hover)";
              row.style.padding = "8px 12px";
              row.style.borderRadius = "var(--radius-sm)";
              row.style.border = "1px solid var(--line)";
              row.style.display = "flex";
              row.style.justifyContent = "space-between";
              row.innerHTML = `<strong>${item.label}:</strong> <span>${val.toFixed(2)}s</span>`;
              ingestionTelemetryContent.appendChild(row);
            }
          });
          
          const totalVal = latencies["total_ingestion"];
          if (totalVal !== undefined) {
            const totalRow = document.createElement("div");
            totalRow.style.background = "var(--bg-hover)";
            totalRow.style.padding = "8px 12px";
            totalRow.style.borderRadius = "var(--radius-sm)";
            totalRow.style.border = "1px solid var(--line)";
            totalRow.style.display = "flex";
            totalRow.style.justifyContent = "space-between";
            totalRow.style.gridColumn = "1 / -1";
            totalRow.style.fontWeight = "bold";
            totalRow.style.borderLeft = "4px solid var(--highlight)";
            totalRow.innerHTML = `<strong>Total Ingestion Latency:</strong> <span>${totalVal.toFixed(2)}s</span>`;
            ingestionTelemetryContent.appendChild(totalRow);
          }
          
          ingestionTelemetry.classList.remove("hidden");
        }
      }
      
      setTimeout(() => {
        progressBarContainer.classList.add("hidden");
        // Reveal Step 2 Panel
        profilePanel.classList.remove("hidden");
        profilePanel.scrollIntoView({ behavior: "smooth" });
      }, 1000);
    } else if (data.status === "failed") {
      clearInterval(pollingInterval);
      
      progressBarContainer.classList.add("hidden");
      
      ingestionLogs.textContent = "Repository indexing failed. Please verify the URL and your GitHub token.";
      ingestionLogs.className = "status-note is-error";
      repoStatusBadge.textContent = "Failed";
      repoStatusBadge.className = "status-badge is-error";
      ingestButton.disabled = false;
      ingestButton.textContent = "Connect";
    }
  } catch (error) {
    console.error("Status polling failed", error);
  }
}

// Onboarding Form Handler
onboardForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const background = profileInput.value.trim();
  if (!background) return;

  onboardButton.disabled = true;
  onboardButton.textContent = "Generating...";
  guideStatusBadge.className = "status-badge is-loading";
  guideStatusBadge.textContent = "Thinking";

  // Reset feedback
  feedbackSaveStatus.textContent = "";
  feedbackSaveStatus.className = "inline-status";
  const selectedRating = document.querySelector('input[name="onboard-rating"]:checked');
  if (selectedRating) selectedRating.checked = false;

  try {
    const res = await fetch(`/repos/${currentOwner}/${currentRepo}/onboard`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_background: background })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to generate onboarding guide.");
    }

    const data = await res.json();
    
    // 1. Render Guide
    guideText.innerHTML = renderMarkdown(data.guide);
    applyRichFormatting(guideText);
    guideStatusBadge.textContent = "Complete";
    guideStatusBadge.className = "status-badge is-success";

    // 2. Render Recommended Issues
    issuesList.replaceChildren();
    if (!data.issues || data.issues.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "No matching issues found for your background.";
      issuesList.appendChild(empty);
    } else {
      data.issues.forEach((issue) => {
        const card = document.createElement("div");
        card.className = "feedback-card";
        
        const header = document.createElement("div");
        header.className = "feedback-card-header";
        
        const title = document.createElement("h3");
        title.textContent = `Issue #${issue.number}: ${issue.title}`;
        header.appendChild(title);
        
        const badges = document.createElement("div");
        badges.className = "retriever-badges";
        
        const typeBadge = document.createElement("span");
        typeBadge.className = "retriever-badge";
        typeBadge.textContent = issue.type.toUpperCase();
        badges.appendChild(typeBadge);
        
        const stateBadge = document.createElement("span");
        stateBadge.className = "ticket-pill";
        stateBadge.textContent = issue.state;
        badges.appendChild(stateBadge);
        
        if (issue.is_good_first_issue) {
          const gfiBadge = document.createElement("span");
          gfiBadge.className = "retriever-badge";
          gfiBadge.style.background = "rgba(184, 92, 56, 0.15)";
          gfiBadge.style.color = "var(--highlight)";
          gfiBadge.textContent = "Good First Issue";
          badges.appendChild(gfiBadge);
        }
        
        const desc = document.createElement("p");
        desc.className = "feedback-excerpt";
        desc.textContent = issue.body.length > 250 ? issue.body.slice(0, 250) + "..." : issue.body;
        
        const solveBtn = document.createElement("button");
        solveBtn.className = "solve-issue-btn";
        solveBtn.innerHTML = `🚀 Solve Issue`;
        solveBtn.type = "button";
        solveBtn.addEventListener("click", async () => {
          const sessionId = `${currentOwner}_${currentRepo}_${currentBackgroundHash}`;
          const background = profileInput.value.trim();
          
          solveBtn.disabled = true;
          solveBtn.textContent = "Starting...";
          
          try {
            const res = await fetch(`/repos/${currentOwner}/${currentRepo}/handoff`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                session_id: sessionId,
                selected_issue: issue.number,
                user_background: background
              })
            });
            if (!res.ok) throw new Error("Failed to start handoff");
            
            // Start polling handoff status
            startConsolePolling(sessionId);
            openWorkspace(issue.number);
          } catch (err) {
            alert(`Error: ${err.message}`);
          } finally {
            solveBtn.disabled = false;
            solveBtn.innerHTML = `🚀 Solve Issue`;
          }
        });
        
        card.append(header, badges, desc, solveBtn);
        issuesList.appendChild(card);
      });
    }

    // 3. Render Telemetry
    queryPillsContainer.replaceChildren();
    if (data.trace && data.trace.queries) {
      data.trace.queries.forEach((q) => {
        const pill = document.createElement("span");
        pill.className = "ticket-pill";
        pill.textContent = q;
        queryPillsContainer.appendChild(pill);
      });
    }
    
    cacheStatusContainer.replaceChildren();
    const cacheStatus = document.createElement("span");
    cacheStatus.className = "retriever-badge";
    cacheStatus.textContent = data.trace && data.trace.cached ? "Served from Cache" : "Generated Live";
    cacheStatusContainer.appendChild(cacheStatus);

    // Render Latency Breakdown
    const latencyBreakdownContainer = document.querySelector("#latencyBreakdownContainer");
    if (latencyBreakdownContainer) {
      latencyBreakdownContainer.replaceChildren();
      if (data.trace && data.trace.latency_info) {
        const latencies = data.trace.latency_info;
        
        let total = 0;
        const items = [
          { key: "load_repo_context", label: "Load Repo Context" },
          { key: "build_search_query", label: "Build Search Queries" },
          { key: "hybrid_search_issues", label: "Hybrid Search Issues" },
          { key: "synthesize_guide", label: "Synthesize Guide" },
          { key: "collect_feedback", label: "Collect Feedback" }
        ];
        
        items.forEach(item => {
          const val = latencies[item.key];
          if (val !== undefined) {
            total += val;
            const row = document.createElement("div");
            row.style.background = "var(--bg-hover)";
            row.style.padding = "8px 12px";
            row.style.borderRadius = "var(--radius-sm)";
            row.style.border = "1px solid var(--line)";
            row.style.display = "flex";
            row.style.justifyContent = "space-between";
            row.innerHTML = `<strong>${item.label}:</strong> <span>${val.toFixed(2)}s</span>`;
            latencyBreakdownContainer.appendChild(row);
          }
        });
        
        const totalRow = document.createElement("div");
        totalRow.style.background = "var(--bg-hover)";
        totalRow.style.padding = "8px 12px";
        totalRow.style.borderRadius = "var(--radius-sm)";
        totalRow.style.border = "1px solid var(--line)";
        totalRow.style.display = "flex";
        totalRow.style.justifyContent = "space-between";
        totalRow.style.gridColumn = "1 / -1";
        totalRow.style.fontWeight = "bold";
        totalRow.style.borderLeft = "4px solid var(--highlight)";
        totalRow.innerHTML = `<strong>Total Onboarding Latency:</strong> <span>${total.toFixed(2)}s</span>`;
        latencyBreakdownContainer.appendChild(totalRow);
      }
    }

    // Reveal Panels
    resultsGrid.classList.remove("hidden");
    onboardingFeedbackSection.classList.remove("hidden");
    onboardingTelemetrySection.classList.remove("hidden");
    
    resultsGrid.scrollIntoView({ behavior: "smooth" });
    
    // Hash background for feedback submission
    currentBackgroundHash = await sha256(background);

    // Load persisted chat history for session
    const sessionId = `${currentOwner}_${currentRepo}_${currentBackgroundHash}`;
    loadChatHistory(sessionId);

  } catch (error) {
    guideText.innerHTML = `<p style="color: var(--highlight);">Failed: ${error.message}</p>`;
    guideStatusBadge.textContent = "Error";
    guideStatusBadge.className = "status-badge is-error";
  } finally {
    onboardButton.disabled = false;
    onboardButton.textContent = "Get My Guide";
  }
});

// Feedback Submission Handler
saveOnboardFeedbackButton.addEventListener("click", async () => {
  const selectedRating = document.querySelector('input[name="onboard-rating"]:checked');
  if (!selectedRating) {
    feedbackSaveStatus.textContent = "Please select a rating option.";
    feedbackSaveStatus.className = "inline-status is-error";
    return;
  }

  saveOnboardFeedbackButton.disabled = true;
  feedbackSaveStatus.textContent = "Submitting feedback...";
  feedbackSaveStatus.className = "inline-status";

  try {
    const res = await fetch(`/repos/${currentOwner}/${currentRepo}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rating: parseInt(selectedRating.value),
        background_hash: currentBackgroundHash,
        session_id: "anonymous"
      })
    });

    if (!res.ok) throw new Error("Failed to submit feedback.");

    feedbackSaveStatus.textContent = "Feedback submitted successfully. Thank you!";
    feedbackSaveStatus.className = "inline-status is-success";
  } catch (error) {
    feedbackSaveStatus.textContent = error.message;
    feedbackSaveStatus.className = "inline-status is-error";
    saveOnboardFeedbackButton.disabled = false;
  }
});

// SHA-256 Hash Helper
async function sha256(message) {
  const msgBuffer = new TextEncoder().encode(message);
  const hashBuffer = await crypto.subtle.digest("SHA-256", msgBuffer);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const hashHex = hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
  return hashHex;
}

// Tab Switching Listeners
function switchTab(activeBtn, activeContent) {
  [tabIssuesBtn, tabChatBtn, tabConsoleBtn].forEach(btn => btn?.classList.remove("active"));
  [tabIssuesContent, tabChatContent, tabConsoleContent].forEach(c => c?.classList.add("hidden"));
  
  activeBtn.classList.add("active");
  activeContent.classList.remove("hidden");
}

tabIssuesBtn.addEventListener("click", () => switchTab(tabIssuesBtn, tabIssuesContent));
tabChatBtn.addEventListener("click", () => {
  switchTab(tabChatBtn, tabChatContent);
  chatMessageFeed.scrollTop = chatMessageFeed.scrollHeight;
});
tabConsoleBtn.addEventListener("click", () => {
  switchTab(tabConsoleBtn, tabConsoleContent);
  consoleTerminal.scrollTop = consoleTerminal.scrollHeight;
});

function startConsolePolling(sessionId) {
  if (consolePollInterval) clearInterval(consolePollInterval);
  
  tabConsoleBtn.classList.remove("hidden");
  switchTab(tabConsoleBtn, tabConsoleContent);
  
  document.querySelectorAll("#consoleChecklist .checklist-item").forEach(item => {
    item.className = "checklist-item pending";
  });
  
  consoleTerminal.textContent = "[SYSTEM] Connecting to Docker sandbox environment...\n";
  consolePatchSection.classList.add("hidden");
  
  if (agentModifiedFilesLabel) {
    agentModifiedFilesLabel.textContent = "Modified by Agent: None";
  }
  document.querySelectorAll(".file-tree-item").forEach(el => el.classList.remove("is-modified"));
  
  pollConsoleStatus(sessionId);
  consolePollInterval = setInterval(() => pollConsoleStatus(sessionId), 1500);
}

async function pollConsoleStatus(sessionId) {
  try {
    const res = await fetch(`/repos/${currentOwner}/${currentRepo}/handoff/status?session_id=${sessionId}`);
    if (!res.ok) throw new Error("Failed to get handoff status");
    const data = await res.json();
    
    if (data.status === "not_found") {
      return;
    }
    
    consoleProgressPercent.textContent = `${data.progress_pct}%`;
    consoleProgressFill.style.width = `${data.progress_pct}%`;
    
    consoleStatusBadge.textContent = data.status.toUpperCase().replace(/_/g, " ");
    consoleStatusBadge.className = "status-badge";
    if (data.status === "completed") {
      consoleStatusBadge.classList.add("is-success");
    } else if (data.status === "failed") {
      consoleStatusBadge.classList.add("is-error");
    } else {
      consoleStatusBadge.classList.add("is-loading");
    }
    
    if (data.status === "pending") {
      consoleProgressLabel.textContent = "Handoff initiated...";
    } else if (data.status === "environment_setup") {
      consoleProgressLabel.textContent = "Setting up Docker sandbox...";
    } else if (data.status === "coding") {
      consoleProgressLabel.textContent = "Analyzing issue and writing code...";
    } else if (data.status === "verification") {
      consoleProgressLabel.textContent = "Running unit tests inside container...";
    } else if (data.status === "completed") {
      consoleProgressLabel.textContent = "Completed! Git patch successfully created.";
    } else if (data.status === "failed") {
      consoleProgressLabel.textContent = "Task execution failed.";
    }
    
    const setupItem = document.querySelector("#chk-setup");
    const codingItem = document.querySelector("#chk-coding");
    const verifyItem = document.querySelector("#chk-verification");
    const compItem = document.querySelector("#chk-completed");
    
    [setupItem, codingItem, verifyItem, compItem].forEach(item => item.className = "checklist-item pending");
    
    if (data.status === "environment_setup") {
      setupItem.className = "checklist-item active";
    } else if (data.status === "coding") {
      setupItem.className = "checklist-item completed";
      codingItem.className = "checklist-item active";
    } else if (data.status === "verification") {
      setupItem.className = "checklist-item completed";
      codingItem.className = "checklist-item completed";
      verifyItem.className = "checklist-item active";
    } else if (data.status === "completed") {
      setupItem.className = "checklist-item completed";
      codingItem.className = "checklist-item completed";
      verifyItem.className = "checklist-item completed";
      compItem.className = "checklist-item completed";
    } else if (data.status === "failed") {
      // mark active item as failed or just leave it
    }
    
    if (data.logs) {
      consoleTerminal.textContent = data.logs;
      consoleTerminal.scrollTop = consoleTerminal.scrollHeight;
    }
    
    // Parse and decorate modified files
    const modifiedFiles = [];
    if (data.patch_diff) {
      consolePatchCode.textContent = data.patch_diff;
      consolePatchSection.classList.remove("hidden");
      applyRichFormatting(consolePatchSection);
      
      const lines = data.patch_diff.split("\n");
      lines.forEach(line => {
        if (line.startsWith("+++ b/")) {
          const filePath = line.substring(6).trim();
          if (filePath && !modifiedFiles.includes(filePath)) {
            modifiedFiles.push(filePath);
          }
        }
      });
    }
    
    // Update modified files badge/label
    if (agentModifiedFilesLabel) {
      if (modifiedFiles.length > 0) {
        agentModifiedFilesLabel.textContent = "Modified by Agent: " + modifiedFiles.join(", ");
      } else {
        agentModifiedFilesLabel.textContent = "Modified by Agent: None";
      }
    }
    
    // Decorate file tree nodes
    document.querySelectorAll(".file-tree-item").forEach(el => el.classList.remove("is-modified"));
    modifiedFiles.forEach(filePath => {
      const nodeEl = document.querySelector(`.file-tree-item[data-path="${filePath}"]`);
      if (nodeEl) {
        nodeEl.classList.add("is-modified");
      }
    });
    
    if (data.status === "completed" || data.status === "failed") {
      clearInterval(consolePollInterval);
      consolePollInterval = null;
    }
  } catch (error) {
    console.error("Error polling handoff status", error);
  }
}

// Copy Patch Diff Event
btnCopyPatch.addEventListener("click", () => {
  navigator.clipboard.writeText(consolePatchCode.textContent);
  btnCopyPatch.textContent = "Copied!";
  setTimeout(() => {
    btnCopyPatch.textContent = "Copy Diff";
  }, 2000);
});

// Chat Integration
async function loadChatHistory(sessionId) {
  try {
    const res = await fetch(`/repos/${currentOwner}/${currentRepo}/chat/history?session_id=${sessionId}`);
    if (!res.ok) throw new Error("Failed to load chat history");
    const history = await res.json();
    
    // Clear feed and restore welcome bubble
    chatMessageFeed.replaceChildren();
    const welcome = document.createElement("div");
    welcome.className = "chat-bubble assistant";
    welcome.innerHTML = `<p>Welcome! I'm your onboarding mentor. Feel free to ask me follow-up questions about the guide, setup commands, files, or recommended issues.</p>`;
    chatMessageFeed.appendChild(welcome);
    
    history.forEach(msg => {
      appendChatBubble(msg.role, msg.content);
    });
    chatMessageFeed.scrollTop = chatMessageFeed.scrollHeight;
  } catch (error) {
    console.error("Error loading history", error);
  }
}

function appendChatBubble(role, content) {
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;
  
  if (role === "assistant") {
    bubble.innerHTML = renderMarkdown(content);
    applyRichFormatting(bubble);
  } else {
    const p = document.createElement("p");
    p.textContent = content;
    bubble.appendChild(p);
  }
  
  chatMessageFeed.appendChild(bubble);
}

chatInputForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = chatInputField.value.trim();
  if (!message) return;
  
  chatInputField.value = "";
  chatSendBtn.disabled = true;
  
  appendChatBubble("user", message);
  chatMessageFeed.scrollTop = chatMessageFeed.scrollHeight;
  
  // Append typing indicator bubble
  const typingBubble = document.createElement("div");
  typingBubble.className = "chat-bubble assistant typing";
  typingBubble.id = "chatTypingIndicator";
  typingBubble.innerHTML = `
    <span>Thinking</span>
    <div class="typing-dots">
      <span></span>
      <span></span>
      <span></span>
    </div>
  `;
  chatMessageFeed.appendChild(typingBubble);
  chatMessageFeed.scrollTop = chatMessageFeed.scrollHeight;
  
  const sessionId = `${currentOwner}_${currentRepo}_${currentBackgroundHash}`;
  const background = profileInput.value.trim();
  
  try {
    const res = await fetch(`/repos/${currentOwner}/${currentRepo}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        user_background: background,
        message: message
      })
    });
    
    const indicator = document.querySelector("#chatTypingIndicator");
    if (indicator) indicator.remove();
    
    if (!res.ok) {
      throw new Error("Agent failed to respond.");
    }
    
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let statusBubble = null;
    let streamingBubble = null;
    let streamedContent = "";
    
    function updateAgentStatus(statusText) {
      if (!statusBubble) {
        statusBubble = document.createElement("div");
        statusBubble.className = "chat-bubble assistant typing";
        statusBubble.style.opacity = "0.85";
        statusBubble.style.fontSize = "0.9rem";
        chatMessageFeed.appendChild(statusBubble);
      }
      statusBubble.innerHTML = `
        <span>${statusText}</span>
        <div class="typing-dots">
          <span></span>
          <span></span>
          <span></span>
        </div>
      `;
      chatMessageFeed.scrollTop = chatMessageFeed.scrollHeight;
    }
    
    function removeAgentStatus() {
      if (statusBubble) {
        statusBubble.remove();
        statusBubble = null;
      }
    }

    function ensureStreamingBubble() {
      if (!streamingBubble) {
        removeAgentStatus();
        streamingBubble = document.createElement("div");
        streamingBubble.className = "chat-bubble assistant";
        streamingBubble.innerHTML = "";
        chatMessageFeed.appendChild(streamingBubble);
      }
    }

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop();
      
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const event = JSON.parse(line.substring(6));
            if (event.type === "thought") {
              if (event.content) {
                const toolNames = event.tool_calls.map(tc => tc.name.replace(/_/g, " ")).join(", ");
                updateAgentStatus(`Investigating (${toolNames})...`);
              }
            } else if (event.type === "tool_start") {
              const names = event.calls.map(c => c.name.replace(/_/g, " ")).join(" & ");
              updateAgentStatus(`Running tools in parallel: ${names}...`);
            } else if (event.type === "tool_end") {
              updateAgentStatus("Processing tool results...");
            } else if (event.type === "token") {
              // Token-by-token streaming — append to streaming bubble
              ensureStreamingBubble();
              streamedContent += event.content;
              // Render incrementally as plain text for speed, rich format at end
              streamingBubble.textContent = streamedContent;
              chatMessageFeed.scrollTop = chatMessageFeed.scrollHeight;
            } else if (event.type === "final_answer") {
              removeAgentStatus();
              if (streamingBubble) {
                // We were streaming — finalize with rich rendering
                streamingBubble.innerHTML = renderMarkdown(streamedContent || event.content);
                applyRichFormatting(streamingBubble);
                streamingBubble = null;
                streamedContent = "";
              } else {
                // Non-streamed final answer (e.g. tool rounds with buffered output)
                appendChatBubble("assistant", event.content);
              }
            } else if (event.type === "handoff_triggered") {
              removeAgentStatus();
              const sessionId = `${currentOwner}_${currentRepo}_${currentBackgroundHash}`;
              startConsolePolling(sessionId);
              openWorkspace(event.selected_issue);
            } else if (event.type === "error") {
              removeAgentStatus();
              appendChatBubble("assistant", `Error: ${event.content}`);
            }
          } catch (jsonErr) {
            console.error("Error parsing stream event", jsonErr);
          }
        }
      }
    }
    // Finalize any leftover streaming bubble
    if (streamingBubble && streamedContent) {
      streamingBubble.innerHTML = renderMarkdown(streamedContent);
      applyRichFormatting(streamingBubble);
      streamingBubble = null;
      streamedContent = "";
    }
    removeAgentStatus();
  } catch (error) {
    const indicator = document.querySelector("#chatTypingIndicator");
    if (indicator) indicator.remove();
    appendChatBubble("assistant", `Error: ${error.message}`);
  } finally {
    chatSendBtn.disabled = false;
    chatMessageFeed.scrollTop = chatMessageFeed.scrollHeight;
  }
});


// Workspace Selectors
const workspacePanel = document.querySelector("#workspacePanel");
const workspaceIssueHeader = document.querySelector("#workspaceIssueHeader");
const workspaceTitle = document.querySelector("#workspaceTitle");
const btnWorkspaceAnalyze = document.querySelector("#btnWorkspaceAnalyze");
const btnWorkspaceSolve = document.querySelector("#btnWorkspaceSolve");
const btnWorkspaceTest = document.querySelector("#btnWorkspaceTest");
const btnWorkspaceSave = document.querySelector("#btnWorkspaceSave");
const btnWorkspaceClose = document.querySelector("#btnWorkspaceClose");
const fileTreeRoot = document.querySelector("#fileTreeRoot");
const activeFileLabel = document.querySelector("#activeFileLabel");
const editorTabBar = document.querySelector("#editorTabBar");
const steeringInput = document.querySelector("#steeringInput");
const agentModifiedFilesLabel = document.querySelector("#agentModifiedFilesLabel");

let monacoEditor = null;
let activeFilePath = null;

function initMonacoEditor() {
  if (window.editor) return;
  
  require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.39.0/min/vs' } });
  require(['vs/editor/editor.main'], function () {
    const currentTheme = document.documentElement.getAttribute("data-theme") === "dark" ? "vs-dark" : "vs";
    
    monacoEditor = monaco.editor.create(document.getElementById('monacoEditorContainer'), {
      value: '# Select a file to view or edit code\n',
      language: 'python',
      theme: currentTheme,
      automaticLayout: true,
      fontSize: 13,
      minimap: { enabled: false }
    });
    
    // Ctrl+S shortcut inside Monaco
    monacoEditor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, function() {
      saveActiveFile();
    });
    
    window.editor = monacoEditor;
  });
}

// Open Workspace
function openWorkspace(issueNumber = null) {
  workspacePanel.classList.remove("hidden");
  workspacePanel.scrollIntoView({ behavior: "smooth" });
  
  if (issueNumber) {
    workspaceIssueHeader.textContent = `Sandbox Environment — Solving Issue #${issueNumber}`;
  } else {
    workspaceIssueHeader.textContent = "Sandbox Environment";
  }
  
  initMonacoEditor();
  loadFileTree();
}

// Close Workspace
btnWorkspaceClose.addEventListener("click", () => {
  workspacePanel.classList.add("hidden");
});

// Load File Tree
async function loadFileTree() {
  fileTreeRoot.innerHTML = "<p style='color: var(--muted); font-style: italic;'>Loading file tree...</p>";
  
  try {
    const res = await fetch(`/repos/${currentOwner}/${currentRepo}/files/tree`);
    if (!res.ok) throw new Error("Failed to load file tree.");
    const treeData = await res.json();
    
    fileTreeRoot.replaceChildren();
    if (treeData.length === 0) {
      fileTreeRoot.innerHTML = "<p style='color: var(--muted);'>No files found.</p>";
      return;
    }
    
    const treeDom = renderFileTreeBranch(treeData);
    fileTreeRoot.appendChild(treeDom);
  } catch (err) {
    fileTreeRoot.innerHTML = `<p style='color: var(--highlight);'>Error loading files: ${err.message}</p>`;
  }
}

function renderFileTreeBranch(nodes) {
  const ul = document.createElement("ul");
  ul.style.listStyle = "none";
  ul.style.padding = "0";
  ul.style.margin = "0";
  
  nodes.forEach(node => {
    const li = document.createElement("li");
    li.style.margin = "2px 0";
    
    const item = document.createElement("div");
    item.className = "file-tree-item";
    item.dataset.path = node.path;
    
    const icon = document.createElement("span");
    icon.className = node.type === "directory" ? "icon-folder" : "icon-file";
    icon.style.marginRight = "6px";
    
    const label = document.createElement("span");
    label.textContent = node.name;
    
    item.append(icon, label);
    li.appendChild(item);
    
    if (node.type === "directory") {
      const childrenContainer = document.createElement("div");
      childrenContainer.className = "file-tree-indent hidden";
      
      if (node.children && node.children.length > 0) {
        childrenContainer.appendChild(renderFileTreeBranch(node.children));
      } else {
        const empty = document.createElement("div");
        empty.style.color = "var(--muted)";
        empty.style.fontStyle = "italic";
        empty.style.paddingLeft = "8px";
        empty.style.fontSize = "0.75rem";
        empty.textContent = "empty folder";
        childrenContainer.appendChild(empty);
      }
      
      li.appendChild(childrenContainer);
      
      item.addEventListener("click", (e) => {
        e.stopPropagation();
        const isExpanded = !childrenContainer.classList.contains("hidden");
        if (isExpanded) {
          childrenContainer.classList.add("hidden");
          icon.className = "icon-folder";
        } else {
          childrenContainer.classList.remove("hidden");
          icon.className = "icon-folder-open";
        }
      });
    } else {
      item.addEventListener("click", (e) => {
        e.stopPropagation();
        document.querySelectorAll(".file-tree-item").forEach(el => el.classList.remove("active"));
        item.classList.add("active");
        
        loadFileContent(node.path);
      });
    }
    
    ul.appendChild(li);
  });
  
  return ul;
}

// Load File Content
async function loadFileContent(filePath) {
  activeFileLabel.textContent = "Loading " + filePath + "...";
  try {
    const res = await fetch(`/repos/${currentOwner}/${currentRepo}/files/content?path=${encodeURIComponent(filePath)}`);
    if (!res.ok) throw new Error("Failed to read file.");
    const data = await res.json();
    
    activeFilePath = filePath;
    activeFileLabel.textContent = filePath;
    
    if (window.editor) {
      window.editor.setValue(data.content);
      
      const ext = filePath.split('.').pop().toLowerCase();
      let language = "plaintext";
      if (ext === "py") language = "python";
      else if (ext === "js" || ext === "jsx") language = "javascript";
      else if (ext === "ts" || ext === "tsx") language = "typescript";
      else if (ext === "html") language = "html";
      else if (ext === "css") language = "css";
      else if (ext === "json") language = "json";
      else if (ext === "md") language = "markdown";
      else if (ext === "yml" || ext === "yaml") language = "yaml";
      else if (ext === "sh") language = "shell";
      
      const model = window.editor.getModel();
      if (model && window.monaco) {
        window.monaco.editor.setModelLanguage(model, language);
      }
    }
  } catch (err) {
    activeFileLabel.textContent = "Error: " + err.message;
  }
}

// Save File
async function saveActiveFile() {
  if (!activeFilePath || !window.editor) return;
  
  const content = window.editor.getValue();
  editorSaveStatus.textContent = "Saving...";
  editorSaveStatus.style.opacity = 1;
  
  try {
    const res = await fetch(`/repos/${currentOwner}/${currentRepo}/files/content`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path: activeFilePath,
        content: content
      })
    });
    if (!res.ok) throw new Error("Failed to save file.");
    
    editorSaveStatus.textContent = "Saved";
    setTimeout(() => {
      if (editorSaveStatus.textContent === "Saved") {
        editorSaveStatus.style.opacity = 0;
      }
    }, 2000);
    
    // Refresh file tree in case folders were created
    loadFileTree();
  } catch (err) {
    editorSaveStatus.textContent = "Error: " + err.message;
  }
}

btnWorkspaceSave.addEventListener("click", saveActiveFile);

// Trigger Commands on Sandbox
async function triggerSandboxCommand(command) {
  const sessionId = `${currentOwner}_${currentRepo}_${currentBackgroundHash}`;
  
  // Start polling console logs
  startConsolePolling(sessionId);
  
  try {
    const res = await fetch(`/repos/${currentOwner}/${currentRepo}/sandbox/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        command: command
      })
    });
    if (!res.ok) throw new Error("Failed to execute command.");
  } catch (err) {
    console.error("Error executing sandbox command", err);
  }
}

btnWorkspaceAnalyze.addEventListener("click", () => {
  triggerSandboxCommand("git status");
});

btnWorkspaceTest.addEventListener("click", () => {
  triggerSandboxCommand("pytest tests/ || python -m unittest discover tests/ || echo 'No tests found.'");
});

// Trigger Agent Solve in Workspace
btnWorkspaceSolve.addEventListener("click", async () => {
  const sessionId = `${currentOwner}_${currentRepo}_${currentBackgroundHash}`;
  const background = profileInput.value.trim();
  const steering = steeringInput ? steeringInput.value.trim() : "";
  
  startConsolePolling(sessionId);
  
  try {
    const res = await fetch(`/repos/${currentOwner}/${currentRepo}/handoff`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        selected_issue: 0,
        user_background: background,
        steering_instructions: steering || null
      })
    });
    if (!res.ok) throw new Error("Failed to trigger agent.");
  } catch (err) {
    console.error("Error triggering solve agent", err);
  }
});

