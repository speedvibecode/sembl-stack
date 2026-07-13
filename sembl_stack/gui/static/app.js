"use strict";

/*
 * sembl cockpit — frontend (SPEC-demo-shell.md WP-B).
 *
 * Vanilla ES2020, no framework, no build step, no requests beyond this app's
 * own API. Every line rendered in the conversation view comes from a real
 * API response — nothing here fabricates assistant prose (D4). A BLOCK
 * verdict renders its reasons and stops; there is no apply/merge/override
 * control anywhere on this surface (D5).
 */

// ---------------------------------------------------------------- constants

const STAGE_LABEL = {
  bounds: "planning bounds",
  sandbox: "opening a disposable sandbox",
  loop: "executor writing",
  verify: "the gate is judging",
};

const VERDICT_LINE = {
  PASS: "Passed the gate",
  WARN: "Warned by the gate",
  BLOCK: "Blocked by the gate",
};

const STATUS_LINE = {
  PASS: "completed",
  WARN: "completed with warnings",
  BLOCK: "blocked",
  started: "running",
  running: "running",
};

// ---------------------------------------------------------------------- dom

const el = (id) => document.getElementById(id);

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function toast(message, isError) {
  const t = document.createElement("div");
  t.style.position = "fixed";
  t.style.bottom = "22px";
  t.style.right = "22px";
  t.style.zIndex = "1000";
  t.style.maxWidth = "360px";
  t.style.padding = "10px 14px";
  t.style.borderRadius = "8px";
  t.style.fontSize = "12.5px";
  t.style.background = "var(--surface)";
  t.style.border = "1px solid " + (isError ? "var(--block)" : "var(--border)");
  t.style.color = "var(--text)";
  t.style.boxShadow = "0 8px 24px rgba(0,0,0,0.2)";
  t.textContent = message;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 5000);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  return res.json();
}

function formatTime(ts) {
  if (!ts && ts !== 0) return null;
  try {
    const d = new Date(ts * 1000);
    let h = d.getHours();
    const m = d.getMinutes();
    const ampm = h >= 12 ? "pm" : "am";
    h = h % 12;
    if (h === 0) h = 12;
    const mm = String(m).padStart(2, "0");
    return `${h}:${mm} ${ampm}`;
  } catch {
    return null;
  }
}

function splitCsv(s) {
  return (s || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

// ---------------------------------------------------------------------- state

let allRuns = [];            // last /api/runs response
let currentDetail = null;    // last /api/runs/{id} response, when viewing a historical run
let selectedRunId = null;    // historical run id being viewed (null while viewingLive)
let viewingLive = false;     // true => thread shows the pending/live composer flow

let pendingComposer = null;  // { taskText, editableStr, forbiddenStr } — unconfirmed draft
let liveRun = null;          // { taskText, lines: [], errorMessage, finished } — after confirm

let ws = null;
let eventsCursor = 0;
let eventsTimer = null;
let liveRunId = null;        // adopted run_id for the in-flight run
let liveStageUrl = null;
let liveStageAttempt = null;
let lastFrameSrc = null;     // tracks what we last pointed #preview-frame at (relative or absolute)

// ------------------------------------------------------------------ status

async function loadStatus() {
  try {
    const status = await api("/api/status");
    const repo = status.repo || "";
    const base = repo.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || repo;
    el("repo-name").textContent = base || "—";
    el("repo-name").title = repo;
    return status;
  } catch {
    el("repo-name").textContent = "—";
    return { task: {} };
  }
}

// -------------------------------------------------------------------- runs

async function loadRuns() {
  try {
    allRuns = await api("/api/runs");
  } catch {
    allRuns = [];
  }
  renderSidebar();
}

function dotClassFor(run) {
  const verdict = run.verdict;
  const status = run.status;
  if (verdict === "PASS" || status === "PASS") return "pass";
  if (verdict === "BLOCK" || status === "BLOCK" || status === "failed") return "block";
  if (status === "started" || status === "running") return "running";
  return "";
}

function renderSidebar() {
  const list = el("run-list");
  list.innerHTML = "";

  const wsLive = liveRun && liveRun.confirmed && !liveRun.finished;

  if (wsLive) {
    const row = document.createElement("div");
    row.className = "run-row" + (viewingLive ? " active" : "");
    row.innerHTML =
      `<span class="dot running"></span>` +
      `<div><div class="t">(new run)</div><div class="m">running</div></div>`;
    row.onclick = () => selectLive();
    list.appendChild(row);
  }

  if (!allRuns.length && !wsLive) {
    list.innerHTML =
      '<div class="empty-note">No runs yet &mdash; describe a task below to start the first one.</div>';
    return;
  }

  for (const run of allRuns) {
    const row = document.createElement("div");
    row.className = "run-row" + (!viewingLive && run.id === selectedRunId ? " active" : "");
    const dot = dotClassFor(run);
    const title = (run.task || "").slice(0, 60) || "(no task text)";
    const model = run.executor
      ? run.executor + (run.model ? ` (${run.model})` : "")
      : (run.model || "unknown model");
    const attempts = run.attempts || 0;
    const verdictOrStatus = run.verdict || run.status || "?";
    const time = formatTime(run.created);
    const meta =
      `${model} · ${attempts} attempt${attempts === 1 ? "" : "s"} · ${verdictOrStatus}` +
      (time ? ` · ${time}` : "");
    row.innerHTML =
      `<span class="dot ${dot}"></span>` +
      `<div><div class="t">${escapeHtml(title)}</div><div class="m">${escapeHtml(meta)}</div></div>`;
    row.onclick = () => selectRun(run.id);
    list.appendChild(row);
  }
}

// --------------------------------------------------------------- selection

function parseHash() {
  const m = /^#run=(.+)$/.exec(location.hash || "");
  return m ? decodeURIComponent(m[1]) : null;
}

function selectLive() {
  viewingLive = true;
  selectedRunId = null;
  renderSidebar();
  renderThread();
  renderPreview();
}

async function selectRun(id, opts) {
  const updateHash = !opts || opts.updateHash !== false;
  viewingLive = false;
  selectedRunId = id;
  pendingComposer = null;
  if (updateHash) location.hash = `run=${encodeURIComponent(id)}`;
  renderSidebar();
  currentDetail = null;
  renderThread();
  renderPreview();
  try {
    currentDetail = await api(`/api/runs/${encodeURIComponent(id)}`);
  } catch {
    currentDetail = { id, error: "could not load this run" };
  }
  if (selectedRunId !== id) return; // navigated away while the fetch was in flight
  renderThread();
  renderPreview();
}

// ---------------------------------------------------------------- thread

function renderThread() {
  const thread = el("thread");
  if (viewingLive && liveRun) {
    thread.innerHTML = renderLiveThreadHtml();
    thread.scrollTop = thread.scrollHeight;
    return;
  }
  if (selectedRunId) {
    if (!currentDetail) {
      thread.innerHTML = '<div class="thread-empty">loading&hellip;</div>';
    } else if (currentDetail.error && !currentDetail.task) {
      thread.innerHTML = `<div class="thread-empty">${escapeHtml(currentDetail.error)}</div>`;
    } else {
      thread.innerHTML = renderHistoricalThreadHtml(currentDetail);
    }
    return;
  }
  thread.innerHTML =
    '<div class="thread-empty">Describe a change below to start the first run.</div>';
}

function boundsRow(label, items) {
  const v =
    items && items.length
      ? items.map((p) => `<code>${escapeHtml(p)}</code>`).join(" · ")
      : '<span class="v faint">&mdash;</span>';
  return `<div class="row"><span class="k">${label}</span><span class="v">${v}</span></div>`;
}

function renderTaskCardStatic(detail) {
  const bounds = detail.bounds || null;
  const editable = bounds ? bounds.editable_paths : null;
  const forbidden = bounds ? bounds.forbidden_areas : null;
  const descriptions = detail.acceptance_descriptions || {};
  const mustPassValues = Object.values(descriptions).filter(Boolean);

  let html = '<div class="card">';
  html += `<div class="row"><span class="k">Task</span><span class="v">${escapeHtml(
    (detail.task && detail.task.text) || ""
  )}</span></div>`;
  html += boundsRow("Can edit", editable);
  html += boundsRow("Can&#39;t touch", forbidden);
  if (mustPassValues.length) {
    html += `<div class="row"><span class="k">Must pass</span><span class="v">${mustPassValues
      .map((d) => escapeHtml(d))
      .join(" · ")}</span></div>`;
  }
  html += "</div>";
  return html;
}

function describeCheck(detail, check) {
  const descriptions = detail.acceptance_descriptions || {};
  return descriptions[check.id] || check.id;
}

function renderAttemptHtml(attempt, detail) {
  const runId = detail.id;
  let html = `<div class="m-wrap">`;
  html += `<div class="quiet-line">attempt ${attempt.attempt} · ${escapeHtml(runId)}</div>`;

  if (attempt.status) {
    const statusClass =
      attempt.status === "PASS" ? "status-pass" : attempt.status === "BLOCK" ? "status-block" : "status-warn";
    const dotClass = attempt.status === "PASS" ? "pass" : attempt.status === "BLOCK" ? "block" : "warn";
    const line = VERDICT_LINE[attempt.status] || attempt.status;
    html += `<div class="verdict ${statusClass}">`;
    html += `<div class="line"><span class="dot ${dotClass}"></span>${escapeHtml(line)}</div>`;

    if (attempt.acceptance && attempt.acceptance.length) {
      html += '<div class="checks">';
      for (const check of attempt.acceptance) {
        const ok = check.outcome === "PASS";
        const mark = ok ? '<span class="ok">✓</span>' : '<span class="bad">✗</span>';
        const label = escapeHtml(describeCheck(detail, check));
        const dur =
          typeof check.duration_s === "number"
            ? `<span class="meta">${check.duration_s.toFixed(1)}s</span>`
            : "";
        html += `<div class="c">${mark} ${label} ${dur}</div>`;
      }
      html += "</div>";
    }

    if (attempt.status === "BLOCK" && attempt.reasons && attempt.reasons.length) {
      html += `<div class="why">${escapeHtml(attempt.reasons.join("\n"))}</div>`;
    }
    html += "</div>";
  }

  html += "</div>";
  return html;
}

function finalStatusLineText(detail) {
  const status = detail.status;
  if (status === "failed") {
    const first = ((detail.error || "").split("\n")[0] || "unknown error").trim();
    return `failed · ${first || "unknown error"}`;
  }
  return STATUS_LINE[status] || status || "unknown status";
}

function renderHistoricalThreadHtml(detail) {
  let html = "";
  const taskText = (detail.task && detail.task.text) || "";
  if (taskText) {
    html += `<div class="m-wrap user"><span class="u-msg">${escapeHtml(taskText)}</span></div>`;
  }
  html += `<div class="m-wrap">${renderTaskCardStatic(detail)}</div>`;

  for (const attempt of detail.attempts || []) {
    html += renderAttemptHtml(attempt, detail);
  }

  html += `<div class="m-wrap"><div class="quiet-line">${escapeHtml(
    finalStatusLineText(detail)
  )}</div></div>`;
  return html;
}

// ------------------------------------------------------------- pending card

function renderPendingCardHtml() {
  const editable = escapeHtml(pendingComposer.editableStr || "");
  const forbidden = escapeHtml(pendingComposer.forbiddenStr || "");
  return (
    '<div class="card" id="pending-card">' +
    `<div class="row"><span class="k">Task</span><span class="v">${escapeHtml(
      pendingComposer.taskText
    )}</span></div>` +
    `<div class="row bounds-edit"><span class="k">Can edit</span><span class="v">` +
    `<input class="bounds-input" id="pending-editable" type="text" value="${editable}" placeholder="app/, src/lib" /></span></div>` +
    `<div class="row bounds-edit"><span class="k">Can&#39;t touch</span><span class="v">` +
    `<input class="bounds-input" id="pending-forbidden" type="text" value="${forbidden}" placeholder="infra/, .env" /></span></div>` +
    '<div class="actions">' +
    '<button class="tbtn primary" id="pending-confirm" type="button">Confirm and run</button>' +
    '<button class="tbtn" id="pending-cancel" type="button">Cancel</button>' +
    "</div>" +
    "</div>"
  );
}

function renderLiveThreadHtml() {
  let html = `<div class="m-wrap user"><span class="u-msg">${escapeHtml(liveRun.taskText)}</span></div>`;
  html += '<div class="m-wrap">';
  if (pendingComposer && !liveRun.confirmed) {
    html += renderPendingCardHtml();
  } else {
    html += renderTaskCardStatic({
      task: { text: liveRun.taskText },
      bounds: {
        editable_paths: splitCsv(liveRun.editableStr),
        forbidden_areas: splitCsv(liveRun.forbiddenStr),
      },
      acceptance_descriptions: {},
    });
  }
  for (const line of liveRun.lines) {
    const cls = line.isFail ? "quiet-line is-fail" : "quiet-line";
    html += `<div class="${cls}">${escapeHtml(line.text)}</div>`;
  }
  if (liveRun.errorMessage) {
    html += `<div class="msg-error"><span class="label">error</span>${escapeHtml(
      liveRun.errorMessage
    )}</div>`;
  }
  html += "</div>";
  return html;
}

function wirePendingCard() {
  const confirmBtn = el("pending-confirm");
  const cancelBtn = el("pending-cancel");
  if (confirmBtn) confirmBtn.onclick = confirmPending;
  if (cancelBtn) cancelBtn.onclick = cancelPending;
}

// ------------------------------------------------------------- composer

function setComposerDisabled(disabled) {
  el("composer-input").disabled = disabled;
}

function submitComposer() {
  if (pendingComposer || (liveRun && !liveRun.finished)) return;
  const textarea = el("composer-input");
  const text = textarea.value.trim();
  if (!text) {
    toast("describe the task first", true);
    return;
  }
  (async () => {
    let editableStr = "";
    let forbiddenStr = "";
    try {
      const status = await api("/api/status");
      editableStr = (status.task && status.task.editable) || "";
      forbiddenStr = (status.task && status.task.forbidden) || "";
    } catch {
      // honest fallback: blank bounds, still editable by hand
    }
    pendingComposer = { taskText: text, editableStr, forbiddenStr };
    liveRun = { taskText: text, editableStr, forbiddenStr, confirmed: false, lines: [], errorMessage: null, finished: false };
    textarea.value = "";
    selectLive();
    setComposerDisabled(true);
    wirePendingCard();
  })();
}

function cancelPending() {
  if (!pendingComposer) return;
  el("composer-input").value = pendingComposer.taskText;
  pendingComposer = null;
  liveRun = null;
  setComposerDisabled(false);
  viewingLive = false;
  selectedRunId = allRuns.length ? allRuns[0].id : null;
  renderSidebar();
  renderThread();
  renderPreview();
  el("composer-input").focus();
}

async function confirmPending() {
  const editableInput = el("pending-editable");
  const forbiddenInput = el("pending-forbidden");
  const editable = splitCsv(editableInput ? editableInput.value : pendingComposer.editableStr);
  const forbidden = splitCsv(forbiddenInput ? forbiddenInput.value : pendingComposer.forbiddenStr);
  if (!editable.length) {
    toast("give the loop at least one editable path", true);
    return;
  }
  const confirmBtn = el("pending-confirm");
  if (confirmBtn) confirmBtn.disabled = true;

  let saved;
  try {
    saved = await api("/api/task", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: pendingComposer.taskText, editable, forbidden }),
    });
  } catch {
    saved = { ok: false, error: "could not reach the server" };
  }
  if (!saved.ok) {
    toast(saved.error || "could not save the task", true);
    if (confirmBtn) confirmBtn.disabled = false;
    return;
  }
  if (saved.warning) toast(saved.warning);

  liveRun.editableStr = editable.join(", ");
  liveRun.forbiddenStr = forbidden.join(", ");
  liveRun.confirmed = true;
  pendingComposer = null;
  renderThread();
  startLiveRun();
}

// ---------------------------------------------------------------- live run

function stageLineText(ev) {
  if (ev.stage === "verify") {
    if (ev.state === "running") return "the gate is judging";
    return ev.detail ? `the gate judged: ${ev.detail}` : "the gate is judging";
  }
  const base = STAGE_LABEL[ev.stage] || ev.stage;
  return ev.detail ? `${base} (${ev.detail})` : base;
}

async function startLiveRun() {
  liveRunId = null;
  liveStageUrl = null;
  liveStageAttempt = null;

  // Prime the bus cursor to NOW before the run starts: polling from byte 0
  // would replay every historical run.started/stage.up in the bus and adopt a
  // PREVIOUS run's id (and its long-dead stage URL) as this run's.
  eventsCursor = 0;
  try {
    const primed = await api("/api/events?cursor=0");
    eventsCursor = primed.cursor || 0;
  } catch {
    // bus unreadable — polling will just start from 0 and the run_id guard
    // below still prevents cross-run stage adoption
  }

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const sock = new WebSocket(`${proto}//${location.host}/ws/run?stage_hold=1`);
  ws = sock;

  sock.onmessage = (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return;
    }
    onWsMessage(msg);
  };
  sock.onerror = () => {
    failLiveRun("connection to the run stream failed");
  };
  sock.onclose = () => {
    // Only an UNEXPECTED close is a failure: normal completion already went
    // through "done"/"error" and cleared `ws`/`liveRun`.
    if (ws === sock && liveRun && !liveRun.finished) {
      failLiveRun("the run stream closed unexpectedly");
    }
  };

  eventsTimer = setInterval(pollEventsTick, 2000);
  renderSidebar();
  renderPreview();
}

function shouldRenderStageEvent(ev) {
  // One line per meaningful transition, not one per event: bounds/loop emit
  // both "running" and "done" with the same label (a duplicate line to a
  // reader), sandbox emits only "done"/"fail", and verify's "done" carries
  // the verdict — the only "done" whose text differs from its "running".
  if (ev.state === "fail") return true;
  if (ev.state === "running") return ev.stage !== "sandbox";
  if (ev.state === "done") return ev.stage === "sandbox" || ev.stage === "verify";
  return false;
}

function onWsMessage(msg) {
  if (!liveRun) return;
  if (msg.type === "stage") {
    if (shouldRenderStageEvent(msg)) {
      liveRun.lines.push({ text: stageLineText(msg), isFail: msg.state === "fail" });
    }
    if (viewingLive) renderThread();
  } else if (msg.type === "done") {
    stopLiveRunTimers();
    liveRunId = msg.run_id;
    liveStageUrl = msg.stage_url || null;
    liveRun.finished = true;
    liveRun = null;
    pendingComposer = null;
    setComposerDisabled(false);
    (async () => {
      await loadRuns();
      await selectRun(msg.run_id);
      if (liveStageUrl) {
        const attempts = (currentDetail && currentDetail.attempts) || [];
        liveStageAttempt = attempts.length ? attempts[attempts.length - 1].attempt : null;
      }
      renderSidebar();
      renderPreview();
    })();
  } else if (msg.type === "error") {
    failLiveRun(msg.message || "the run failed");
  }
}

function failLiveRun(message) {
  stopLiveRunTimers();
  if (liveRun) {
    liveRun.errorMessage = message;
    if (viewingLive) renderThread();
  }
  setComposerDisabled(false);
  // Honest refresh: a run may (or may not) exist in the store now depending on
  // where the failure happened — reflect reality instead of leaving a
  // perpetual "(new run)" placeholder.
  (async () => {
    await loadRuns();
    liveRun = null;
    renderSidebar();
  })();
}

function stopLiveRunTimers() {
  if (eventsTimer) {
    clearInterval(eventsTimer);
    eventsTimer = null;
  }
  if (ws) {
    try {
      ws.close();
    } catch {
      // already closed
    }
    ws = null;
  }
}

async function pollEventsTick() {
  let res;
  try {
    res = await api(`/api/events?cursor=${eventsCursor}`);
  } catch {
    return;
  }
  eventsCursor = res.cursor || eventsCursor;
  for (const ev of res.events || []) {
    if (ev.kind === "run.started" && !liveRunId) {
      liveRunId = ev.run_id;
    } else if (ev.kind === "stage.up" && ev.run_id === liveRunId) {
      liveStageUrl = (ev.data && ev.data.url) || null;
      liveStageAttempt = ev.data && typeof ev.data.attempt === "number" ? ev.data.attempt : null;
      renderPreview();
    } else if (ev.kind === "stage.down" && ev.run_id === liveRunId) {
      liveStageUrl = null;
      renderPreview();
    }
  }
}

// ----------------------------------------------------------------- preview

function computePreviewState() {
  if (viewingLive && liveStageUrl) {
    return { mode: "live", url: liveStageUrl, attempt: liveStageAttempt, runId: liveRunId, diffSha: null };
  }
  if (selectedRunId && liveStageUrl && selectedRunId === liveRunId) {
    return { mode: "live", url: liveStageUrl, attempt: liveStageAttempt, runId: liveRunId, diffSha: null };
  }
  if (selectedRunId && currentDetail && currentDetail.attempts) {
    const attempts = currentDetail.attempts;
    for (let i = attempts.length - 1; i >= 0; i--) {
      const a = attempts[i];
      if (a.stage) {
        return {
          mode: "snapshot",
          url: `/api/runs/${encodeURIComponent(selectedRunId)}/stage/${a.attempt}`,
          attempt: a.attempt,
          runId: selectedRunId,
          diffSha: a.stage.diff_sha256 || null,
        };
      }
    }
  }
  return { mode: "empty" };
}

function renderPreview() {
  const state = computePreviewState();
  const dot = el("preview-dot");
  const url = el("preview-url");
  const attemptEl = el("preview-attempt");
  const page = el("preview-page");
  const empty = el("preview-empty");
  const frame = el("preview-frame");
  const foot = el("preview-foot");

  if (state.mode === "live") {
    dot.classList.add("live");
    url.textContent = state.url;
    attemptEl.textContent = state.attempt ? `attempt ${state.attempt} · sandbox` : "sandbox";
    empty.classList.add("hidden");
    frame.classList.remove("hidden");
    if (lastFrameSrc !== state.url) {
      frame.src = state.url;
      lastFrameSrc = state.url;
    }
    foot.textContent = state.runId
      ? `Evidence — bound to run ${state.runId}, attempt ${state.attempt || "?"} (live)`
      : "";
    return;
  }

  if (state.mode === "snapshot") {
    dot.classList.remove("live");
    url.textContent = `run ${state.runId} · snapshot`;
    attemptEl.textContent = `attempt ${state.attempt} · sandbox`;
    empty.classList.add("hidden");
    frame.classList.remove("hidden");
    if (lastFrameSrc !== state.url) {
      frame.src = state.url;
      lastFrameSrc = state.url;
    }
    const sha8 = state.diffSha ? state.diffSha.slice(0, 8) : null;
    foot.textContent =
      `Evidence — bound to run ${state.runId}, attempt ${state.attempt}` +
      (sha8 ? ` · diff ${sha8}` : "");
    return;
  }

  dot.classList.remove("live");
  url.textContent = "—";
  attemptEl.textContent = "";
  frame.classList.add("hidden");
  frame.removeAttribute("src");
  lastFrameSrc = null;
  foot.textContent = "";
  empty.classList.remove("hidden");
  empty.textContent = selectedRunId || viewingLive
    ? "No stage evidence recorded for this run."
    : "Select a run to view evidence.";
}

// -------------------------------------------------------------------- init

function wireComposer() {
  const textarea = el("composer-input");
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitComposer();
    }
  });
}

el("new-run-btn").addEventListener("click", () => {
  el("composer-input").focus();
  el("composer-input").scrollIntoView({ block: "center" });
});

window.addEventListener("hashchange", () => {
  const id = parseHash();
  if (id) selectRun(id, { updateHash: false });
});

(async function init() {
  wireComposer();
  await loadStatus();
  await loadRuns();
  const hashId = parseHash();
  if (hashId) {
    selectRun(hashId, { updateHash: false });
  } else if (allRuns.length) {
    selectRun(allRuns[0].id, { updateHash: false });
  } else {
    renderThread();
    renderPreview();
  }
})();
