"""Internal connection lease boundary for audit PostgreSQL readers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


@contextmanager
def acquire_postgres_connection(source: Any) -> Iterator[Any]:
    """Acquire from a runtime pool or borrow a caller-managed test connection."""

    acquire = getattr(source, "acquire", None)
    if callable(acquire):
        with acquire() as connection:
            yield connection
        return
    yield source


__all__ = ["acquire_postgres_connection"]
