"""Guard: lore_core_domain stays stdlib-only (the merge's base-layer invariant)."""

from __future__ import annotations

import subprocess
import sys

# lore_core_domain must not pull ANY third-party or sibling package.
FORBIDDEN = [
    "airflow", "fastapi", "pydantic", "chainlit", "psycopg", "markitdown",
    "openpyxl", "PIL", "fitz", "docx", "pptx", "defusedxml", "yaml",
    "lore_audit", "lore_splitter", "lore_audit_api",
]

_SCRIPT = """
import importlib, pkgutil, sys
import lore_core_domain
for m in pkgutil.walk_packages(lore_core_domain.__path__, "lore_core_domain."):
    importlib.import_module(m.name)
forbidden = set(%r)
loaded = {name.split(".")[0] for name in sys.modules}
bad = sorted(forbidden & loaded)
assert not bad, "lore_core_domain pulled forbidden imports: " + repr(bad)
"""


def test_lore_core_domain_imports_no_forbidden_dependencies():
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT % FORBIDDEN],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
