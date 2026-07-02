"""L7 deploy adapter for Vercel CLI.

The stage owns the Delivery artifact, not the hosting mechanism. Credentials are
left to the local Vercel CLI environment (`vercel login`, `VERCEL_TOKEN`, or linked
project config) and are never copied into the artifact.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from ._redact import summarize
from .base import Delivery

_URL_RE = re.compile(r"https://[^\s]+")


class VercelDeployAdapter:
    def __init__(self, timeout: int = 1800, yes: bool = True):
        self.timeout = timeout
        self.yes = yes

    def available(self) -> bool:
        return bool(_resolve_vercel())

    def deploy(self, repo: str, *, production: bool = False,
               prebuilt: bool = False) -> Delivery:
        repo_path = str(Path(repo).resolve())
        cmd = _resolve_vercel()
        if prebuilt:
            cmd.append("deploy")
            cmd.append("--prebuilt")
        if production:
            cmd.append("--prod")
        if self.yes:
            cmd.append("--yes")

        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd, cwd=repo_path, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            return Delivery(
                target="vercel",
                status="failed",
                data={
                    "reason": "timeout",
                    "latency_s": round(time.perf_counter() - t0, 3),
                    "command": _safe_command(cmd),
                    "stdout": summarize(exc.stdout),
                    "stderr": summarize(exc.stderr),
                },
            )

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        url = _last_url(stdout) or _last_url(stderr)
        status = "deployed" if proc.returncode == 0 and url else "failed"
        return Delivery(
            target="vercel",
            url=url,
            status=status,
            data={
                "production": production,
                "prebuilt": prebuilt,
                "returncode": proc.returncode,
                "latency_s": round(time.perf_counter() - t0, 3),
                "command": _safe_command(cmd),
                "stdout": summarize(stdout),
                "stderr": summarize(stderr),
            },
        )

    def rollback(self, repo: str, *, to: str | None = None) -> Delivery:
        """Promote the previous production deployment (Vercel rollback).

        Mechanism only: the decision to roll back is the caller's (the L8 gate Verdict).
        `to` optionally names a specific deployment URL/id to roll back to. When omitted,
        this looks up the immediately previous production deployment and rolls back to it
        explicitly — verified live against a real deploy: bare `vercel rollback` (no target)
        only reports in-progress rollback *status* on current CLI versions ("No deployment
        rollback in progress", exit 0) rather than performing one, so the old
        target-less/omitted call silently never rolled anything back.
        """
        repo_path = str(Path(repo).resolve())
        if not to:
            to = self._previous_production_url(repo_path)
            if not to:
                return Delivery(
                    target="vercel",
                    status="rollback_failed",
                    data={"reason": "no previous production deployment found"},
                )
        cmd = _resolve_vercel() + ["rollback", to]
        if self.yes:
            cmd.append("--yes")

        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd, cwd=repo_path, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            return Delivery(
                target="vercel",
                status="rollback_failed",
                data={
                    "reason": "timeout",
                    "latency_s": round(time.perf_counter() - t0, 3),
                    "command": _safe_command(cmd),
                    "stdout": summarize(exc.stdout),
                    "stderr": summarize(exc.stderr),
                },
            )

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        url = _last_url(stdout) or _last_url(stderr)
        status = "rolled_back" if proc.returncode == 0 else "rollback_failed"
        return Delivery(
            target="vercel",
            url=url,
            status=status,
            data={
                "rolled_back_to": to,
                "returncode": proc.returncode,
                "latency_s": round(time.perf_counter() - t0, 3),
                "command": _safe_command(cmd),
                "stdout": summarize(stdout),
                "stderr": summarize(stderr),
            },
        )

    def _previous_production_url(self, repo_path: str) -> str | None:
        """The production deployment immediately before the current one.

        `vercel ls --prod` prints a scriptable bare-URL list at the end of its output,
        newest first — index 0 is the (bad) deployment we're rolling back FROM, index 1 is
        the one to roll back TO. Returns None if there's no prior production deployment.
        """
        try:
            proc = subprocess.run(
                _resolve_vercel() + ["ls", "--prod"], cwd=repo_path,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return None
        urls = [ln.strip() for ln in (proc.stdout or "").splitlines()
                if ln.strip().startswith("https://")]
        return urls[1] if len(urls) > 1 else None


def _resolve_vercel() -> list[str]:
    """Return the argv prefix that actually launches the Vercel CLI.

    On Windows, npm installs `vercel` as a `.cmd`/`.ps1` shim (pure-JS package, no vendored
    native binary like opencode has) — `subprocess.run(["vercel", ...])` without a shell
    raises `FileNotFoundError` because CreateProcess can't launch a batch file directly.
    Route through the shim's own interpreter instead. On POSIX `which` already returns the
    real (shebang'd) executable, so it needs no wrapping.
    """
    exe = shutil.which("vercel")
    if not exe:
        return []
    low = exe.lower()
    if low.endswith((".cmd", ".bat")):
        return ["cmd", "/c", exe]
    if low.endswith(".ps1"):
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", exe]
    return [exe]


_DEPLOYMENT_HOST_RE = re.compile(r"^https://[^/\s]+\.vercel\.app(?:/|$)")


def _last_url(text: str | None) -> str | None:
    """The last *deployment* URL Vercel CLI printed — never a dashboard/API link.

    Live-proof finding: the CLI interleaves other `https://` links into stdout alongside
    the human-facing deployment URL — an `https://vercel.com/<team>/<project>/<id>`
    dashboard "Inspect" link, and on some versions an `https://api.vercel.com/v13/
    deployments/...` internal status-poll call. Picking the textually-last URL without
    filtering returns one of those instead, which then silently breaks every downstream
    health check against it. Every real deployment/preview/production URL Vercel serves
    lives on the `*.vercel.app` domain (never `vercel.com`/`api.vercel.com`), so prefer
    matches on that host; fall back to any match only if that's all there is.
    """
    urls = _URL_RE.findall(text or "")
    preferred = [u for u in urls if _DEPLOYMENT_HOST_RE.match(u)]
    picked = preferred or urls
    return picked[-1].rstrip(".,)\"'") if picked else None


def _safe_command(cmd: list[str]) -> list[str]:
    safe: list[str] = []
    redact_next = False
    for part in cmd:
        if redact_next:
            safe.append("<redacted>")
            redact_next = False
            continue
        safe.append(part)
        if part == "--token":
            redact_next = True
    return safe
