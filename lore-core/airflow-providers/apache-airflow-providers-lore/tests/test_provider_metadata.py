from __future__ import annotations


def test_get_provider_info_declares_both_operators():
    from airflow.providers.lore.get_provider_info import get_provider_info

    info = get_provider_info()
    assert info["package-name"] == "apache-airflow-providers-lore"
    modules = info["operators"][0]["python-modules"]
    assert "airflow.providers.lore.operators.lore_splitter_operator" in modules
    assert "airflow.providers.lore.operators.lore_splitter_audit_operator" in modules


def test_sibling_packages_importable_without_real_airflow_sdk():
    import importlib.metadata as md

    import lore_splitter  # noqa: F401
    import lore_audit  # noqa: F401

    # The real Airflow SDK must NOT be installed in the provider test env.
    # Assert on the installed DISTRIBUTION (not sys.modules / find_spec), so the
    # check is immune to the fake `airflow.*` modules other tests stub in-process.
    try:
        md.version("apache-airflow")
        installed = True
    except md.PackageNotFoundError:
        installed = False
    assert not installed, "apache-airflow must not be installed in the provider test env"
