"""L3 executor: a deterministic mock — no model, no keys.

It exists to prove the *loop* end to end (and to make the retry-on-BLOCK behaviour
visible): the first attempt deliberately wanders out of scope and fabricates a claim
(→ BLOCK); once the gate's feedback arrives, it behaves (→ PASS). Swap for `opencode`
to drive a real agent.
"""
from __future__ import annotations

from pathlib import Path

from .base import Bounds, ExecutionResult, Sandbox, Task


class MockExecutor:
    def run(self, task: Task, bounds: Bounds, sandbox: Sandbox,
            feedback: str | None) -> ExecutionResult:
        root = Path(sandbox.workdir)

        if not feedback:
            # First attempt: misbehave — edit outside scope + fabricate a claim.
            stray = bounds.forbidden_areas[0] if bounds.forbidden_areas else ""
            rel = self._write(root, stray, "stray.txt", "# out-of-scope edit\n") \
                if stray else self._write(root, "", "OUTSIDE.txt", "# out-of-scope\n")
            report = {
                "files_modified": [rel, "src/imaginary.py"],   # imaginary = fabrication
                "tests_passed": True,                           # no evidence attached
            }
            return ExecutionResult(diff=sandbox.diff(), report=report, workdir=str(root))

        # Retry: stay in the first editable path and report honestly, with evidence.
        target = bounds.editable_paths[0] if bounds.editable_paths else "."
        rel = self._write(root, target, "patch.py", "# in-scope change\nVALUE = 1\n")
        report = {
            "files_modified": [rel],
            "tests_passed": True,
            "exit_code": 0,
            "output": "pytest: 1 passed in 0.1s",
        }
        return ExecutionResult(diff=sandbox.diff(), report=report, workdir=str(root))

    @staticmethod
    def _write(root: Path, target: str, default_name: str, content: str) -> str:
        """Write `content` to `target` (file or dir). Returns the repo-relative path."""
        t = (root / target) if target else root
        if target and not target.endswith("/") and t.suffix:
            path = t                      # target is a concrete file
        else:
            path = t / default_name        # target is a dir (or repo root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(content)
        return str(path.relative_to(root)).replace("\\", "/")
