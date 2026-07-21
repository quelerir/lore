from __future__ import annotations

from lore_core_domain.storage_contracts import (
    ImageToastStoragePlan,
    ImageToastStorageResult,
    StorageRow,
    TableToastStoragePlan,
    TableToastStorageResult,
)
from lore_splitter.storage.object_schema import validate_image_storage_plan
from lore_splitter.storage.schema import validate_table_storage_plan


class ImmutableStoreResult:
    def __init__(self, action: str, identity: str) -> None:
        self.action = action
        self.identity = identity


class ImmutableFakeTableStore:
    def __init__(self) -> None:
        self._items: dict[str, tuple[str, ...]] = {}

    def store(self, payload_id: str, values: tuple[str, ...]) -> ImmutableStoreResult:
        prior = self._items.get(payload_id)
        if prior is None:
            self._items[payload_id] = tuple(values)
            return ImmutableStoreResult("created", payload_id)
        if prior != tuple(values):
            raise ValueError("payload collision")
        return ImmutableStoreResult("reused", payload_id)


class FakeTableToastStore:
    """In-memory table TOAST store for deterministic dry-run tests."""

    def __init__(self) -> None:
        self.plans_by_toast_id: dict[str, TableToastStoragePlan] = {}
        self.results_by_toast_id: dict[str, TableToastStorageResult] = {}
        self.rows_by_table_name: dict[str, tuple[StorageRow, ...]] = {}

    def store_table(self, plan: TableToastStoragePlan) -> TableToastStorageResult:
        validate_table_storage_plan(plan)
        action = (
            "dry_run_replaced" if plan.toast_id in self.results_by_toast_id else "dry_run_created"
        )
        result = TableToastStorageResult.from_plan(plan, action=action)
        self.plans_by_toast_id[plan.toast_id] = plan
        self.results_by_toast_id[plan.toast_id] = result
        self.rows_by_table_name[plan.table_name] = plan.rows
        return result


class FakeObjectToastStore:
    """In-memory object TOAST store for deterministic dry-run tests."""

    def __init__(
        self,
        *,
        fail_toast_ids: set[str] | None = None,
        fail_object_keys: set[str] | None = None,
    ) -> None:
        self.fail_toast_ids = set(fail_toast_ids or ())
        self.fail_object_keys = set(fail_object_keys or ())
        self.plans_by_toast_id: dict[str, ImageToastStoragePlan] = {}
        self.results_by_toast_id: dict[str, ImageToastStorageResult] = {}
        self.payloads_by_toast_id: dict[str, bytes] = {}
        self.payloads_by_object_key: dict[str, bytes] = {}

    def store_object(self, plan: ImageToastStoragePlan) -> ImageToastStorageResult:
        validate_image_storage_plan(plan)
        self.plans_by_toast_id[plan.toast_id] = plan
        if plan.toast_id in self.fail_toast_ids or plan.object_key in self.fail_object_keys:
            result = ImageToastStorageResult.from_plan(
                plan,
                action="failed",
                diagnostics=(
                    *plan.diagnostics,
                    f"fake_object_store_failure:toast_id={plan.toast_id}:object_key={plan.object_key}",
                ),
            )
            self.results_by_toast_id[plan.toast_id] = result
            return result

        action = (
            "dry_run_replaced" if plan.toast_id in self.results_by_toast_id else "dry_run_created"
        )
        result = ImageToastStorageResult.from_plan(plan, action=action)
        self.results_by_toast_id[plan.toast_id] = result
        self.payloads_by_toast_id[plan.toast_id] = plan.payload
        self.payloads_by_object_key[plan.object_key] = plan.payload
        return result
