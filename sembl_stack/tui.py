"""O6 — the in-terminal run dashboard (CI-run-page UX), built on Textual.

Optional by design: Textual is an extra (`pip install "sembl-stack[tui]"`). If it isn't
installed, `available()` is False and the CLI prints an actionable hint instead of crashing —
the same degrade-don't-fail stance as the LangGraph fallback. The data comes from the shared
`views` layer, so the dashboard shows exactly what `sembl-stack runs` shows, live-refreshed.
"""
from __future__ import annotations

from . import views

try:
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal
    from textual.widgets import DataTable, Footer, Header, Static
    _HAVE_TEXTUAL = True
except ImportError:                      # textual not installed — degrade gracefully
    _HAVE_TEXTUAL = False


def available() -> bool:
    return _HAVE_TEXTUAL


def run_dashboard(store, refresh_s: float = 3.0) -> None:
    """Launch the live dashboard. Caller must check `available()` first."""
    if not _HAVE_TEXTUAL:
        raise RuntimeError("textual not installed — `pip install \"sembl-stack[tui]\"`")
    RunsDashboard(store, refresh_s).run()


if _HAVE_TEXTUAL:

    class RunsDashboard(App):
        """A two-pane dashboard: a table of runs + the highlighted run's detail."""

        TITLE = "sembl-stack — runs"
        BINDINGS = [("q", "quit", "Quit"), ("r", "reload", "Reload")]
        CSS = """
        DataTable { width: 60%; }
        #detail { width: 40%; padding: 0 1; border-left: solid $accent; }
        """

        def __init__(self, store, refresh_s: float = 3.0):
            super().__init__()
            self._store = store
            self._refresh_s = refresh_s

        def compose(self) -> "ComposeResult":
            yield Header()
            with Horizontal():
                yield DataTable(id="runs", cursor_type="row")
                yield Static("select a run", id="detail")
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#runs", DataTable)
            table.add_columns("run", "status", "att", "latency", "task")
            self._reload()
            if self._refresh_s:
                self.set_interval(self._refresh_s, self._reload)

        def action_reload(self) -> None:
            self._reload()

        def _reload(self) -> None:
            table = self.query_one("#runs", DataTable)
            keep = table.cursor_row
            table.clear()
            for r in views.list_rows(self._store):
                task = (r["task"][:48] + "…") if len(r["task"]) > 49 else r["task"]
                table.add_row(r["id"], r["status"], str(r["attempts"]),
                              r["latency"], task, key=r["id"])
            if table.row_count:
                table.move_cursor(row=min(keep, table.row_count - 1))
                self._show(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)

        def on_data_table_row_highlighted(self, event) -> None:
            self._show(event.row_key.value)

        def _show(self, run_id) -> None:
            if not run_id:
                return
            lines = views.detail_lines(self._store, run_id)
            self.query_one("#detail", Static).update(
                "\n".join(lines) if lines else "no detail")
