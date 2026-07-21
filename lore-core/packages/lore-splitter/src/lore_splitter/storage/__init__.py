"""Storage public API for TOAST artifacts (portable; Airflow hooks deferred to Phase 3)."""

from __future__ import annotations

from lore_core_domain.storage_contracts import (
    ImageToastStoragePlan,
    ImageToastStorageResult,
    ObjectToastStore,
    StorageColumn,
    StoragePlanError,
    StorageRow,
    TableToastStoragePlan,
    TableToastStorageResult,
    TableToastStore,
)

from lore_splitter.storage.core_schema import apply_migration
from lore_splitter.storage.fake import FakeObjectToastStore, FakeTableToastStore
from lore_splitter.storage.object_schema import (
    image_content_signature,
    image_object_key,
    image_toast_id,
    validate_image_storage_plan,
)
from lore_splitter.storage.schema import (
    DEFAULT_TOAST_SCHEMA,
    TOAST_TABLE_RE,
    build_table_storage_plan,
    validate_table_storage_plan,
    validate_toast_table_name,
)

__all__ = [
    "DEFAULT_TOAST_SCHEMA",
    "FakeObjectToastStore",
    "FakeTableToastStore",
    "ImageToastStoragePlan",
    "ImageToastStorageResult",
    "ObjectToastStore",
    "StorageColumn",
    "StoragePlanError",
    "StorageRow",
    "TOAST_TABLE_RE",
    "TableToastStoragePlan",
    "TableToastStorageResult",
    "TableToastStore",
    "apply_migration",
    "build_table_storage_plan",
    "image_content_signature",
    "image_object_key",
    "image_toast_id",
    "validate_image_storage_plan",
    "validate_table_storage_plan",
    "validate_toast_table_name",
]
