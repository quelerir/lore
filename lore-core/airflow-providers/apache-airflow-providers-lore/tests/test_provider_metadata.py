from __future__ import annotations


def test_get_provider_info_declares_both_operators():
    from airflow.providers.lore.get_provider_info import get_provider_info

    info = get_provider_info()
    assert info["package-name"] == "apache-airflow-providers-lore"
    modules = info["operators"][0]["python-modules"]
    assert "airflow.providers.lore.operators.lore_splitter_operator" in modules
    assert "airflow.providers.lore.operators.lore_splitter_audit_operator" in modules


def test_sibling_packages_importable_without_real_airflow_sdk():
    import importlib.util

    import lore_splitter  # noqa: F401
    import lore_audit  # noqa: F401

    # The provider owns the `airflow.providers.lore` namespace, so `airflow`
    # resolves to our own package. What must be ABSENT is the real Airflow SDK
    # (e.g. airflow.models) — the test env installs airflow-free; stubs fake it.
    assert importlib.util.find_spec("airflow.models") is None
