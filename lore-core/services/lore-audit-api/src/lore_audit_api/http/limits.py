"""Server-owned ceilings for the optional audit HTTP adapter."""

from __future__ import annotations

from dataclasses import dataclass

from lore_audit.read import AuditReadError, ReadBounds


@dataclass(frozen=True)
class AuditHttpLimits:
    """Immutable policy that callers may reduce but never raise."""

    page_size_default: int = 50
    page_size_max: int = 100
    max_text_bytes: int = 1_000_000
    max_batch_size: int = 100
    max_filter_count: int = 8
    max_filter_values: int = 32
    max_complexity: int = 100
    timeout_ms: int = 5_000

    def __post_init__(self) -> None:
        values = (
            self.page_size_default,
            self.page_size_max,
            self.max_text_bytes,
            self.max_batch_size,
            self.max_filter_count,
            self.max_filter_values,
            self.max_complexity,
            self.timeout_ms,
        )
        if (
            any(type(value) is not int or value <= 0 for value in values)
            or self.page_size_default > self.page_size_max
            or self.page_size_max > 10_000
            or self.max_text_bytes > 100_000_000
            or any(value > 10_000 for value in values[3:])
        ):
            raise ValueError("invalid audit HTTP limits")

    def read_bounds(
        self,
        *,
        page_size: int | None = None,
        max_text_bytes: int | None = None,
    ) -> ReadBounds:
        """Build a complete Phase 22 policy using optional caller reductions."""

        selected_page = self.page_size_default if page_size is None else page_size
        selected_text = self.max_text_bytes if max_text_bytes is None else max_text_bytes
        if (
            type(selected_page) is not int
            or not 0 < selected_page <= self.page_size_max
            or type(selected_text) is not int
            or not 0 < selected_text <= self.max_text_bytes
        ):
            raise AuditReadError("bounds_exceeded")
        return ReadBounds(
            page_size=selected_page,
            max_text_bytes=selected_text,
            max_batch_size=self.max_batch_size,
            max_filter_count=self.max_filter_count,
            max_filter_values=self.max_filter_values,
            max_complexity=self.max_complexity,
            timeout_ms=self.timeout_ms,
        )
