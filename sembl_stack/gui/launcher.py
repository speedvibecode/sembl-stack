"""Launches the dashboard: the FastAPI server in a background thread, a native
window on top of it via `pywebview` (falls back to the default browser when
`pywebview` isn't installed or `--browser` is passed).
"""
from __future__ import annotations

import threading
import time
import webbrowser


def available() -> bool:
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        return False
    return True


def launch_gui(repo: str = ".", *, port: int = 8765, host: str = "127.0.0.1",
               browser: bool = False) -> None:
    import uvicorn

    from .server import create_app

    app = create_app(repo)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):                     # wait for the socket to actually be up
        if server.started:
            break
        time.sleep(0.05)

    url = f"http://{host}:{port}"
    if not browser:
        try:
            import webview
        except ImportError:
            browser = True                   # pywebview not installed — fall back
    if browser:
        webbrowser.open(url)
        try:
            while thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    else:
        webview.create_window("sembl-stack", url, width=1280, height=820)
        webview.start()
        server.should_exit = True
