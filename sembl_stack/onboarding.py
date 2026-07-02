"""Phase-1 first-run onboarding TUI for the BYO profile.

This module is a thin Textual guide over `profile.py`: welcome, choose how model
calls are paid for, capture a few preferences, persist `~/.sembl/profile.json`,
then return control to the Phase-0 stage rail. It is deliberately tolerant of bad
state and keeps all credential decisions in the deterministic profile core.
Textual is optional; callers use `available()` before launching.
"""
from __future__ import annotations

import re

from . import presets, profile
from .session import resume_or_new, save as save_session

try:
    from textual.app import App, ComposeResult
    from textual.containers import Vertical
    from textual.widgets import (
        Button,
        Checkbox,
        Collapsible,
        Footer,
        Header,
        Input,
        Select,
        Static,
    )
    _HAVE_TEXTUAL = True
except ImportError:                      # textual not installed - degrade gracefully
    _HAVE_TEXTUAL = False


RUNNER_CHOICES = {
    "claude-login": ("Use my Claude Code login", "claude"),
    "api-key": ("Use my API key", "claude"),
    "local": ("Use a local model", "opencode"),
    "mock": ("Preview the mechanics (no AI)", "mock"),
}

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def available() -> bool:
    return _HAVE_TEXTUAL


def launch(repo: str = ".") -> "profile.Profile | None":
    """Launch first-run onboarding. Caller launches `wizard.launch(repo)` after."""
    if not _HAVE_TEXTUAL:
        raise RuntimeError("textual not installed - `pip install \"sembl-stack[tui]\"`")
    return OnboardingApp(repo=repo).run()


def env_var_options() -> list[str]:
    return list(profile._KEY_ENV_VARS)


def normalize_env_var_name(name: str) -> str:
    cleaned = name.strip()
    if not _ENV_NAME.match(cleaned):
        raise ValueError("enter an environment variable name, not an API key value")
    return cleaned


def api_key_source(selected: str | None, custom: str | None) -> str:
    custom_name = (custom or "").strip()
    name = normalize_env_var_name(custom_name or (selected or ""))
    return f"env:{name}"


def profile_for_runner(
    runner: str,
    *,
    key_env: str | None = None,
    custom_key_env: str | None = None,
    executor: str | None = None,
    model: str | None = None,
    strict: bool = True,
    preset: str | None = None,
) -> profile.Profile:
    """Build a Profile from widget state without reading any API key value."""
    if runner not in RUNNER_CHOICES:
        raise ValueError(f"unknown runner: {runner}")
    default_executor = RUNNER_CHOICES[runner][1]
    key_source = None
    if runner == "api-key":
        key_source = api_key_source(key_env, custom_key_env)
    model = (model or "").strip() or None
    preset = preset or None
    return profile.Profile(
        runner=runner,
        executor=executor or default_executor,
        model=model,
        key_source=key_source,
        strict=strict,
        preset=preset,
    )


def first_fix_hint(candidate: profile.Profile) -> tuple[bool, str]:
    checks = profile.preflight(candidate)
    return profile.ready(checks)


if _HAVE_TEXTUAL:

    class OnboardingApp(App):
        """First-run BYO setup: welcome -> runner choice -> preferences -> profile."""

        TITLE = "sembl-stack"
        SUB_TITLE = "first-run setup"
        BINDINGS = [("q", "quit", "Quit")]
        CSS = """
        #onboarding { padding: 1 2; }
        .screen { display: none; }
        .active { display: block; }
        .choice { width: 100%; margin: 0 0 1 0; }
        #mock-choice { opacity: 70%; }
        #byo-hint { color: $error; margin: 1 0 0 0; }
        #prefs-error { color: $error; margin: 1 0 0 0; }
        Select, Input { margin: 0 0 1 0; }
        Button { margin: 0 1 1 0; }
        """

        def __init__(self, repo: str = "."):
            super().__init__()
            self.repo = repo
            detected = profile.detect()
            self._runner = detected.runner
            self._key_env = (
                detected.key_source.removeprefix("env:")
                if detected.key_source and detected.key_source.startswith("env:")
                else profile._KEY_ENV_VARS[0]
            )

        def compose(self) -> "ComposeResult":
            yield Header()
            with Vertical(id="onboarding"):
                with Vertical(id="welcome-screen", classes="screen active"):
                    yield Static(
                        "sembl-stack puts an accountability gate around an AI coding loop.",
                        id="welcome-copy",
                    )
                    yield Static(
                        "It runs on your own keys, local model, or Claude Code login.",
                        id="keys-copy",
                    )
                    yield Button("Continue", id="welcome-next", variant="primary")

                with Vertical(id="byo-screen", classes="screen"):
                    yield Static("Choose how sembl-stack should run AI work.", id="byo-title")
                    yield Button(RUNNER_CHOICES["claude-login"][0], id="claude-choice", classes="choice")
                    yield Button(RUNNER_CHOICES["api-key"][0], id="api-choice", classes="choice")
                    yield Select(
                        [(name, name) for name in env_var_options()],
                        value=self._key_env if self._key_env in env_var_options() else env_var_options()[0],
                        id="api-env",
                    )
                    yield Input(placeholder="OTHER_API_KEY_ENV", id="api-env-custom")
                    yield Button(RUNNER_CHOICES["local"][0], id="local-choice", classes="choice")
                    yield Button(RUNNER_CHOICES["mock"][0], id="mock-choice", classes="choice")
                    yield Static("", id="byo-hint")

                with Vertical(id="prefs-screen", classes="screen"):
                    yield Static("Preferences", id="prefs-title")
                    yield Select([("Existing repo", "existing"), ("New repo", "new")],
                                 value="existing", id="repo-mode")
                    yield Checkbox("Strict gate", value=True, id="strict")
                    yield Select([("No preset", "")] + [(name, name) for name in presets.names()],
                                 value="", id="preset")
                    with Collapsible(title="Advanced", collapsed=True, id="advanced"):
                        yield Select([(name, name) for name in ("claude", "opencode", "aider", "mock")],
                                     value=RUNNER_CHOICES[self._runner][1], id="executor")
                        yield Input(placeholder="Model (optional)", id="model")
                    yield Button("Go", id="finish", variant="primary")
                    yield Static("", id="prefs-error")
            yield Footer()

        def on_mount(self) -> None:
            self._mark_selected()

        def on_button_pressed(self, event) -> None:
            button_id = event.button.id
            if button_id == "welcome-next":
                self._show("byo")
            elif button_id in {"claude-choice", "api-choice", "local-choice", "mock-choice"}:
                runner = {
                    "claude-choice": "claude-login",
                    "api-choice": "api-key",
                    "local-choice": "local",
                    "mock-choice": "mock",
                }[button_id]
                self._choose_runner(runner)
            elif button_id == "finish":
                self._finish()

        def _show(self, name: str) -> None:
            for screen_id in ("welcome-screen", "byo-screen", "prefs-screen"):
                screen = self.query_one(f"#{screen_id}")
                screen.remove_class("active")
            self.query_one(f"#{name}-screen").add_class("active")

        def _choose_runner(self, runner: str) -> None:
            self._runner = runner
            self._mark_selected()
            try:
                candidate = self._candidate_from_inputs()
            except ValueError as exc:
                self.query_one("#byo-hint", Static).update(str(exc))
                return
            ok, hint = first_fix_hint(candidate)
            if not ok:
                self.query_one("#byo-hint", Static).update(hint)
                return
            self.query_one("#byo-hint", Static).update("")
            self.query_one("#executor", Select).value = candidate.executor
            self._show("prefs")

        def _finish(self) -> None:
            try:
                candidate = self._candidate_from_inputs(include_preferences=True)
            except ValueError as exc:
                self.query_one("#prefs-error", Static).update(str(exc))
                return
            ok, hint = first_fix_hint(candidate)
            if not ok:
                self.query_one("#prefs-error", Static).update(hint)
                return
            profile.save(candidate)
            session = resume_or_new(self.repo)
            session.mode = str(self.query_one("#repo-mode", Select).value or "existing")
            save_session(session)
            self.exit(candidate)

        def _candidate_from_inputs(self, *, include_preferences: bool = False) -> profile.Profile:
            key_env = str(self.query_one("#api-env", Select).value or "")
            custom_key_env = self.query_one("#api-env-custom", Input).value
            executor = RUNNER_CHOICES[self._runner][1]
            model = None
            strict = True
            preset = None
            if include_preferences:
                executor = str(self.query_one("#executor", Select).value or executor)
                model = self.query_one("#model", Input).value
                strict = bool(self.query_one("#strict", Checkbox).value)
                preset_value = str(self.query_one("#preset", Select).value or "")
                preset = preset_value or None
            return profile_for_runner(
                self._runner,
                key_env=key_env,
                custom_key_env=custom_key_env,
                executor=executor,
                model=model,
                strict=strict,
                preset=preset,
            )

        def _mark_selected(self) -> None:
            ids = {
                "claude-login": "claude-choice",
                "api-key": "api-choice",
                "local": "local-choice",
                "mock": "mock-choice",
            }
            for runner, button_id in ids.items():
                button = self.query_one(f"#{button_id}", Button)
                button.variant = "primary" if runner == self._runner else "default"
