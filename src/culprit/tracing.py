"""neatlogs tracing for Culprit (workflow label `culprit`).

Every Culprit command is one WORKFLOW root whose `session_id` is the run_id, so the readback CLI
can find a run's traces with `--session <run_id>` (the read API cannot filter on custom metadata).
A span processor stamps `run_id` and `commit_sha` from context onto every span, including the
LLM spans captured by `neatlogs.wrap()`. Without NEATLOGS_API_KEY, tracing is a no-op.
"""

from __future__ import annotations

import contextvars
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

WORKFLOW = "culprit"
_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("culprit_run_id", default=None)
_commit_sha: contextvars.ContextVar[str | None] = contextvars.ContextVar("culprit_commit_sha", default=None)
_enabled = False


def enabled() -> bool:
    return _enabled


def init() -> None:
    global _enabled
    if _enabled or not os.environ.get("NEATLOGS_API_KEY"):
        return
    import neatlogs
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import SpanProcessor, TracerProvider

    class StampRunContext(SpanProcessor):
        def on_start(self, span: Any, parent_context: Any = None) -> None:
            span.set_attribute("run_id", _run_id.get() or "none")
            span.set_attribute("commit_sha", _commit_sha.get() or "none")

    provider = TracerProvider(resource=Resource.create({"service.name": WORKFLOW, "neatlogs.workflow_name": WORKFLOW}))
    provider.add_span_processor(StampRunContext())
    neatlogs.init(workflow_name=WORKFLOW, tracer_provider=provider)
    _enabled = True


def shutdown() -> None:
    if not _enabled:
        return
    import neatlogs

    neatlogs.flush(timeout_millis=15000)
    neatlogs.shutdown(timeout_millis=15000)


def _json(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)


class Span:
    """Handle for recording a span's output and extra attributes (no-op when tracing is off)."""

    def __init__(self, otel_span: Any = None):
        self._span = otel_span

    def output(self, value: Any) -> None:
        if self._span is not None:
            self._span.set_attribute("output.value", _json(value))
            self._span.set_attribute("output.mime_type", "application/json")

    def set(self, **attrs: Any) -> None:
        if self._span is not None:
            for key, val in attrs.items():
                self._span.set_attribute(key, val if isinstance(val, str | int | float | bool) else _json(val))


@contextmanager
def run_context(run_id: str | None = None, commit_sha: str | None = None) -> Iterator[None]:
    tokens = []
    if run_id is not None:
        tokens.append((_run_id, _run_id.set(run_id)))
    if commit_sha is not None:
        tokens.append((_commit_sha, _commit_sha.set(commit_sha)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


@contextmanager
def span(name: str, kind: str, *, commit_sha: str | None = None, input: Any = None, **attrs: Any) -> Iterator[Span]:
    """A WORKFLOW / AGENT / TOOL span. The WORKFLOW root binds the run_id as the neatlogs session."""
    with run_context(commit_sha=commit_sha):
        if not _enabled:
            yield Span()
            return
        import neatlogs

        session = _run_id.get() if kind == "WORKFLOW" else None
        with neatlogs.trace(name, kind=kind, session_id=session) as otel_span:
            handle = Span(otel_span)
            if input is not None:
                otel_span.set_attribute("input.value", _json(input))
                otel_span.set_attribute("input.mime_type", "application/json")
            handle.set(**attrs)
            yield handle


def current_trace_id() -> str | None:
    """Trace ID of the active span, via the documented W3C traceparent injection."""
    if not _enabled:
        return None
    import neatlogs

    carrier: dict[str, str] = {}
    if neatlogs.inject_trace_context(carrier) and "traceparent" in carrier:
        return carrier["traceparent"].split("-")[1]
    return None


def wrap(client: Any) -> Any:
    if not _enabled:
        return client
    import neatlogs

    return neatlogs.wrap(client, run_id=_run_id.get() or "none", commit_sha=_commit_sha.get() or "none")
