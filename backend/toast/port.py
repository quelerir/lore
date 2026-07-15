from typing import Any, Protocol, TypedDict


class DiscoveredTable(TypedDict):
    source_path: str
    table_id: str
    coordinates: Any
    summary: str | None


class TableInfo(TypedDict):
    table_id: str
    columns: list[str]
    row_count: int
    header_hint: str | None  # display_text чанка: header-as-data дефект


class SelectResult(TypedDict):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool


class ToastStorePort(Protocol):
    async def discover(self, document_hint: str) -> list[DiscoveredTable]: ...
    async def inspect(self, table_id: str) -> TableInfo: ...
    async def run_select(self, sql: str) -> SelectResult | str: ...
