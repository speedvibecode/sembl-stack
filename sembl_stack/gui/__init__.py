"""The graphical dashboard surface (O7, relocked 2026-07-05).

A local FastAPI+WebSocket server over the SAME deterministic cores `guide.py`'s
inline CLI already drives (profile.py, runner.py, the gate) — this package only
renders and streams; it makes zero decisions of its own. See `server.py`.
"""
from __future__ import annotations
