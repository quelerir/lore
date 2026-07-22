"""HTTP cross-encoder reranker adapter — offline (fake client / pure parser).

Live-verify against the real bge-reranker server separately (endpoint contract).
"""
from lore_retrieval.adapters.rerank_http import (
    HttpReranker,
    build_reranker,
    parse_rerank_response,
)


def test_parse_tei_list_shape_sorts_desc_and_maps_ids():
    ids = ["a", "b", "c"]
    # TEI-style: a list of {index, score}, not necessarily sorted.
    payload = [{"index": 2, "score": 0.1}, {"index": 0, "score": 0.9}, {"index": 1, "score": 0.5}]
    assert parse_rerank_response(payload, ids) == [("a", 0.9), ("b", 0.5), ("c", 0.1)]


def test_parse_results_envelope_shape():
    ids = ["a", "b"]
    payload = {"results": [{"index": 1, "score": 0.8}, {"index": 0, "score": 0.2}]}
    assert parse_rerank_response(payload, ids) == [("b", 0.8), ("a", 0.2)]


def test_parse_ignores_out_of_range_index():
    assert parse_rerank_response([{"index": 9, "score": 1.0}, {"index": 0, "score": 0.3}], ["a"]) == [
        ("a", 0.3)
    ]


def test_parse_empty():
    assert parse_rerank_response([], ["a"]) == []


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.captured = None

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def post(self, url, json):
        self.calls.append((url, json))
        return _FakeResp(self._payload)


async def test_http_reranker_ranks_and_caps_top_k():
    client = _FakeClient([{"index": 0, "score": 0.9}, {"index": 1, "score": 0.2}])
    r = HttpReranker("http://rr:8080", client=client)
    out = await r.rerank("оклад", [("a", "текст a"), ("b", "текст b")], top_k=1)
    assert out == [("a", 0.9)]
    url, body = client.calls[0]
    assert url == "http://rr:8080/rerank"
    assert body == {"query": "оклад", "texts": ["текст a", "текст b"]}


async def test_http_reranker_empty_docs_short_circuits():
    client = _FakeClient([])
    assert await HttpReranker("http://rr:8080", client=client).rerank("q", [], top_k=5) == []
    assert client.calls == []


def test_build_reranker_none_without_endpoint():
    assert build_reranker("") is None
    assert build_reranker(None) is None
