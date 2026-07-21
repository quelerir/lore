"""Throwaway (P0 Task 5): probe the external Neo4j for edition/version/capabilities.

Run: uv run python spikes/probe_capabilities.py   (needs RETRIEVAL_NEO4J_* env)
Untested until creds are available.
"""
from neo4j import GraphDatabase

from lore_retrieval.config import get_settings


def main() -> None:
    s = get_settings()
    driver = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
    with driver.session(database=s.neo4j_database) as sess:
        comp = sess.run(
            "CALL dbms.components() YIELD name, versions, edition "
            "RETURN name, versions, edition"
        ).data()
        print("components:", comp)

        procs = sess.run(
            "SHOW PROCEDURES YIELD name "
            "WHERE name IN ['db.index.vector.queryNodes', 'db.index.fulltext.queryNodes'] "
            "RETURN collect(name) AS available"
        ).single()["available"]
        print("index procs available:", procs)

        try:
            dbs = sess.run(
                "SHOW DATABASES YIELD name RETURN collect(name) AS names"
            ).single()["names"]
            print("databases visible:", dbs)
        except Exception as e:  # Community may restrict SHOW DATABASES
            print("SHOW DATABASES not available:", e)
    driver.close()


if __name__ == "__main__":
    main()
