"""Langfuse tracing for the grounded pipeline — service-side only.

Langfuse-specific code lives here (the pure ``lore-retrieval`` package stays
vendor-free and is traced solely through its ``observability.Tracer`` seam). The
seam docstring anticipates this adapter: each pipeline stage record becomes a
Langfuse event under the current turn's trace, carrying only bounded fields
(counts, ids, degraded flags, error detail) — never canonical content.

The SDK binding is isolated in ``build_langfuse_tracer`` so:
* the module imports without ``langfuse`` installed (import is lazy);
* the mapping logic (``LangfuseTracer.record``) is offline-testable via an
  injected ``emit`` callable, with no live client.
"""
import os
from typing import Callable


class LangfuseTracer:
    """``observability.Tracer`` impl forwarding each stage record to an ``emit``
    callable (bound to Langfuse in ``build_langfuse_tracer``; a fake in tests).
    Tracing must never break the pipeline, so emit failures are swallowed."""

    def __init__(self, emit: Callable[[str, dict], None]) -> None:
        self._emit = emit

    def record(self, stage: str, payload: dict) -> None:
        try:
            self._emit(stage, dict(payload))
        except Exception:
            return


def _langfuse_emit(client: object) -> Callable[[str, dict], None]:
    """Bind a Langfuse client to the ``emit`` signature. Targets langfuse v3
    ``create_event`` (auto-nests under the active observation), falling back to a
    ``event`` method; each stage record becomes one event. Version-tolerant and
    best-effort — LIVE-VERIFY that spans appear once creds are set."""

    def emit(stage: str, data: dict) -> None:
        fn = getattr(client, "create_event", None) or getattr(client, "event", None)
        if fn is None:
            return
        fn(name=stage, metadata=data)

    return emit


def build_langfuse_tracer() -> LangfuseTracer | None:
    """Build a ``LangfuseTracer`` from env (``LANGFUSE_PUBLIC_KEY`` /
    ``LANGFUSE_SECRET_KEY`` / optional ``LANGFUSE_HOST``), or ``None`` when creds are
    missing or ``langfuse`` is not installed — the pipeline then runs untraced by
    Langfuse (the in-UI ContextTracer is unaffected). Env-only, mirroring
    ``langsmith_tracing.enable_langsmith``: no lore-chat config import here."""
    public = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret = os.environ.get("LANGFUSE_SECRET_KEY")
    if not (public and secret):
        return None
    try:
        from langfuse import Langfuse
    except Exception:
        return None
    host = os.environ.get("LANGFUSE_HOST")
    kwargs = {"public_key": public, "secret_key": secret}
    if host:
        kwargs["host"] = host
    try:
        client = Langfuse(**kwargs)
    except Exception:
        return None
    return LangfuseTracer(_langfuse_emit(client))
