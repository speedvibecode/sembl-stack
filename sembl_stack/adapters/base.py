"""The platform contract.

The data types are the canonical artifacts (see `sembl_stack/artifacts.py`); the
Protocols below are what an adapter must satisfy to be swappable into a layer. Re-exported
here so adapters import everything they need from one place.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..artifacts import (  # noqa: F401  (re-exported for adapters)
    Bounds,
    Change,
    Context,
    Delivery,
    ExecutionResult,
    Task,
    Trace,
    Verdict,
)


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
