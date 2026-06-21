"""Phase-0 guided surface — the bare-`sembl-stack` Textual wizard (O6, elevates C4).

A thin guide over the artifact-first machinery: a New/Existing choice, a stage rail
(CI-run-page UX), and leave/continue-anywhere resume via the `session.json` pointer (see
`session.py`). It adds NO core/gate logic — the rail shells the same headless stage functions
the CLI does. Textual is an extra (`pip install "sembl-stack[tui]"`); if it isn't installed,
`available()` is False and the caller prints an actionable hint instead of crashing.
"""
from __future__ import annotations

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


def _rail_text(s: Session) -> str:
    """The stage rail as plain text: [x] done, [>] current, [ ] pending."""
    lines = [f"repo: {s.repo}", f"mode: {s.mode}", ""]
    for stage in STAGES:
        mark = "x" if stage in s.completed else (">" if stage == s.current_stage else " ")
        lines.append(f"  [{mark}] {stage}")
    if s.done:
        lines.append("\n  all stages complete.")
    return "\n".join(lines)


if _HAVE_TEXTUAL:

    class StackWizard(App):
        """Bare-`sembl-stack` guided wizard: New/Existing + stage rail + session resume."""

        TITLE = "sembl-stack"
        SUB_TITLE = "guided run"
        BINDINGS = [
            ("q", "quit", "Quit"),
            ("n", "mode_new", "New repo"),
            ("e", "mode_existing", "Existing repo"),
            ("space", "advance", "Advance stage"),
        ]
        CSS = """
        #mode { width: 30%; padding: 1; border-right: solid $accent; }
        #rail { width: 70%; padding: 1; }
        Button { width: 100%; margin: 0 0 1 0; }
        """

        def __init__(self, repo: str = ".", session: "Session | None" = None):
            super().__init__()
            self._session = session or resume_or_new(repo)

        def compose(self) -> "ComposeResult":
            yield Header()
            with Horizontal():
                with Vertical(id="mode"):
                    yield Static("New or existing?", id="mode-label")
                    yield Button("New repo", id="mode-new", variant="primary")
                    yield Button("Existing repo", id="mode-existing")
                yield Static(_rail_text(self._session), id="rail")
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

        def _refresh(self) -> None:
            self.query_one("#rail", Static).update(_rail_text(self._session))
