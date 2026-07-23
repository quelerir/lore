"""ToolCallTracker: resolve tool calls (args from model node, result from tools node)."""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from run_trace import ToolCallTracker, content_to_text, iter_node_updates


def test_resolves_call_across_nodes_with_args_and_result():
    t = ToolCallTracker()
    # model node: AIMessage proposes a tool call (name + args), no result yet
    ai = AIMessage(content="", tool_calls=[{"id": "c1", "name": "knowledge_base",
                                            "args": {"query": "юристы"}, "type": "tool_call"}])
    assert t.observe([ai]) == []  # nothing resolved on the call itself
    # tools node: ToolMessage carries the result for c1
    tm = ToolMessage(content="Каневский — Помощник Юриста", tool_call_id="c1")
    resolved = t.observe([tm])
    assert resolved == [{"name": "knowledge_base", "args": {"query": "юристы"},
                         "result": "Каневский — Помощник Юриста"}]


def test_unknown_tool_call_id_falls_back_to_message_name():
    t = ToolCallTracker()
    tm = ToolMessage(content="4", tool_call_id="x", name="calculator")
    assert t.observe([tm]) == [{"name": "calculator", "args": {}, "result": "4"}]


def test_content_to_text_flattens_list_parts():
    assert content_to_text("hi") == "hi"
    assert content_to_text([{"type": "text", "text": "a"}, "b"]) == "a\nb"


def test_iter_node_updates_yields_node_messages_and_node_io():
    payload = {"summarize": {"messages": [HumanMessage(content="x")],
                             "node_io": {"input": {"q": 1}, "output": {"answer": "a"}}}}
    got = [(n, len(m), io) for n, m, io in iter_node_updates(payload)]
    assert got == [("summarize", 1, {"input": {"q": 1}, "output": {"answer": "a"}})]
    # node without node_io yields None; non-dict payload yields nothing
    assert [io for _, _, io in iter_node_updates({"tools": {"messages": []}})] == [None]
    assert list(iter_node_updates("not-a-dict")) == []


def test_preview_passes_through_small_and_truncates_large():
    from run_trace import preview
    assert '"n": 1' in preview({"n": 1}, cap=100)
    big = preview({"s": "x" * 500}, cap=50)
    assert len(big) <= 50 + len("\n…(+9999 chars)")
    assert "…(+" in big


def test_preview_survives_non_serializable():
    from run_trace import preview
    assert "object" in preview({"o": object()}, cap=500)  # default=str, no throw


def test_step_io_fields_splits_input_output_entries():
    from run_trace import step_io_fields
    inp, out = step_io_fields({"input": {"q": "x"}, "output": {"answer": "a"}}, cap=200)
    assert inp is not None and '"q": "x"' in inp
    assert '"answer": "a"' in out


def test_step_io_fields_omits_input_when_none():
    from run_trace import step_io_fields
    inp, out = step_io_fields({"input": None, "output": {"n": 1}}, cap=200)
    assert inp is None
    assert '"n": 1' in out


def test_step_io_fields_legacy_entry_renders_whole_data_as_output():
    from run_trace import step_io_fields
    inp, out = step_io_fields({"fused": 5, "degraded": []}, cap=200)
    assert inp is None
    assert '"fused": 5' in out
