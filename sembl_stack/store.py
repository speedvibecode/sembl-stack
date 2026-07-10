"""Run store — artifacts persisted at `.sembl/runs/<run-id>/` in the target repo.

Local-first, no server required to read a past run. Each run is a directory of JSON
artifacts plus a `run.json` manifest. This is what makes runs inspectable (TUI/web),
resumable, and enterable at an arbitrary stage (supply the upstream artifact).
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from . import artifacts
from .artifacts import _Serializable
from .bus import publish


class Run:
    def __init__(self, root: Path, run_id: str):
        self.id = run_id
        self.dir = root / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self.dir / "run.json"

    # -- artifacts --------------------------------------------------------------
    def put(self, artifact: _Serializable, name: str | None = None) -> str:
        """Persist an artifact; `name` defaults to its KIND. Returns the file name."""
        name = name or artifact.KIND
        fname = f"{name}.json"
        (self.dir / fname).write_text(artifact.to_json(), encoding="utf-8")
        self._touch_manifest(name, artifact.KIND, fname)
        return fname

    def get(self, name: str):
        """Load an artifact by name (reconstructs the right type via its `_kind` tag)."""
        path = self.dir / f"{name}.json"
        if not path.is_file():
            return None
        return artifacts.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def has(self, name: str) -> bool:
        return (self.dir / f"{name}.json").is_file()

    # -- manifest ---------------------------------------------------------------
    def manifest(self) -> dict:
        if self._manifest_path.is_file():
            return json.loads(self._manifest_path.read_text(encoding="utf-8"))
        return {}

    def set_status(self, status: str, **extra) -> None:
        m = self.manifest()
        m["status"] = status
        m["updated"] = time.time()
        m.update(extra)
        self._write_manifest(m)

    def append_event(self, stage: str, status: str, attempt: int = 0) -> None:
        """Append one stage-transition line to `events.jsonl` — the IDE's live-run stage
        lighting (docs/DESIGN-sembl-ide.md §5 step 2) tails this while a run executes.
        One JSON object per line: `{"ts", "stage", "status", "attempt"}` where `stage` is a
        registry layer key (context|spec|execute|sandbox|verify|review|merge|deploy|
        postdeploy) and `status` is "start"|"done"|"failed". Recording only — never raises,
        so a write failure here can never affect the loop or the gate."""
        try:
            line = json.dumps(
                {"ts": time.time(), "stage": stage, "status": status, "attempt": attempt},
                ensure_ascii=False)
            with (self.dir / "events.jsonl").open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        # Mirror to the repo-wide bus (D5) so any subscriber sees stage transitions live,
        # for free, at this single choke point. `self.dir` is `<repo>/.sembl/runs/<id>`.
        try:
            summary = f"{stage}: {status}" + (f" (attempt {attempt})" if attempt else "")
            publish(self.dir.parents[2], {
                "kind": "run.stage", "run_id": self.id, "summary": summary,
                "data": {"stage": stage, "status": status, "attempt": attempt}})
        except Exception:
            pass

    def record_attempt(self, attempt: int, **metric) -> None:
        """Append a per-attempt cost/latency record to the manifest (C1.3).

        One entry per execute call: `{attempt, latency_s, agent, model, exit_code,
        tokens, cost}` (tokens/cost only where the executor reported usage). This is the
        signal `sembl-stack runs` shows and that the process-RSI / eval (B) layer consumes.
        Keys with a None value are dropped so the manifest stays clean.
        """
        m = self.manifest()
        entry = {"attempt": attempt}
        entry.update({k: v for k, v in metric.items() if v is not None})
        m.setdefault("attempts_log", []).append(entry)
        self._write_manifest(m)

    def _touch_manifest(self, name: str, kind: str, fname: str) -> None:
        m = self.manifest()
        m.setdefault("artifacts", {})[name] = {
            "kind": kind, "file": fname, "ts": time.time()}
        self._write_manifest(m)

    def _write_manifest(self, m: dict) -> None:
        self._manifest_path.write_text(
            json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class RunStore:
    def __init__(self, repo: str):
        self.root = Path(repo).resolve() / ".sembl" / "runs"

    def new_run(self, task=None) -> Run:
        run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        run = Run(self.root, run_id)
        m = {"id": run_id, "created": time.time(), "status": "started",
             "artifacts": {}}
        if task is not None:
            m["task"] = {"text": getattr(task, "text", ""),
                         "repo": getattr(task, "repo", "")}
        run._write_manifest(m)
        return run

    def open(self, run_id: str) -> Run:
        # A run id is a single directory name under .sembl/runs — never a path. Rejecting
        # separators/leading dots here keeps `runs <id>` / `apply <id>` from resolving
        # (and mkdir-ing) outside the store via a crafted id like `..\\..\\evil`.
        if not _RUN_ID.match(run_id):
            raise ValueError(f"invalid run id: {run_id!r}")
        return Run(self.root, run_id)

    def list_runs(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted((p.name for p in self.root.iterdir() if p.is_dir()), reverse=True)
