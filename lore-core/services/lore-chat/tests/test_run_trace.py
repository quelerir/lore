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


def test_iter_node_updates_yields_node_and_messages():
    payload = {"tools": {"messages": [HumanMessage(content="x")]}}
    assert [(n, len(m)) for n, m in iter_node_updates(payload)] == [("tools", 1)]
    assert list(iter_node_updates("not-a-dict")) == []
