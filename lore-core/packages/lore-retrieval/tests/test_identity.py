from lore_retrieval.identity import projection_id, section_id, section_prefixes


def test_projection_id_joins_version_and_canonical():
    assert projection_id("v3", "chunk_abc") == "v3:chunk_abc"


def test_section_prefixes_lists_every_prefix_shallowest_first():
    assert section_prefixes(("Root", "Child", "Sub")) == [
        ("Root",),
        ("Root", "Child"),
        ("Root", "Child", "Sub"),
    ]


def test_section_prefixes_empty_path_is_empty():
    assert section_prefixes(()) == []


def test_section_id_is_deterministic_and_path_sensitive():
    a = section_id("doc1", ("Root", "Child"))
    b = section_id("doc1", ("Root", "Child"))
    c = section_id("doc1", ("Root",))
    d = section_id("doc2", ("Root", "Child"))
    assert a == b
    assert a != c
    assert a != d
