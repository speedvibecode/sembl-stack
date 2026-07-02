"""The platform contract.

The data types are the canonical artifacts (see `sembl_stack/artifacts.py`); the
Protocols below are what an adapter must satisfy to be swappable into a layer. Re-exported
here so adapters import everything they need from one place.
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Protocol, runtime_checkable

from ..artifacts import (  # noqa: F401  (re-exported for adapters)
    Bounds,
    Change,
    Context,
    Delivery,
    ExecutionResult,
    MergeRecord,
    ReconciliationReport,
    ReviewReport,
    SpecGraph,
    Task,
    Trace,
    Verdict,
)


# --- Shared adapter helpers ---------------------------------------------------

def changed_files_from_diff(diff: str) -> list[str]:
    """Files touched by a unified git diff, order-preserved and de-duplicated.

    Reads BOTH the `diff --git a/… b/…` headers and the `+++ b/…` markers, unioned:
      * the `diff --git` header names a file even when it has no `+++` hunk — e.g. an
        EMPTY new file an errored agent created. A `+++`-only parser silently drops it,
        and the gate then flags a spurious "unreported change";
      * the `+++ b/` marker is the fallback for a diff fragment that arrives without a
        full header.
    `/dev/null` (the add/delete sentinel) is skipped. Every executor adapter uses this
    one parser so Claude/OpenCode/Aider report changed files consistently.
    """
    seen: set[str] = set()
    out: list[str] = []

    def add(path: str) -> None:
        path = path.strip()
        if path and path != "/dev/null" and path not in seen:
            seen.add(path)
            out.append(path)

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            _, _, tail = line.partition(" b/")
            if tail:
                add(tail)
        elif line.startswith("+++ "):
            marker = line[4:]
            if marker.startswith("b/"):
                marker = marker[2:]
            add(marker.split("\t", 1)[0])     # drop a trailing tab-timestamp if present
    return out


# Env-var names whose values are credentials; a secret only ever lives in the
# environment, so an executor CLI echoing one (e.g. in an auth error) is the one
# path it could reach a persisted run artifact. Scrubbed by value below.
_SECRET_ENV_NAME = re.compile(r"(API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)S?$", re.IGNORECASE)
# Generic provider-key shapes (sk-ant-…, sk-proj-…, sk-or-v1-…) as a second net.
_SECRET_TOKEN = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")


def scrub_secrets(text: str) -> str:
    """Redact anything secret-shaped before it reaches a run artifact.

    Executor stdout/stderr is persisted into `.sembl/runs/<id>/change.json` for
    debuggability; the security invariant (no key value ever stored) must hold even
    when a CLI misbehaves and echoes a credential. Env values are compared in memory
    only — nothing read here is ever written anywhere except as its redaction marker.
    """
    if not text:
        return text
    for name, value in os.environ.items():
        if len(value) >= 8 and _SECRET_ENV_NAME.search(name):
            text = text.replace(value, f"[redacted:{name}]")
    return _SECRET_TOKEN.sub("[redacted:key]", text)


def run_executor(cmd: list[str], cwd: str, timeout: int, **run_kwargs):
    """Run an executor subprocess, turning a timeout into a structured signal.

    Returns ``(returncode, stdout, stderr, timed_out)``. A `subprocess.TimeoutExpired`
    is caught here (its partial stdout/stderr preserved) instead of being allowed to
    propagate and abort the whole loop — the caller records `timed_out` in the report so
    the gate stage can convert it to a BLOCK rather than a crash.
    """
    try:
        # encoding/errors explicit: agents emit UTF-8 (box-drawing, emoji, ✓). The default
        # text=True decodes with the locale codec (cp1252 on Windows), which crashes the
        # stdout reader thread mid-run and silently loses the output. Decode as UTF-8 and
        # replace undecodable bytes so capture never aborts the loop.
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", **run_kwargs)
        return proc.returncode, proc.stdout or "", proc.stderr or "", False
    except subprocess.TimeoutExpired as exc:
        out, err = exc.stdout or "", exc.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return -1, out, err, True


# --- Layer interfaces (Protocols) ---------------------------------------------

class Sandbox(Protocol):              # an open sandbox handle (from L4)
    workdir: str
    def diff(self) -> str: ...
    def close(self) -> None: ...


@runtime_checkable
class SpecAdapter(Protocol):         # L2: Task -> Bounds
    def plan(self, task: Task) -> Bounds: ...


@runtime_checkable
class SandboxAdapter(Protocol):      # L4: Change -> Change (contained)
    def open(self, repo: str) -> Sandbox: ...


@runtime_checkable
class ExecuteAdapter(Protocol):      # L3: Task+Bounds(+Context) -> Change
    def run(self, task: Task, bounds: Bounds, sandbox: Sandbox,
            feedback: str | None) -> ExecutionResult: ...


@runtime_checkable
class VerifyAdapter(Protocol):       # L5: Change+Bounds -> Verdict
    def verify(self, bounds: Bounds, result: ExecutionResult,
               strict: bool) -> Verdict: ...


@runtime_checkable
class ReconcileAdapter(Protocol):    # L5.5: SpecGraph+CodeGraph -> report
    def reconcile(self, spec_graph: SpecGraph, code_graph: dict) -> ReconciliationReport:
        ...


@runtime_checkable
class MergeAdapter(Protocol):        # L6.5: Verdict(PASS) -> MergeRecord
    def merge(self, repo: str, *, into: str = "main", source: str = "HEAD",
              no_ff: bool = True, message: str | None = None) -> MergeRecord:
        ...


@runtime_checkable
class DeployAdapter(Protocol):       # L7: Verdict(PASS) -> Delivery; rollback reverts it
    def deploy(self, repo: str, *, production: bool = False,
               prebuilt: bool = False) -> Delivery:
        ...

    def rollback(self, repo: str, *, to: str | None = None) -> Delivery:
        ...


@runtime_checkable
class PostDeployAdapter(Protocol):   # L8: Delivery -> Verdict
    def verify(self, delivery: Delivery, *, health_path: str = "/",
               timeout_s: float = 10.0) -> Verdict:
        ...


@runtime_checkable
class ReviewAdapter(Protocol):       # L5.5 quality: a diff -> ReviewReport (advisory)
    def review(self, diff: str, *, reviewer_hint: str = "") -> ReviewReport:
        ...
