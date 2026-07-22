"""Observability seam for the pipeline.

A minimal per-stage tracer the pipeline calls at each boundary. The default is a
no-op; the real Langfuse adapter (added when the chat service wires Langfuse)
maps these records to spans/observations under ``project_id="loreagent"``.
Payloads carry only safe bounded fields (counts, ids, latency) — never full
canonical content or secrets.
"""
import contextvars
from typing import Protocol, runtime_checkable

# Per-turn trace sink. The integration layer sets a fresh list in the current
# context before calling ``pipeline.answer``; ``ContextTracer`` appends each stage
# to it. Lets a SINGLETON pipeline emit per-call traces (no shared mutable state).
# Child tasks (text/table lanes run via asyncio.gather) inherit the context copy
# pointing at the SAME list, so their records are visible too.
trace_sink: contextvars.ContextVar[list | None] = contextvars.ContextVar(
    "retrieval_trace_sink", default=None
)


@runtime_checkable
class Tracer(Protocol):
    def record(self, stage: str, payload: dict) -> None: ...


class ContextTracer:
    """Routes stage records to the current context's ``trace_sink`` (no-op when
    unset). Used by the live pipeline so each turn can capture its own trace."""

    def record(self, stage: str, payload: dict) -> None:
        sink = trace_sink.get()
        if sink is not None:
            sink.append({"stage": stage, "data": dict(payload)})


class NullTracer:
    """Default: records nothing."""

    def record(self, stage: str, payload: dict) -> None:
        return None


class CompositeTracer:
    """Fans a stage record out to several tracers (e.g. the per-turn ContextTracer
    that feeds the chat debug view AND a Langfuse sink). A failing child never stops
    the others, and tracing never breaks the pipeline."""

    def __init__(self, tracers: list) -> None:
        self._tracers = list(tracers)

    def record(self, stage: str, payload: dict) -> None:
        for tracer in self._tracers:
            try:
                tracer.record(stage, payload)
            except Exception:
                continue


class RecordingTracer:
    """Collects records in memory (tests, and a basis for the Langfuse adapter)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def record(self, stage: str, payload: dict) -> None:
        self.events.append((stage, dict(payload)))

    def stages(self) -> list[str]:
        return [stage for stage, _ in self.events]
