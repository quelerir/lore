from __future__ import annotations

from pathlib import Path

MIGRATION_DIR = Path(__file__).with_name("migrations")


def migration_sql(version: str = "001_lore_core") -> str:
    path = MIGRATION_DIR / f"{version}.sql"
    if not path.is_file():
        raise ValueError(f"unknown core migration: {version}")
    return path.read_text(encoding="utf-8")


def apply_migration(connection, *, version: str = "001_lore_core") -> None:
    """Apply schema setup explicitly; this is never called by a file task."""
    cursor = connection.cursor()
    try:
        cursor.execute(migration_sql(version))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
