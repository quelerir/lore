"""Langfuse tracer adapter — offline (fake emit / no creds). Live-verify separately."""
from langfuse_tracing import LangfuseTracer, build_langfuse_tracer


def test_langfuse_tracer_forwards_stage_and_payload():
    seen: list[tuple[str, dict]] = []
    LangfuseTracer(lambda stage, data: seen.append((stage, data))).record(
        "arbitration", {"used_sql": 2}
    )
    assert seen == [("arbitration", {"used_sql": 2})]


def test_langfuse_tracer_copies_payload_defensively():
    seen: list[tuple[str, dict]] = []
    tracer = LangfuseTracer(lambda stage, data: seen.append((stage, data)))
    payload = {"fused": 3}
    tracer.record("text_fanout", payload)
    payload["fused"] = 999                       # mutating the caller's dict
    assert seen[0][1] == {"fused": 3}            # the recorded copy is unaffected


def test_langfuse_tracer_swallows_emit_failure():
    def boom(_stage, _data):
        raise RuntimeError("langfuse down")

    # Tracing must never break the pipeline.
    LangfuseTracer(boom).record("cite", {"citations": 1})


def test_build_langfuse_tracer_is_none_without_creds(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert build_langfuse_tracer() is None
