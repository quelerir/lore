from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import Mock

# tests/ -> provider root; the fake `airflow` package __path__ points at the
# real provider `airflow/` dir so `airflow.providers.lore.*` resolves to real
# code while `airflow.models` / hooks / exceptions are faked.
PROVIDER_ROOT = Path(__file__).resolve().parents[1]


def install_airflow_stubs():
    airflow = types.ModuleType("airflow")
    airflow.__path__ = [str(PROVIDER_ROOT / "airflow")]
    models = types.ModuleType("airflow.models")

    class BaseOperator:
        def __init__(self, **kwargs):
            self.task_id = kwargs.get("task_id")

    models.BaseOperator = BaseOperator
    amazon_s3 = types.ModuleType("airflow.providers.amazon.aws.hooks.s3")

    class S3Hook:
        instances = []

        def __init__(self, aws_conn_id=None, **kwargs):
            self.aws_conn_id = aws_conn_id
            self.kwargs = kwargs
            self.download_file = Mock()
            self.load_bytes = Mock()
            S3Hook.instances.append(self)

    amazon_s3.S3Hook = S3Hook
    amazon = types.ModuleType("airflow.providers.amazon")
    amazon.__path__ = []
    amazon_aws = types.ModuleType("airflow.providers.amazon.aws")
    amazon_aws.__path__ = []
    amazon_hooks = types.ModuleType("airflow.providers.amazon.aws.hooks")
    amazon_hooks.__path__ = []
    postgres = types.ModuleType("airflow.providers.postgres")
    postgres.__path__ = []
    postgres_hooks = types.ModuleType("airflow.providers.postgres.hooks")
    postgres_hooks.__path__ = []
    postgres_module = types.ModuleType("airflow.providers.postgres.hooks.postgres")

    class PostgresHook:
        instances = []

        def __init__(self, postgres_conn_id=None, **kwargs):
            self.postgres_conn_id = postgres_conn_id
            self.connection = object()
            self.get_conn = Mock(return_value=self.connection)
            PostgresHook.instances.append(self)

    postgres_module.PostgresHook = PostgresHook
    base_hooks = types.ModuleType("airflow.hooks.base")

    class BaseHook:
        get_connection = Mock()

    base_hooks.BaseHook = BaseHook
    exceptions = types.ModuleType("airflow.exceptions")

    class AirflowException(Exception):
        pass

    class AirflowFailException(AirflowException):
        pass

    exceptions.AirflowException = AirflowException
    exceptions.AirflowFailException = AirflowFailException
    context = types.ModuleType("airflow.utils.context")
    context.Context = dict
    for name, value in {
        "airflow": airflow,
        "airflow.models": models,
        "airflow.providers.amazon": amazon,
        "airflow.providers.amazon.aws": amazon_aws,
        "airflow.providers.amazon.aws.hooks": amazon_hooks,
        "airflow.providers.amazon.aws.hooks.s3": amazon_s3,
        "airflow.providers.postgres": postgres,
        "airflow.providers.postgres.hooks": postgres_hooks,
        "airflow.providers.postgres.hooks.postgres": postgres_module,
        "airflow.hooks.base": base_hooks,
        "airflow.exceptions": exceptions,
        "airflow.utils.context": context,
    }.items():
        sys.modules[name] = value
