"""Guided surface — the bare-`sembl-stack` Textual wizard (O6, elevates C4).

Phase 0: a New/Existing choice, a stage rail (CI-run-page UX), and leave/continue-anywhere
resume via the `session.json` pointer (see `session.py`).

Phase 2: the stage rail actually RUNS the loop under the configured profile — press `r`
and the real `loop.run` (plan -> execute -> verify, retry-on-BLOCK) executes in a worker
thread against the repo's `task.yaml`, streaming per-stage status (pending/running/pass/
fail) into the rail and showing the final verdict panel. The orchestration glue is
`runner.py` (pure, headless); the wizard only renders its events — it adds NO core/gate
logic, so a TUI run and a headless `sembl-stack loop` run are byte-identical.

Deliberately NOT in Phase 2 (see docs/PROCESS-ACTION-PLAN.md §9 Track 2 item 5):
  TODO(plan §9.5): CBM `index_repository` trigger on the Existing-repo path.
  TODO(plan §9.5): reconcile (S9) advisory panel.
  TODO(plan §9.5): live deploy/postdeploy panels + MurphyScan readiness screen.

Textual is an extra (`pip install "sembl-stack[tui]"`); if it isn't installed,
`available()` is False and the caller prints an actionable hint instead of crashing.
"""
from __future__ import annotations

from . import runner
from .session import STAGES, Session, resume_or_new, save

try:
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Button, Footer, Header, Static
    _HAVE_TEXTUAL = True
except ImportError:                      # textual not installed — degrade gracefully
    _HAVE_TEXTUAL = False


def available() -> bool:
    return _HAVE_TEXTUAL


def launch(repo: str = ".") -> None:
    """Launch the guided wizard. Caller must check `available()` first."""
    if not _HAVE_TEXTUAL:
        raise RuntimeError("textual not installed — `pip install \"sembl-stack[tui]\"`")
    StackWizard(repo=repo).run()


# Live-run stage marks (Phase 2), layered over the session marks (Phase 0).
_LIVE_MARK = {"running": "~", "done": "x", "fail": "!"}


def _rail_text(s: Session, live: dict | None = None) -> str:
    """The stage rail as plain text: [x] done, [>] current, [ ] pending;
    live-run states win: [~] running, [!] failed."""
    live = live or {}
    lines = [f"repo: {s.repo}", f"mode: {s.mode}", ""]
    for stage in STAGES:
        if stage in live:
            mark = _LIVE_MARK.get(live[stage]["state"], "?")
            detail = live[stage].get("detail", "")
            suffix = f"  ({detail})" if detail else ""
        else:
            mark = "x" if stage in s.completed else (">" if stage == s.current_stage else " ")
            suffix = ""
        lines.append(f"  [{mark}] {stage}{suffix}")
    if s.done:
        lines.append("\n  all stages complete.")
    return "\n".join(lines)


def _verdict_text(result) -> str:
    """The final-verdict panel line(s) for a finished live run."""
    v = result.verdict
    lines = [f"FINAL: {v.status}  (after {result.attempts} attempt(s))"]
    for r in getattr(v, "reasons", []) or []:
        lines.append(f"  - {r}")
    if result.run_id:
        lines.append(f"run: {result.run_id}  (.sembl/runs/{result.run_id}/)")
    return "\n".join(lines)


if _HAVE_TEXTUAL:

    class StackWizard(App):
        """Bare-`sembl-stack` guided wizard: New/Existing + stage rail + session resume
        + Phase-2 live run (`r` runs task.yaml through the real loop)."""

        TITLE = "sembl-stack"
        SUB_TITLE = "guided run"
        BINDINGS = [
            ("q", "quit", "Quit"),
            ("n", "mode_new", "New repo"),
            ("e", "mode_existing", "Existing repo"),
            ("space", "advance", "Advance stage"),
            ("r", "run_loop", "Run task.yaml"),
        ]
        CSS = """
        #mode { width: 30%; padding: 1; border-right: solid $accent; }
        #right { width: 70%; }
        #rail { padding: 1; height: auto; }
        #verdict { padding: 1; height: auto; color: $text-muted; }
        Button { width: 100%; margin: 0 0 1 0; }
        """

        def __init__(self, repo: str = ".", session: "Session | None" = None):
            super().__init__()
            self._session = session or resume_or_new(repo)
            self._live: dict = {}          # stage -> {"state", "detail"} during a live run
            self._loop_running = False

        def compose(self) -> "ComposeResult":
            yield Header()
            with Horizontal():
                with Vertical(id="mode"):
                    yield Static("New or existing?", id="mode-label")
                    yield Button("New repo", id="mode-new", variant="primary")
                    yield Button("Existing repo", id="mode-existing")
                with Vertical(id="right"):
                    yield Static(_rail_text(self._session), id="rail")
                    yield Static("", id="verdict")
            yield Footer()

        # -- actions ------------------------------------------------------------
        def _set_mode(self, mode: str) -> None:
            self._session.mode = mode
            save(self._session)
            self._refresh()

        def action_mode_new(self) -> None:
            self._set_mode("new")

        def action_mode_existing(self) -> None:
            self._set_mode("existing")

        def action_advance(self) -> None:
            self._session.advance()
            save(self._session)
            self._refresh()

        def on_button_pressed(self, event) -> None:
            if event.button.id == "mode-new":
                self._set_mode("new")
            elif event.button.id == "mode-existing":
                self._set_mode("existing")

        # -- Phase 2: run the real loop under the profile ------------------------
        def action_run_loop(self) -> None:
            if self._loop_running:
                self._note("a run is already in progress…")
                return
            task = runner.load_task(self._session.repo)
            if task is None:
                self._note(f"no task.yaml in {self._session.repo} — "
                           "`sembl-stack init` scaffolds one.")
                return
            cfg = runner.resolve_config(self._session.repo)
            self._loop_running = True
            self._live = {}
            self._note("running…  (plan -> execute -> verify)")
            self._refresh()
            self.run_worker(self._run_loop_async(cfg, task), exclusive=True)

        async def _run_loop_async(self, cfg, task) -> None:
            """Run the blocking loop in an executor; drain stage events on the app's
            own event loop via a thread-safe queue.

            The loop's stage functions call `emit` from the executor thread, so `emit`
            only enqueues (thread-safe, non-blocking) — every UI mutation happens here,
            on the app thread. This deliberately avoids `call_from_thread`, whose
            blocking round-trip deadlocks a threaded worker under Textual's `run_test`
            harness (the pilot drives the loop, so the worker's blocked wait never
            resolves)."""
            import asyncio
            import queue as _queue

            events: "_queue.Queue" = _queue.Queue()

            def emit(ev) -> None:
                events.put(("event", ev))

            def blocking() -> None:
                try:
                    events.put(("done", runner.run_stages(cfg, task, emit)))
                except Exception as exc:          # loop crash (plan/verify raised)
                    events.put(("crash", exc))

            loop = asyncio.get_running_loop()
            fut = loop.run_in_executor(None, blocking)
            terminal = None
            while terminal is None:
                try:
                    kind, payload = events.get_nowait()
                except _queue.Empty:
                    await asyncio.sleep(0.02)
                    continue
                if kind == "event":
                    self._on_stage_event(payload)
                else:
                    terminal = (kind, payload)
            await fut                             # surface any executor teardown error
            if terminal[0] == "done":
                self._on_run_done(terminal[1])
            else:
                self._on_run_crashed(terminal[1])

        def _on_stage_event(self, ev) -> None:
            self._live[ev.stage] = {"state": ev.state, "detail": ev.detail}
            self._refresh()

        def _on_run_done(self, result) -> None:
            self._loop_running = False
            if result.verdict.status in ("PASS", "WARN"):
                # The loop-backed stages are genuinely complete — record the resume
                # pointer just past them (leave/continue-anywhere, Phase 0 semantics).
                for stage in ("bounds", "loop", "verify"):
                    if stage not in self._session.completed:
                        self._session.completed.append(stage)
                self._session.current_stage = "merge"
                self._session.run_id = result.run_id
                save(self._session)
            self._note(_verdict_text(result))
            self._refresh()

        def _on_run_crashed(self, exc: Exception) -> None:
            self._loop_running = False
            self._note(f"run crashed: {exc!r}")
            self._refresh()

        # -- rendering ------------------------------------------------------------
        def _note(self, text: str) -> None:
            self.query_one("#verdict", Static).update(text)

        def _refresh(self) -> None:
            self.query_one("#rail", Static).update(
                _rail_text(self._session, self._live))
