from __future__ import annotations

import importlib
import inspect
import sys
import types
from copy import deepcopy
from pathlib import Path

import pytest

PROVIDER_ROOT = Path(__file__).resolve().parents[1]
MODULE_NAME = "airflow.providers.lore.operators.lore_splitter_audit_operator"


def _import_operator_module():
    airflow = types.ModuleType("airflow")
    airflow.__path__ = [str(PROVIDER_ROOT / "airflow")]
    models = types.ModuleType("airflow.models")

    class BaseOperator:
        def __init__(self, **kwargs):
            self.task_id = kwargs.get("task_id")

    models.BaseOperator = BaseOperator
    exceptions = types.ModuleType("airflow.exceptions")
    exceptions.AirflowException = RuntimeError
    exceptions.AirflowFailException = RuntimeError
    context = types.ModuleType("airflow.utils.context")
    context.Context = dict
    sys.modules.update(
        {
            "airflow": airflow,
            "airflow.models": models,
            "airflow.exceptions": exceptions,
            "airflow.utils.context": context,
        }
    )
    sys.modules.pop(MODULE_NAME, None)
    sys.path.insert(0, str(PROVIDER_ROOT))
    try:
        return importlib.import_module(MODULE_NAME)
    finally:
        sys.path.remove(str(PROVIDER_ROOT))


class FakeTaskInstance:
    def __init__(self, *, map_index: object, claim: object):
        self.map_index = map_index
        self.claim = claim
        self.pulls: list[dict[str, object]] = []

    def xcom_pull(self, **kwargs):
        self.pulls.append(kwargs)
        return self.claim


class Recorder:
    def __init__(self, *, result=None, service_category=None, adapter_error=None):
        self.events = []
        self.adapter_calls = []
        self.service_calls = []
        self.audit_calls = []
        self.result = result or {
            "run_id": "8d5bb83a-b219-4fb4-bf6b-5301252ebf0a",
            "ruleset_version": "audit/v1",
            "status": "completed",
            "checked_rule_count": 5,
            "outcome_counts": {"pass": 5, "finding": 0, "unavailable": 0},
            "severity_counts": {"info": 0, "warning": 0, "error": 0},
        }
        self.service_category = service_category
        self.adapter_error = adapter_error
        self.error_class = None
        self.adapters = types.SimpleNamespace(
            reader=object(), writer=object(), payload_resolver=object(), bounds=object()
        )

    def adapter_factory(self, **kwargs):
        self.events.append("adapters")
        self.adapter_calls.append(kwargs)
        if self.adapter_error:
            raise self.adapter_error
        return self.adapters

    def service_factory(self, **kwargs):
        self.events.append("service")
        self.service_calls.append(kwargs)
        recorder = self

        class Service:
            def audit_run(self, run_id, ruleset_version):
                recorder.events.append("audit")
                recorder.audit_calls.append((run_id, ruleset_version))
                if recorder.service_category:
                    primary = RuntimeError(
                        "postgresql://user:password@host/db "
                        "https://bucket.invalid/key?X-Amz-Signature=secret "
                        "private source text payload-bytes-secret"
                    )
                    raise recorder.error_class(recorder.service_category) from primary
                return types.SimpleNamespace(to_dict=lambda: deepcopy(recorder.result))

        return Service()


def _operator(module, *, file_item=None, recorder=None):
    recorder = recorder or Recorder()
    recorder.error_class = module.AuditExecutionError
    return module.LoreSplitterAuditOperator(
        task_id="audit_file",
        file_item=file_item or {"file_id": "file-a"},
        splitter_task_id="split_file",
        postgres_conn_id="postgres.ready",
        s3_conn_id="s3.ready",
        adapter_factory=recorder.adapter_factory,
        service_factory=recorder.service_factory,
    )


def test_constructor_is_keyword_only_and_templates_file_item():
    module = _import_operator_module()
    signature = inspect.signature(module.LoreSplitterAuditOperator.__init__)

    assert signature.parameters["file_item"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["splitter_task_id"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["postgres_conn_id"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["s3_conn_id"].kind is inspect.Parameter.KEYWORD_ONLY
    assert "file_item" in module.LoreSplitterAuditOperator.template_fields
    assert _operator(module).file_item == {"file_id": "file-a"}


@pytest.mark.parametrize(
    ("map_index", "run_id"),
    [
        (0, "8d5bb83a-b219-4fb4-bf6b-5301252ebf0a"),
        (1, "ab4777ce-1a9c-4d21-9ab4-597c80cfa30c"),
    ],
)
def test_ready_claim_is_pulled_only_from_same_map_index(map_index, run_id):
    module = _import_operator_module()
    expected = Recorder().result
    expected["run_id"] = run_id
    recorder = Recorder(result=expected)
    ti = FakeTaskInstance(
        map_index=map_index,
        claim={"schema_version": "lore/run-claim/v1", "run_id": run_id},
    )

    assert _operator(module, recorder=recorder).execute({"ti": ti}) == expected
    assert ti.pulls == [
        {"task_ids": "split_file", "key": "lore_run_claim", "map_indexes": map_index}
    ]
    assert recorder.events == ["adapters", "service", "audit"]
    assert recorder.audit_calls == [(run_id, "audit/v1")]


def test_file_item_cannot_change_claim_lookup_or_selected_run():
    module = _import_operator_module()
    run_id = "8d5bb83a-b219-4fb4-bf6b-5301252ebf0a"
    results = []
    pulls = []
    recorders = []
    for file_item in ({"file_id": "one"}, {"malicious": "latest-run", "file_id": "two"}):
        ti = FakeTaskInstance(
            map_index=3,
            claim={"schema_version": "lore/run-claim/v1", "run_id": run_id.upper()},
        )
        expected = Recorder().result
        expected["run_id"] = run_id
        recorder = Recorder(result=expected)
        results.append(
            _operator(module, file_item=file_item, recorder=recorder).execute(
                {"task_instance": ti}
            )
        )
        pulls.append(ti.pulls)
        recorders.append(recorder)

    assert results == [recorders[0].result, recorders[1].result]
    assert pulls[0] == pulls[1] == [
        {"task_ids": "split_file", "key": "lore_run_claim", "map_indexes": 3}
    ]
    assert [item.audit_calls for item in recorders] == [[(run_id, "audit/v1")]] * 2


@pytest.mark.parametrize(
    ("map_index", "claim"),
    [
        (0, None),
        (0, "not-an-object"),
        (0, {}),
        (0, {"schema_version": "lore/run-claim/v1"}),
        (0, {"run_id": "8d5bb83a-b219-4fb4-bf6b-5301252ebf0a"}),
        (0, {"schema_version": "lore/run-claim/v2", "run_id": "8d5bb83a-b219-4fb4-bf6b-5301252ebf0a"}),
        (0, {"schema_version": "lore/run-claim/v1", "run_id": "not-a-uuid"}),
        (0, {"schema_version": "lore/run-claim/v1", "run_id": 123}),
        (0, {"schema_version": "lore/run-claim/v1", "run_id": "8d5bb83a-b219-4fb4-bf6b-5301252ebf0a", "extra": True}),
        (None, {"schema_version": "lore/run-claim/v1", "run_id": "8d5bb83a-b219-4fb4-bf6b-5301252ebf0a"}),
        (True, {"schema_version": "lore/run-claim/v1", "run_id": "8d5bb83a-b219-4fb4-bf6b-5301252ebf0a"}),
    ],
)
def test_missing_malformed_or_unmapped_claim_is_closed_no_run(map_index, claim):
    module = _import_operator_module()
    ti = FakeTaskInstance(map_index=map_index, claim=claim)
    recorder = Recorder()

    assert _operator(module, recorder=recorder).execute({"ti": ti}) == {
        "status": "no_run",
        "run_id": None,
    }
    assert recorder.events == []
    if type(map_index) is int:
        assert ti.pulls == [
            {"task_ids": "split_file", "key": "lore_run_claim", "map_indexes": map_index}
        ]
    else:
        assert ti.pulls == []


def test_missing_task_instance_is_closed_no_run():
    module = _import_operator_module()
    recorder = Recorder()

    assert _operator(module, recorder=recorder).execute({}) == {
        "status": "no_run",
        "run_id": None,
    }
    assert recorder.events == []


def test_operator_uses_adapter_boundary_without_direct_hook_or_processing_mutation():
    source = (PROVIDER_ROOT / "airflow/providers/lore/operators/lore_splitter_audit_operator.py").read_text(
        encoding="utf-8"
    )

    for forbidden in ("CoreRepository", "S3Hook", "PostgresHook", "processing_runs"):
        assert forbidden not in source
    assert "build_airflow_audit_adapters" in source
    assert "AuditService" in source


def test_completed_clean_and_retry_return_same_bounded_safe_shape():
    module = _import_operator_module()
    run_id = "8d5bb83a-b219-4fb4-bf6b-5301252ebf0a"
    result = Recorder().result
    result.update(
        {
            "run_id": run_id,
            "checked_rule_count": 0,
            "outcome_counts": {"pass": 0, "finding": 0, "unavailable": 0},
        }
    )
    recorder = Recorder(result=result)
    operator = _operator(module, recorder=recorder)

    outputs = []
    for _ in range(2):
        ti = FakeTaskInstance(
            map_index=4,
            claim={"schema_version": "lore/run-claim/v1", "run_id": run_id},
        )
        outputs.append(operator.execute({"ti": ti}))

    assert outputs == [result, result]
    assert recorder.audit_calls == [(run_id, "audit/v1"), (run_id, "audit/v1")]


@pytest.mark.parametrize(
    "category",
    [
        "read_failed",
        "resolution_failed",
        "engine_failed",
        "completed_write_failed",
        "failure_recording_failed",
    ],
)
def test_service_failures_raise_fixed_redacted_airflow_failure(category):
    module = _import_operator_module()
    run_id = "8d5bb83a-b219-4fb4-bf6b-5301252ebf0a"
    recorder = Recorder(service_category=category)
    ti = FakeTaskInstance(
        map_index=0,
        claim={"schema_version": "lore/run-claim/v1", "run_id": run_id},
    )

    with pytest.raises(RuntimeError) as error:
        _operator(module, recorder=recorder).execute({"ti": ti})

    assert str(error.value) == f"lore audit failed: {category}"
    assert isinstance(error.value.__cause__, module.AuditExecutionError)
    for canary in ("password", "X-Amz-Signature", "private source", "payload-bytes"):
        assert canary not in str(error.value)


def test_adapter_failure_is_fixed_and_processing_evidence_is_immutable():
    module = _import_operator_module()
    run_id = "8d5bb83a-b219-4fb4-bf6b-5301252ebf0a"
    claim = {"schema_version": "lore/run-claim/v1", "run_id": run_id}
    processing = {"status": "success", "chunks": ["immutable"], "claim": claim.copy()}
    before = deepcopy(processing)
    recorder = Recorder(
        adapter_error=RuntimeError("postgresql://user:password@host/db private content")
    )

    with pytest.raises(RuntimeError) as error:
        _operator(module, file_item=processing, recorder=recorder).execute(
            {"ti": FakeTaskInstance(map_index=0, claim=claim)}
        )

    assert str(error.value) == "lore audit failed: dependency_initialization"
    assert processing == before
    assert recorder.events == ["adapters"]


def test_ready_claim_forwards_only_connection_ids_ruleset_and_bounds():
    module = _import_operator_module()
    run_id = "8d5bb83a-b219-4fb4-bf6b-5301252ebf0a"
    recorder = Recorder()
    ti = FakeTaskInstance(
        map_index=0,
        claim={"schema_version": "lore/run-claim/v1", "run_id": run_id},
    )

    _operator(module, recorder=recorder).execute({"ti": ti})

    assert recorder.adapter_calls == [
        {
            "postgres_conn_id": "postgres.ready",
            "s3_conn_id": "s3.ready",
            "bounds": recorder.adapter_calls[0]["bounds"],
        }
    ]
    assert set(recorder.service_calls[0]) == {
        "reader",
        "writer",
        "bounds",
        "payload_resolver",
    }
