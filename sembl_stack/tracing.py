"""L6 observability: Langfuse tracing, with a no-op fallback.

`span(name)` is a context manager around each loop node. If Langfuse isn't enabled or
installed, it's a no-op — the loop runs identically, just untraced.
"""
from __future__ import annotations

from contextlib import contextmanager


class _NoopTracer:
    enabled = False

    @contextmanager
    def span(self, name: str, **meta):
        yield None

    def flush(self):
        pass


class _LangfuseTracer:
    enabled = True

    def __init__(self):
        from langfuse import Langfuse
        self._lf = Langfuse()
        self._trace = self._lf.trace(name="sembl-stack-loop")

    @contextmanager
    def span(self, name: str, **meta):
        span = self._trace.span(name=name, metadata=meta or None)
        try:
            yield span
        finally:
            span.end()

    def flush(self):
        try:
            self._lf.flush()
        except Exception:
            pass


def get_tracer(langfuse: bool):
    if not langfuse:
        return _NoopTracer()
    try:
        return _LangfuseTracer()
    except Exception:
        return _NoopTracer()
