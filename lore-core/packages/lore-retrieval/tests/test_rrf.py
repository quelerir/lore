from lore_retrieval.neo4j_spike import rrf_fuse


def test_rrf_dedups_and_rewards_agreement():
    vector = [("a", 0.9), ("b", 0.8), ("c", 0.7)]
    fulltext = [("b", 5.0), ("a", 4.0), ("d", 3.0)]
    fused = rrf_fuse([vector, fulltext])
    ids = [cid for cid, _ in fused]
    assert set(ids) == {"a", "b", "c", "d"}          # deduped union
    assert ids[0] in {"a", "b"}                       # agreed items rank first
    assert ids.index("a") < ids.index("c")            # a (in both) beats c (in one)
