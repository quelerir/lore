"""Throwaway (P0 Task 8): compare Lucene analyzers on Russian prose vs exact-code recall.

For each analyzer, drop+recreate the TextChunk fulltext index with that analyzer,
run every case, and report recall@10 per bucket. Requires a projected corpus
(run the Task 6 projection first) and RETRIEVAL_NEO4J_* env. Untested until creds.
"""
import asyncio
from pathlib import Path

import yaml
from neo4j import AsyncGraphDatabase

from lore_retrieval.config import get_settings
from lore_retrieval.neo4j_spike import _labels, fulltext_search

ANALYZERS = ["standard", "standard-no-stop-words", "russian", "whitespace"]


async def recreate_ft_index(driver, database, index_version, analyzer):
    text_label, _ = _labels(index_version)
    name = f"ft_{text_label}"
    async with driver.session(database=database) as sess:
        await sess.run(f"DROP INDEX {name} IF EXISTS")
        await sess.run(
            f"CREATE FULLTEXT INDEX {name} FOR (n:{text_label}) ON EACH [n.fulltext] "
            "OPTIONS { indexConfig: { `fulltext.analyzer`: $analyzer } }",
            analyzer=analyzer,
        )
        await sess.run("CALL db.awaitIndex($name, 120)", name=name)


def recall_at_k(hits: list[str], expected: list[str]) -> float:
    if not expected:
        return 0.0
    return len(set(hits) & set(expected)) / len(set(expected))


async def main():
    s = get_settings()
    cases = yaml.safe_load(Path(__file__).parent.joinpath("cases_ru.yaml").read_text())
    driver = AsyncGraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
    for analyzer in ANALYZERS:
        await recreate_ft_index(driver, s.neo4j_database, "spike1", analyzer)
        report = {}
        for bucket, items in cases.items():
            recalls = []
            for c in items:
                hits = [
                    cid
                    for cid, _ in await fulltext_search(
                        driver, s.neo4j_database, "spike1", c["query"], top_k=10
                    )
                ]
                recalls.append(recall_at_k(hits, c["expect_chunk_ids"]))
            report[bucket] = sum(recalls) / len(recalls) if recalls else 0.0
        print(f"analyzer={analyzer:24s} " + " ".join(f"{b}={r:.2f}" for b, r in report.items()))
    await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
