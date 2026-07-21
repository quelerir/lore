from __future__ import annotations


def get_provider_info() -> dict[str, object]:
    return {
        "package-name": "apache-airflow-providers-lore",
        "name": "Lore",
        "description": "Lore Airflow provider for Splitter workflows.",
        "versions": ["0.1.0"],
        "operators": [
            {
                "integration-name": "Lore Splitter",
                "python-modules": [
                    "airflow.providers.lore.operators.lore_splitter_operator",
                    "airflow.providers.lore.operators.lore_splitter_audit_operator",
                ],
            }
        ],
    }
