# Apache Airflow Provider for Lore

This package exposes Lore Airflow operators under `airflow.providers.lore`.

## LoreSplitterOperator

`LoreSplitterOperator` processes exactly one Airbyte file item through the durable
v1.2 `PerFileExecutionService`.  ConfigManager resolves and validates `splitter`
configuration before mapped tasks are created; the operator itself does not read
YAML, Airflow Variables, environment files, or credentials.  It only acquires the
immutable source object, creates hook-backed persistence adapters, manages scratch,
and returns a compact durable-result XCom.

```python
from airflow.providers.lore.operators import LoreSplitterOperator

split_regulations = LoreSplitterOperator(
    task_id="split_one_regulation",
    file_item=airbyte_item,
    configurations=resolved_configurations,
    overwrite=False,
)
```

The operator return value is intentionally compact for XCom: file/run identifiers,
terminal status, pipeline type, counts, and schema identities. It never includes
payload bytes, source paths, signed URLs, DSNs, or tokens.
