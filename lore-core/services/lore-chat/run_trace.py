"""Turn a LangGraph ``updates`` stream into a clean node -> tool-calls trace.

Replaces Chainlit's default LangchainTracer (which emits a noisy step per internal
run) with a two-level view: one step per graph node, and under it the node's tool
calls with their arguments and results. Pure logic lives here (testable); the
Chainlit ``cl.Step`` rendering stays in ``app.py``.

Tool calls span two nodes — the model node emits an ``AIMessage`` carrying
``tool_calls`` (name + args), the tools node emits ``ToolMessage``s (results,
keyed by ``tool_call_id``). ``ToolCallTracker`` remembers pending calls and
resolves each one when its result arrives, so the caller can render the tool
under the node where it completed.
"""
from typing import Any


def content_to_text(content: Any) -> str:
    """Flatten LangChain message content (str | list of parts) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                parts.append(str(p.get("text", p)))
            else:
                parts.append(str(p))
        return "\n".join(parts)
    return str(content)


class ToolCallTracker:
    """Accumulates tool-call args across nodes and resolves them on result."""

    def __init__(self) -> None:
        self._pending: dict[str, dict] = {}

    def observe(self, messages: list) -> list[dict]:
        """Record any tool calls in ``messages`` and return the ones resolved by a
        result in this same batch: ``[{name, args, result}]`` (in result order)."""
        resolved: list[dict] = []
        for m in messages or []:
            for tc in getattr(m, "tool_calls", None) or []:
                tcid = tc.get("id")
                if tcid:
                    self._pending[tcid] = {"name": tc.get("name", ""), "args": tc.get("args", {})}
            tcid = getattr(m, "tool_call_id", None)
            if tcid is not None:
                call = self._pending.pop(tcid, {})
                resolved.append(
                    {
                        "name": call.get("name") or getattr(m, "name", None) or "tool",
                        "args": call.get("args", {}),
                        "result": content_to_text(getattr(m, "content", "")),
                    }
                )
        return resolved


def iter_node_updates(payload: Any):
    """Yield ``(node_name, messages)`` from one LangGraph ``updates`` payload.

    Shape is ``{node_name: {"messages": [...], ...}}`` (possibly several nodes).
    Non-dict payloads / nodes without messages yield an empty message list."""
    if not isinstance(payload, dict):
        return
    for node_name, delta in payload.items():
        messages = delta.get("messages", []) if isinstance(delta, dict) else []
        yield node_name, messages
