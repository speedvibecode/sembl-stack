"""L5 verify adapter (ours): the deterministic gate, Sembl.

MCP-first (`verify_change`), with a `sembl verify` CLI fallback. No model, no tokens,
same verdict every run. Verifies the diff in the sandbox against the bounds and
cross-checks the executor's self-report.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .base import Bounds, ExecutionResult, Verdict
from ..transport import mcp_client


class SemblVerifyAdapter:
    def __init__(self, transport: str = "mcp", mcp_server: list[str] | None = None):
        self.transport = transport
        self.mcp_server = mcp_server or ["uvx", "--from", "sembl[mcp]", "sembl-mcp"]

    def verify(self, bounds: Bounds, result: ExecutionResult,
               strict: bool, acceptance: dict | None = None) -> Verdict:
        # O12: `acceptance` is {"declared": [...], "results": [...]} (Acceptance.to_contract()
        # + AcceptanceReport.results) — omitted entirely on both transports when empty, so a
        # pinned older gate (or a caller that never declares a behavioral surface) still
        # verifies exactly as before (back-compat, byte-identical verdict).
        acceptance = acceptance if acceptance and (acceptance.get("declared")
                                                    or acceptance.get("results")) else None
        # 1) MCP path — hand over the DIFF (not a repo path): the gate verifies the
        # patch, so detection never depends on the verifier process being able to run
        # git in the sandbox (it often can't — scrubbed env over stdio MCP).
        if self.transport == "mcp" and mcp_client.available():
            try:
                args = {
                    "diff": result.diff,
                    "editable_paths": bounds.editable_paths,
                    "forbidden_areas": bounds.forbidden_areas,
                    "churn_budget": bounds.churn_budget,
                    "report": result.report,
                    "strict": strict,
                }
                if acceptance is not None:
                    args["acceptance"] = acceptance
                out = mcp_client.call_tool(self.mcp_server, "verify_change", args)
                return self._from_payload(out)
            except Exception:
                pass
        # 2) CLI fallback — same contract: verify the diff via a temp .patch.
        return self._cli(bounds, result, strict, acceptance)

    def _cli(self, bounds: Bounds, result: ExecutionResult, strict: bool,
             acceptance: dict | None = None) -> Verdict:
        with tempfile.TemporaryDirectory() as tmp:
            bf = Path(tmp) / "bounds.json"
            rf = Path(tmp) / "report.json"
            pf = Path(tmp) / "change.patch"
            bf.write_text(json.dumps(bounds.to_contract()), encoding="utf-8")
            rf.write_text(json.dumps(result.report), encoding="utf-8")
            pf.write_text(result.diff, encoding="utf-8")
            # Invoke via the running interpreter (`python -m sembl.cli`) rather than a bare
            # `sembl` on PATH: sembl-stack runs on the shared venv that has sembl installed,
            # but PATH may not include its Scripts dir, which made the CLI fallback raise
            # FileNotFoundError. `sys.executable -m` resolves the same package every time.
            cmd = [sys.executable, "-m", "sembl.cli", "verify", "--diff", str(pf),
                   "--wo-file", str(bf), "--report", str(rf), "--json"]
            if strict:
                cmd.append("--strict")
            if acceptance is not None:
                af = Path(tmp) / "acceptance.json"
                af.write_text(json.dumps(acceptance), encoding="utf-8")
                cmd += ["--acceptance", str(af)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            try:
                return self._from_payload(json.loads(proc.stdout))
            except json.JSONDecodeError:
                raise RuntimeError(
                    f"L5: sembl verify produced no JSON (rc={proc.returncode}): "
                    f"{proc.stderr.strip() or proc.stdout.strip()}")

    @staticmethod
    def _from_payload(payload: dict) -> Verdict:
        summary = payload.get("summary", payload)
        status = summary.get("verdict") or payload.get("verdict") or "BLOCK"
        reasons = summary.get("reasons") or payload.get("reasons") or []
        return Verdict(status=status, reasons=reasons, raw=payload)
