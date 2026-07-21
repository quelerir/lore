from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    ACTIVE = "active"
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"
    STALE = "stale"
