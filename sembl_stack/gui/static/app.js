const STAGE_LABEL = { bounds: "bounds", sandbox: "sandbox", loop: "execute", verify: "gate" };
const STAGE_MARK = { running: "…", done: "✓", fail: "✕" };

const el = (id) => document.getElementById(id);

let currentRunId = null;

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function toast(message, isError) {
  const t = document.createElement("div");
  t.className = "toast" + (isError ? " error" : "");
  t.textContent = message;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 5000);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  return res.json();
}

// ---------------------------------------------------------------- status

async function loadStatus() {
  const status = await api("/api/status");
  el("repo-path").textContent = status.repo;
  el("repo-path").title = status.repo;

  const agentEl = el("agent-status");
  if (status.profile) {
    agentEl.innerHTML = `<span class="dot ok"></span> ${status.profile.executor}` +
      (status.profile.model ? ` (${status.profile.model})` : "");
  } else {
    agentEl.innerHTML = `<span class="dot bad"></span> no agent configured`;
  }

  renderAgentList(status.providers, status.profile);

  const layers = status.layers.layers || {};
  const layersList = el("layers-list");
  layersList.innerHTML = "";
  const rows = Object.keys(layers).length
    ? layers
    : { execute: status.profile ? status.profile.executor : "?" };
  for (const [k, v] of Object.entries(rows)) {
    const row = document.createElement("div");
    row.className = "layer-row";
    row.innerHTML = `<span>${escapeHtml(k)}</span><span>${escapeHtml(String(v))}</span>`;
    layersList.appendChild(row);
  }

  if (status.task.text) {
    el("task-text").value = status.task.text;
    el("editable-paths").value = status.task.editable;
    el("forbidden-paths").value = status.task.forbidden;
  }
}

const KEY_ENV_VARS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"];

function renderAgentList(providers, profile) {
  const list = el("agent-list");
  list.innerHTML = "";
  for (const p of providers) {
    const row = document.createElement("button");
    row.className = "run-item agent-item" + (profile && profile.runner === p.runner ? " active" : "");
    row.disabled = !p.ok;
    row.title = p.status;
    row.innerHTML = `${escapeHtml(p.label)}<span class="run-time">${escapeHtml(p.status)}</span>`;
    row.onclick = () => chooseAgent(p);
    list.appendChild(row);
  }
}

async function chooseAgent(provider) {
  const body = { runner: provider.runner };
  if (provider.runner === "api-key") {
    const found = KEY_ENV_VARS.find((v) => provider.status.includes(v));
    if (found) body.key_env = found;
  }
  const result = await api("/api/agent", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!result.ok) { toast(result.hint, true); return; }
  toast(`agent set: ${result.profile.executor}`);
  loadStatus();
}

// ---------------------------------------------------------------- history

async function loadRuns() {
  const runs = await api("/api/runs");
  const list = el("run-list");
  list.innerHTML = "";
  if (!runs.length) {
    list.innerHTML = '<div class="empty-note">no runs yet</div>';
    return;
  }
  for (const run of runs) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.className = "run-item" + (run.id === currentRunId ? " active" : "");
    const verdict = run.verdict || run.status || "?";
    btn.innerHTML =
      `<span class="run-time">${escapeHtml(run.id)}</span>` +
      `<span class="run-verdict ${escapeHtml(verdict)}">${escapeHtml(verdict)}</span> ` +
      `${escapeHtml((run.task || "").slice(0, 40))}`;
    btn.onclick = () => openRun(run.id);
    li.appendChild(btn);
    list.appendChild(li);
  }
}

async function openRun(runId) {
  currentRunId = runId;
  await loadRuns();
  const detail = await api(`/api/runs/${runId}`);
  renderResult(detail);
}

// ---------------------------------------------------------------- task form

el("suggest-editable").onclick = () => suggestPaths("editable");
el("suggest-forbidden").onclick = () => suggestPaths("forbidden");

async function suggestPaths(kind) {
  const btn = kind === "editable" ? el("suggest-editable") : el("suggest-forbidden");
  const text = el("task-text").value.trim();
  if (!text) { toast("describe the task first", true); return; }
  btn.disabled = true;
  btn.textContent = "...";
  try {
    const editable = el("editable-paths").value.split(",").map((s) => s.trim()).filter(Boolean);
    const result = await api("/api/suggest-paths", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, kind, editable }),
    });
    if (result.paths && result.paths.length) {
      const target = kind === "editable" ? el("editable-paths") : el("forbidden-paths");
      target.value = result.paths.join(", ");
    } else {
      toast("no usable AI suggestion — " + (result.reason || "enter paths manually"));
    }
  } finally {
    btn.disabled = false;
    btn.textContent = "Suggest";
  }
}

el("run-button").onclick = runTask;

async function runTask() {
  const text = el("task-text").value.trim();
  const editable = el("editable-paths").value.split(",").map((s) => s.trim()).filter(Boolean);
  const forbidden = el("forbidden-paths").value.split(",").map((s) => s.trim()).filter(Boolean);
  if (!text) { toast("describe the task first", true); return; }
  if (!editable.length) { toast("give the agent at least one editable path", true); return; }

  const saved = await api("/api/task", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, editable, forbidden }),
  });
  if (!saved.ok) { toast(saved.error, true); return; }
  if (saved.warning) toast(saved.warning);

  el("run-button").disabled = true;
  el("timeline").innerHTML = "";
  el("result-body").innerHTML = '<div class="placeholder">running…</div>';
  el("ship-actions").style.display = "none";

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws/run`);
  ws.onmessage = (event) => onRunMessage(JSON.parse(event.data));
  ws.onerror = () => toast("connection to the run stream failed", true);
}

function onRunMessage(msg) {
  if (msg.type === "stage") {
    appendStageRow(msg);
  } else if (msg.type === "done") {
    el("run-button").disabled = false;
    currentRunId = msg.run_id;
    loadRuns();
    openRun(msg.run_id);
  } else if (msg.type === "error") {
    el("run-button").disabled = false;
    toast(msg.message, true);
    el("result-body").innerHTML =
      `<div class="verdict-banner BLOCK"><span class="verdict-status">ERROR</span><div>${escapeHtml(msg.message)}</div></div>`;
  }
}

function appendStageRow(ev) {
  const row = document.createElement("div");
  row.className = `stage-row ${ev.state}`;
  const mark = STAGE_MARK[ev.state] || " ";
  const label = STAGE_LABEL[ev.stage] || ev.stage;
  row.innerHTML =
    `<span class="mark">${mark}</span><span>${escapeHtml(label)}</span>` +
    (ev.detail ? `<span class="detail">${escapeHtml(ev.detail)}</span>` : "");
  el("timeline").appendChild(row);
  el("timeline").scrollTop = el("timeline").scrollHeight;
}

// ---------------------------------------------------------------- result pane

function renderDiff(diff) {
  if (!diff || !diff.trim()) return '<div class="hint">(no changes)</div>';
  const lines = diff.split("\n").map((line) => {
    const escaped = escapeHtml(line);
    if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ") ||
        line.startsWith("@@") || line.startsWith("index ")) {
      return `<span class="meta">${escaped}</span>`;
    }
    if (line.startsWith("+")) return `<span class="add">${escaped}</span>`;
    if (line.startsWith("-")) return `<span class="del">${escaped}</span>`;
    return escaped;
  });
  return `<pre class="diff">${lines.join("\n")}</pre>`;
}

function renderResult(detail) {
  const body = el("result-body");
  let html = "";
  if (detail.verdict) {
    html += `<div class="verdict-banner ${detail.verdict.status}">` +
      `<span class="verdict-status">${escapeHtml(detail.verdict.status)}</span>`;
    if (detail.verdict.reasons && detail.verdict.reasons.length) {
      html += "<ul>" + detail.verdict.reasons.map((r) => `<li>${escapeHtml(r)}</li>`).join("") + "</ul>";
    }
    html += "</div>";
  }
  for (const attempt of detail.attempts || []) {
    html += `<div class="attempt-block"><h3>attempt ${attempt.attempt}` +
      (attempt.status ? ` — ${escapeHtml(attempt.status)}` : "") + `</h3>`;
    html += renderDiff(attempt.diff);
    html += "</div>";
  }
  if (!html) html = '<div class="placeholder">no artifacts for this run</div>';
  body.innerHTML = html;

  const shipActions = el("ship-actions");
  if (detail.verdict && (detail.verdict.status === "PASS" || detail.verdict.status === "WARN")) {
    shipActions.style.display = "flex";
    el("ship-apply").onclick = () => shipRun(detail.id, detail.verdict.status === "WARN");
  } else {
    shipActions.style.display = "none";
  }
}

async function shipRun(runId, allowWarn) {
  const commit = el("ship-commit").checked;
  el("ship-apply").disabled = true;
  try {
    const result = await api("/api/ship", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId, allow_warn: allowWarn, commit }),
    });
    if (!result.ok) { toast(result.error, true); return; }
    toast(`applied: ${result.files}`);
    if (result.commit_error) toast("commit skipped: " + result.commit_error);
  } finally {
    el("ship-apply").disabled = false;
  }
}

loadStatus();
loadRuns();
