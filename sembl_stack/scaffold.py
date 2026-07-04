"""Demo/starter scaffolding shared by `init` (CLI) and the guided TUI.

One place owns "make this directory loop-runnable": the starter config/task/bounds
files, and — for a fresh non-git directory — a demo app module plus a git repo with a
first commit (the clone sandbox needs one). Existing repos and existing files are
always left alone.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import presets


def write_starter_files(root: Path, preset: str = presets.DEFAULT_PRESET,
                        *, force: bool = False, include_config: bool = True) -> list[str]:
    """Write sembl.stack.yaml + task.yaml + bounds.json (skipping existing files
    unless `force`). Returns human-readable messages for whatever was written.
    `include_config=False` when the caller manages the config file itself (init
    with a custom --config path)."""
    files = [("task.yaml", presets.starter_task()),
             ("bounds.json", presets.starter_bounds())]
    if include_config:
        files.insert(0, ("sembl.stack.yaml", presets.render(preset)))
    msgs = []
    for name, content in files:
        target = root / name
        if target.exists() and not force:
            continue
        target.write_text(content, encoding="utf-8")
        msgs.append(f"wrote {name}")
    return msgs


def ensure_demo_repo(root: Path) -> list[str]:
    """Make `root` loop-runnable: the sandbox clones the repo, so a fresh demo
    directory needs a git repo with at least one commit. Existing repos are left
    entirely alone. Returns human-readable messages."""
    if (root / ".git").exists():
        return []
    msgs = []
    app = root / "app"
    if not app.exists():
        app.mkdir()
        (app / "__init__.py").write_text(
            '"""Demo app module — the starter task adds a constant here."""\n',
            encoding="utf-8")
        msgs.append("wrote app/__init__.py  (demo module the starter task edits)")
    run = lambda cmd: subprocess.run(cmd, cwd=root, capture_output=True, text=True)  # noqa: E731
    run(["git", "init", "-q"])
    run(["git", "add", "-A"])
    committed = run(["git", "commit", "-q", "-m", "sembl-stack demo scaffold"])
    if committed.returncode != 0:       # machine has no git identity configured
        run(["git", "-c", "user.name=sembl-stack", "-c", "user.email=demo@sembl.local",
             "commit", "-q", "-m", "sembl-stack demo scaffold"])
    msgs.append("initialized a git repo + first commit  (the sandbox clones it)")
    return msgs


def scaffold_demo(root: Path, preset: str = presets.DEFAULT_PRESET) -> list[str]:
    """The full demo scaffold: starter files + a committed git repo."""
    root.mkdir(parents=True, exist_ok=True)
    return write_starter_files(root, preset) + ensure_demo_repo(root)
