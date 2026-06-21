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

from .base import Delivery

_URL_RE = re.compile(r"https://[^\s]+")


class VercelDeployAdapter:
    def __init__(self, timeout: int = 1800, yes: bool = True):
        self.timeout = timeout
        self.yes = yes

    def available(self) -> bool:
        return shutil.which("vercel") is not None

    def deploy(self, repo: str, *, production: bool = False,
               prebuilt: bool = False) -> Delivery:
        repo_path = str(Path(repo).resolve())
        cmd = ["vercel"]
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
                    "stdout": _tail(exc.stdout),
                    "stderr": _tail(exc.stderr),
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
                "stdout": _tail(stdout),
                "stderr": _tail(stderr),
            },
        )


def _last_url(text: str | None) -> str | None:
    urls = _URL_RE.findall(text or "")
    return urls[-1].rstrip(".,)") if urls else None


def _tail(text: str | bytes | None, limit: int = 4000) -> str:
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    text = str(text)
    return text[-limit:]


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
