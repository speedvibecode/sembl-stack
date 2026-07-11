#!/usr/bin/env node
// O12 WP3 — the flagship's `profile:"web"` acceptance check.
//
// Given the feedback board boots with Supabase unconfigured (the local-preview
// fallback dataset from src/lib/feedback.ts:fallbackFeedback),
// When a client GETs "/",
// Then the rendered page must show all three fallback feedback items.
//
// No new test framework: this is a plain Node script (zero added dependencies),
// invoked directly as the acceptance check's `run.command`. It starts `next dev`
// against the app directory, forces the Supabase env vars empty (so the app takes
// the deterministic local-fallback path -- no network beyond localhost, per the
// spec's determinism note), polls until the server responds, fetches "/", and
// asserts on the rendered HTML. Exit 0 = PASS, exit 1 = FAIL/ERROR (with a reason
// on stderr) -- exactly what the command-runner machinery this profile reuses
// already expects from a `run.command`.
//
// Env overrides (used by the pytest planted-break test to point this same script
// at a broken copy of the app without duplicating it):
//   WEB_CHECK_APP_DIR   app root to run against (default: this script's parent dir)
//   WEB_CHECK_PORT      fixed port instead of an OS-assigned free one
//   WEB_CHECK_TIMEOUT_MS  overall wait budget for the dev server to become ready
//   SEMBL_STAGE_URL     set by the loop when a stage is already serving this
//                       sandbox (SPEC-stage): assert against THAT server instead
//                       of booting our own — Next 16 holds a per-directory
//                       single-instance lock, so a second `next dev` here would
//                       refuse to start.

import { spawn, execSync } from "node:child_process";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import path from "node:path";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const APP_DIR = process.env.WEB_CHECK_APP_DIR
  ? path.resolve(process.env.WEB_CHECK_APP_DIR)
  : path.resolve(SCRIPT_DIR, "..");
const READY_TIMEOUT_MS = Number(process.env.WEB_CHECK_TIMEOUT_MS || 60000);
const POLL_INTERVAL_MS = 300;

// The exact three items rendered by the local-preview fallback dataset (given/when/
// then premise: no Supabase env -> the app serves `fallbackFeedback` verbatim).
const EXPECTED_TITLES = [
  "Invite review needs a status trail",
  "Export filter should persist",
  "Closed cards need calmer contrast",
];

function fail(reason) {
  process.stderr.write(`FAIL: ${reason}\n`);
  process.exitCode = 1;
}

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

function killTree(child) {
  if (!child || child.pid == null || child.killed) return;
  try {
    if (process.platform === "win32") {
      // `next dev` (via npx) forks a real Node child under the shim process; a
      // plain child.kill() only signals the immediate process and leaves the
      // dev server running. /T kills the whole process tree by PID.
      execSync(`taskkill /PID ${child.pid} /T /F`, { stdio: "ignore" });
    } else {
      process.kill(-child.pid, "SIGKILL");
    }
  } catch {
    // Best-effort cleanup -- the process may have already exited.
  }
}

async function waitForReady(url, deadline) {
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(2000) });
      if (res.status) return true;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  return false;
}

async function checkRenderedPage(url) {
  const res = await fetch(url, { signal: AbortSignal.timeout(10000) });
  if (res.status !== 200) {
    fail(`GET ${url} returned status ${res.status}, expected 200`);
    return;
  }
  const html = await res.text();
  const missing = EXPECTED_TITLES.filter((title) => !html.includes(title));
  if (missing.length > 0) {
    fail(
      `rendered page is missing expected fallback feedback item(s): ${JSON.stringify(missing)}`,
    );
    return;
  }
  process.stdout.write(
    "PASS: feedback board renders all 3 local-fallback feedback items\n",
  );
}

async function main() {
  if (process.env.SEMBL_STAGE_URL) {
    // The loop's stage already serves this sandbox — use it, don't race it.
    try {
      await checkRenderedPage(process.env.SEMBL_STAGE_URL);
    } catch (err) {
      fail(`web check crashed against the stage: ${err && err.stack ? err.stack : err}`);
    }
    return;
  }

  const port = process.env.WEB_CHECK_PORT
    ? Number(process.env.WEB_CHECK_PORT)
    : await freePort();
  const url = `http://127.0.0.1:${port}/`;

  const child = spawn(
    "npx",
    ["--no-install", "next", "dev", "-p", String(port)],
    {
      cwd: APP_DIR,
      shell: true,
      // POSIX killTree signals the process GROUP (-pid); without its own group
      // (detached) there is nothing to signal and the dev server would leak.
      detached: process.platform !== "win32",
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...process.env,
        // Force the deterministic local-fallback path: no live Supabase project,
        // no network beyond localhost, regardless of what .env.local holds.
        NEXT_PUBLIC_SUPABASE_URL: "",
        NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "",
        NEXT_PUBLIC_SUPABASE_ANON_KEY: "",
      },
    },
  );

  let serverOutput = "";
  child.stdout.on("data", (d) => (serverOutput += d.toString()));
  child.stderr.on("data", (d) => (serverOutput += d.toString()));

  let exitedEarly = null;
  child.on("exit", (code) => {
    exitedEarly = code;
  });

  try {
    const deadline = Date.now() + READY_TIMEOUT_MS;
    const ready = await waitForReady(url, deadline);
    if (exitedEarly !== null) {
      fail(`dev server exited early (code ${exitedEarly}) before becoming ready:\n${serverOutput.slice(-2000)}`);
      return;
    }
    if (!ready) {
      fail(`dev server never responded at ${url} within ${READY_TIMEOUT_MS}ms:\n${serverOutput.slice(-2000)}`);
      return;
    }

    await checkRenderedPage(url);
  } catch (err) {
    fail(`web check crashed: ${err && err.stack ? err.stack : err}`);
  } finally {
    killTree(child);
  }
}

main();
