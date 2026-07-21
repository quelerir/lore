from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest


PROVIDER_ROOT = Path(__file__).resolve().parents[1]
DAG_PATH = PROVIDER_ROOT / "example_dags" / "lore_splitter.py"
CONFIG_PATH = PROVIDER_ROOT / "example_dags" / "configs" / "lore.yaml.example"


class _XComArg:
    pass


class _MappedTask:
    def __init__(self, operator: type[Any], partial: dict[str, Any], mapped: dict[str, Any]) -> None:
        self.operator = operator
        self.task_id = partial["task_id"]
        self.partial_kwargs = partial
        self.mapped_kwargs = mapped
        self.upstream_task_ids: set[str] = set()
        self.downstream_task_ids: set[str] = set()

    def __rshift__(self, other: "_MappedTask") -> "_MappedTask":
        self.downstream_task_ids.add(other.task_id)
        other.upstream_task_ids.add(self.task_id)
        return other


class _Partial:
    def __init__(self, operator: type[Any], kwargs: dict[str, Any], tasks: dict[str, Any]) -> None:
        self.operator = operator
        self.kwargs = kwargs
        self.tasks = tasks

    def expand(self, **kwargs: Any) -> _MappedTask:
        mapped = _MappedTask(self.operator, self.kwargs, kwargs)
        self.tasks[mapped.task_id] = mapped
        return mapped


class _TaskDecorator:
    def __init__(self, python_callable: Any, task_id: str, tasks: dict[str, Any]) -> None:
        self.python_callable = python_callable
        self.task_id = task_id
        self.tasks = tasks

    def __call__(self) -> _XComArg:
        output = _XComArg()
        self.tasks[self.task_id] = types.SimpleNamespace(task_id=self.task_id, output=output)
        return output


def _load_with_structural_airflow(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    tasks: dict[str, Any] = {}
    context: dict[str, Any] = {}
    airflow = types.ModuleType("airflow")
    airflow.__path__ = [str(PROVIDER_ROOT / "airflow")]
    sdk = types.ModuleType("airflow.sdk")
    trigger_rule = types.ModuleType("airflow.utils.trigger_rule")
    lore_operators = types.ModuleType("airflow.providers.lore.operators")

    def task(*, task_id: str):
        return lambda function: _TaskDecorator(function, task_id, tasks)

    def dag(**dag_kwargs: Any):
        def decorate(function: Any):
            def build() -> Any:
                function()
                return types.SimpleNamespace(
                    dag_id=dag_kwargs["dag_id"], task_dict=tasks, dag_kwargs=dag_kwargs
                )

            return build

        return decorate

    class LoreSplitterOperator:
        @classmethod
        def partial(cls, **kwargs: Any) -> _Partial:
            return _Partial(cls, kwargs, tasks)

    class LoreSplitterAuditOperator:
        @classmethod
        def partial(cls, **kwargs: Any) -> _Partial:
            return _Partial(cls, kwargs, tasks)

    sdk.dag = dag
    sdk.task = task
    sdk.get_current_context = lambda: context
    trigger_rule.TriggerRule = types.SimpleNamespace(ALL_DONE="all_done")
    lore_operators.LoreSplitterOperator = LoreSplitterOperator
    lore_operators.LoreSplitterAuditOperator = LoreSplitterAuditOperator
    monkeypatch.setitem(sys.modules, "airflow", airflow)
    monkeypatch.setitem(sys.modules, "airflow.sdk", sdk)
    monkeypatch.setitem(sys.modules, "airflow.utils.trigger_rule", trigger_rule)
    monkeypatch.setitem(sys.modules, "airflow.providers.lore.operators", lore_operators)

    spec = importlib.util.spec_from_file_location("lore_splitter_test_dag", DAG_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._test_context = context
    return module, module.lore_splitter


def _valid_item(**updates: Any) -> dict[str, Any]:
    item = {
        "source_id": "airbyte",
        "stream": "files",
        "file_id": "file-1",
        "bucket": "lore-files",
        "key": "documents/file-1.pdf",
    }
    item.update(updates)
    return item


def test_real_dagbag_import_when_scheduler_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        from airflow.models.dagbag import DagBag
    except ModuleNotFoundError:
        pytest.skip("Airflow scheduler classes are intentionally absent from the provider venv")

    monkeypatch.setenv("LORE_CONFIG_PATH", str(CONFIG_PATH))
    dag_bag = DagBag(dag_folder=str(DAG_PATH), include_examples=False, safe_mode=False)

    assert dag_bag.import_errors == {}
    assert "lore_splitter" in dag_bag.dags


def test_real_dag_import_and_paired_mapping_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORE_CONFIG_PATH", str(CONFIG_PATH))
    module, dag = _load_with_structural_airflow(monkeypatch)

    assert DAG_PATH.is_file()
    assert module.RUNTIME_CONFIG_PATH == str(CONFIG_PATH)
    assert dag.dag_id == "lore_splitter"
    assert set(dag.task_dict) == {"validated_file_items", "split_file", "audit_file"}

    producer = dag.task_dict["validated_file_items"].output
    splitter = dag.task_dict["split_file"]
    audit = dag.task_dict["audit_file"]
    assert splitter.mapped_kwargs == {"file_item": producer}
    assert audit.mapped_kwargs == {"file_item": producer}
    assert splitter.mapped_kwargs["file_item"] is audit.mapped_kwargs["file_item"]
    assert splitter.partial_kwargs["configurations"] == module.RUNTIME_CONFIG.splitter_operator_config()
    assert splitter.partial_kwargs["retries"] == 2
    assert splitter.partial_kwargs["max_active_tis_per_dag"] == 16
    assert audit.partial_kwargs["splitter_task_id"] == "split_file"
    assert audit.partial_kwargs["postgres_conn_id"] == module.RUNTIME_CONFIG.splitter.postgres_conn_id
    assert audit.partial_kwargs["s3_conn_id"] == module.RUNTIME_CONFIG.splitter.s3_conn_id
    assert audit.partial_kwargs["ruleset_version"] == "audit/v1"
    assert audit.partial_kwargs["trigger_rule"] == "all_done"
    assert splitter.downstream_task_ids == {"audit_file"}
    assert audit.upstream_task_ids == {"split_file"}


@pytest.mark.parametrize(
    "conf",
    [
        {},
        {"file_items": "not-a-list"},
        {"file_items": ["not-a-mapping"]},
        {"file_items": [_valid_item(unknown="unsafe")]},
    ],
)
def test_file_item_producer_rejects_missing_non_list_or_unsafe_shape(
    monkeypatch: pytest.MonkeyPatch, conf: dict[str, Any]
) -> None:
    monkeypatch.setenv("LORE_CONFIG_PATH", str(CONFIG_PATH))
    module, _ = _load_with_structural_airflow(monkeypatch)
    module._test_context["dag_run"] = types.SimpleNamespace(conf=conf)

    with pytest.raises(ValueError, match="file_items"):
        module.validated_file_items.python_callable()


def test_file_item_producer_is_bounded_and_returns_copies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LORE_CONFIG_PATH", str(CONFIG_PATH))
    module, _ = _load_with_structural_airflow(monkeypatch)
    item = _valid_item(metadata={"owner": "lore"})
    module._test_context["dag_run"] = types.SimpleNamespace(conf={"file_items": [item]})

    result = module.validated_file_items.python_callable()

    assert result == [item]
    assert result is not module._test_context["dag_run"].conf["file_items"]
    assert result[0] is not item

    module._test_context["dag_run"] = types.SimpleNamespace(
        conf={"file_items": [_valid_item(file_id=str(index)) for index in range(module.MAX_FILE_ITEMS + 1)]}
    )
    with pytest.raises(ValueError, match="file_items"):
        module.validated_file_items.python_callable()


def test_dag_source_is_parse_time_service_free_and_namespace_safe() -> None:
    source = DAG_PATH.read_text(encoding="utf-8")

    assert "from airflow.sdk import dag, get_current_context, task" in source
    assert "from airflow.decorators" not in source
    assert "from airflow.operators.python" not in source
    for forbidden in ("Datacraft", "DagBuilder", "ConfigManager", "Variable.get", "Hook(",
                      "get_connection", "{{", "processed_files.latest_run_id"):
        assert forbidden not in source
    assert not (PROVIDER_ROOT / "airflow" / "__init__.py").exists()
    assert not (PROVIDER_ROOT / "airflow" / "providers" / "__init__.py").exists()
