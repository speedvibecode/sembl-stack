"""The platform contract.

These dataclasses + Protocols are the *only* thing every layer must agree on.
An adapter is anything that satisfies one of the Protocols below — that's what makes
each layer swappable without touching the rest of the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


# --- Data that flows between layers --------------------------------------------

@dataclass
class Task:
    """What the user wants. `repo` is the target working copy."""
    text: str
    repo: str
    spec_path: str | None = None      # a Spec Kit tasks.md / feature dir, if any


@dataclass
class Bounds:
    """The governed scope of a change — the four-field contract Sembl verifies."""
    editable_paths: list[str] = field(default_factory=list)
    forbidden_areas: list[str] = field(default_factory=list)
    churn_budget: dict = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "editable_paths": self.editable_paths,
            "forbidden_areas": self.forbidden_areas,
            "churn_budget": self.churn_budget,
        }


@dataclass
class ExecutionResult:
    """What the executor produced, in the sandbox."""
    diff: str                          # unified diff of the change
    report: dict                       # executor self-report (never trusted by L5)
    workdir: str                       # path the change lives in (the sandbox)


@dataclass
class Verdict:
    """The gate's deterministic answer."""
    status: str                        # PASS | WARN | BLOCK
    reasons: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.status == "BLOCK"

    def feedback(self) -> str:
        """A nudge the executor can act on, on retry."""
        if not self.reasons:
            return ""
        return "Your previous attempt was blocked. Fix these and stay in scope:\n- " + \
            "\n- ".join(self.reasons)


# --- Layer interfaces (Protocols) ---------------------------------------------

class Sandbox(Protocol):              # an open sandbox handle (from L4)
    workdir: str
    def diff(self) -> str: ...
    def close(self) -> None: ...


@runtime_checkable
class SpecAdapter(Protocol):         # L2
    def plan(self, task: Task) -> Bounds: ...


@runtime_checkable
class SandboxAdapter(Protocol):      # L4
    def open(self, repo: str) -> Sandbox: ...


@runtime_checkable
class ExecuteAdapter(Protocol):      # L3
    def run(self, task: Task, bounds: Bounds, sandbox: Sandbox,
            feedback: str | None) -> ExecutionResult: ...


@runtime_checkable
class VerifyAdapter(Protocol):       # L5
    def verify(self, bounds: Bounds, result: ExecutionResult,
               strict: bool) -> Verdict: ...
