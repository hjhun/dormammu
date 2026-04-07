const panels = document.querySelectorAll(".panel");
const tabs = document.querySelectorAll(".tab");
const fileButtons = document.querySelectorAll(".file-button");
const runForm = document.querySelector("#run-form");
const resumeButton = document.querySelector("#resume-button");
const formStatus = document.querySelector("#form-status");
const fileContent = document.querySelector("#file-content");
const filePath = document.querySelector("#file-path");

let activeFile = "dashboard";
let stdoutSource = null;
let stderrSource = null;

function showPanel(panelName) {
  tabs.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.panel === panelName);
  });
  panels.forEach((panel) => {
    panel.classList.toggle("is-active", panel.id === `panel-${panelName}`);
  });
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

function splitLines(value) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function setText(id, value) {
  const node = document.querySelector(id);
  if (node) {
    node.textContent = value ?? "-";
  }
}

async function loadRunSetup() {
  const payload = await fetchJson("/api/runs/setup");
  document.querySelector("#workdir").value = payload.workdir || "";
  document.querySelector("#max-retries").value = payload.default_max_retries ?? 0;
  return payload;
}

function renderSummary(payload) {
  const roadmapFocus =
    payload.workflow.roadmap.active_phase_ids?.join(", ") || "none";
  const taskSync = payload.session.task_sync || {};
  const latestRun = payload.workflow.latest_run || {};
  const supervisor = payload.workflow.supervisor || {};
  const loop = payload.session.loop || {};
  const uiRun = payload.ui_run || {};

  setText("#hero-roadmap", roadmapFocus);
  setText("#hero-action", payload.workflow.next_action || payload.session.next_action);
  setText("#workflow-phase", payload.workflow.active_phase || payload.session.active_phase);
  setText("#loop-status", loop.status || "idle");
  setText("#supervisor-verdict", supervisor.verdict || "not_run");
  setText("#latest-exit-code", latestRun.exit_code ?? "n/a");
  setText("#roadmap-focus", roadmapFocus);
  setText("#next-action", payload.workflow.next_action || payload.session.next_action);
  setText("#next-task", taskSync.next_pending_task || "No pending task");
  setText("#ui-job-status", uiRun.status || "idle");
}

async function refreshSummary() {
  const payload = await fetchJson("/api/state/summary");
  renderSummary(payload);
  return payload;
}

async function loadFile(name) {
  const payload = await fetchJson(`/api/state/files/${name}`);
  filePath.textContent = payload.path;
  fileContent.textContent = payload.exists ? payload.content : "File is not available yet.";
}

function connectLogStream(stream, selector) {
  const target = document.querySelector(selector);
  const source = new EventSource(`/api/state/logs/${stream}/stream?lines=160`);
  source.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    target.textContent = payload.content || "No log output yet.";
  };
  source.onerror = () => {
    target.textContent = "Log stream disconnected. Retrying on the next refresh.";
    source.close();
    setTimeout(() => connectStreams(), 2000);
  };
  return source;
}

function connectStreams() {
  if (stdoutSource) {
    stdoutSource.close();
  }
  if (stderrSource) {
    stderrSource.close();
  }
  stdoutSource = connectLogStream("stdout", "#stdout-log");
  stderrSource = connectLogStream("stderr", "#stderr-log");
}

async function startRun(event) {
  event.preventDefault();
  formStatus.textContent = "Submitting supervised run...";
  try {
    const payload = {
      agent_cli: document.querySelector("#agent-cli").value.trim(),
      workdir: document.querySelector("#workdir").value.trim() || null,
      input_mode: document.querySelector("#input-mode").value,
      run_label: document.querySelector("#run-label").value.trim() || null,
      prompt: document.querySelector("#prompt").value,
      max_retries: Number(document.querySelector("#max-retries").value || "0"),
      extra_args: splitLines(document.querySelector("#extra-args").value),
      required_paths: splitLines(document.querySelector("#required-paths").value),
      require_worktree_changes: document.querySelector("#require-worktree-changes").checked,
    };
    const response = await fetchJson("/api/runs/start", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    formStatus.textContent = `Submitted ${response.job_id}.`;
    showPanel("progress");
    await refreshSummary();
  } catch (error) {
    formStatus.textContent = error.message;
  }
}

async function resumeRun() {
  formStatus.textContent = "Requesting resume...";
  try {
    const response = await fetchJson("/api/runs/resume", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({}),
    });
    formStatus.textContent = `Resume job ${response.job_id} submitted.`;
    showPanel("progress");
    await refreshSummary();
  } catch (error) {
    formStatus.textContent = error.message;
  }
}

tabs.forEach((button) => {
  button.addEventListener("click", () => showPanel(button.dataset.panel));
});

fileButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    activeFile = button.dataset.file;
    fileButtons.forEach((candidate) => {
      candidate.classList.toggle("is-active", candidate === button);
    });
    await loadFile(activeFile);
  });
});

runForm.addEventListener("submit", startRun);
resumeButton.addEventListener("click", resumeRun);

await loadRunSetup();
await refreshSummary();
await loadFile(activeFile);
connectStreams();
setInterval(refreshSummary, 3000);
