"""Phase-0 guided-session pointer over the run store.

A tiny `.sembl/session.json` `{repo, mode, run_id, current_stage, completed}` is what makes the
guided `sembl-stack` TUI leave/continue-anywhere: it points at a run in the existing store and
records which stage the user reached. Pure and headless — unit-testable without Textual; the
wizard only renders and advances it.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# The Phase-0 stage rail (CI-run-page order). Only stages that are already headless.
STAGES = ["bounds", "loop", "verify", "merge", "deploy", "postdeploy"]


@dataclass
class Session:
    repo: str = "."
    mode: str = "existing"            # "new" | "existing"
    run_id: str | None = None
    current_stage: str = STAGES[0]
    completed: list[str] = field(default_factory=list)

    def advance(self) -> str:
        """Mark the current stage complete and move to the next; return the new current stage."""
        if self.current_stage not in self.completed:
            self.completed.append(self.current_stage)
        i = STAGES.index(self.current_stage)
        if i + 1 < len(STAGES):
            self.current_stage = STAGES[i + 1]
        return self.current_stage

    @property
    def done(self) -> bool:
        return all(s in self.completed for s in STAGES)


def _path(repo: str) -> Path:
    return Path(repo).resolve() / ".sembl" / "session.json"


def save(session: Session) -> Path:
    p = _path(session.repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(session), indent=2), encoding="utf-8")
    return p


def load(repo: str) -> "Session | None":
    p = _path(repo)
    if not p.is_file():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return Session(**{k: v for k, v in data.items() if k in Session.__dataclass_fields__})


def resume_or_new(repo: str) -> Session:
    """Resume the saved session if it exists and is incomplete; else a fresh session.

    This is the "continue anywhere" entry point: an incomplete saved session is the latest
    point the user reached, so the wizard reopens there. A missing or finished session starts
    fresh at the first stage.
    """
    existing = load(repo)
    if existing is not None and not existing.done:
        return existing
    return Session(repo=str(Path(repo).resolve()))
