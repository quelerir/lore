"""Observability seam for the pipeline.

A minimal per-stage tracer the pipeline calls at each boundary. The default is a
no-op; the real Langfuse adapter (added when the chat service wires Langfuse)
maps these records to spans/observations under ``project_id="loreagent"``.
Payloads carry only safe bounded fields (counts, ids, latency) — never full
canonical content or secrets.
"""
from typing import Protocol, runtime_checkable


@runtime_checkable
class Tracer(Protocol):
    def record(self, stage: str, payload: dict) -> None: ...


class NullTracer:
    """Default: records nothing."""

    def record(self, stage: str, payload: dict) -> None:
        return None


class RecordingTracer:
    """Collects records in memory (tests, and a basis for the Langfuse adapter)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def record(self, stage: str, payload: dict) -> None:
        self.events.append((stage, dict(payload)))

    def stages(self) -> list[str]:
        return [stage for stage, _ in self.events]
