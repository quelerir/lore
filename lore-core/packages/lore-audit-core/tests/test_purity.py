"""Guard: lore_audit imports no Airflow / web-stack dependencies."""

from __future__ import annotations

import subprocess
import sys

FORBIDDEN = ["airflow", "fastapi", "pydantic", "chainlit", "lore_splitter"]

_SCRIPT = """
import importlib, pkgutil, sys
import lore_audit
for m in pkgutil.walk_packages(lore_audit.__path__, "lore_audit."):
    importlib.import_module(m.name)
forbidden = set(%r)
loaded = {name.split(".")[0] for name in sys.modules}
bad = sorted(forbidden & loaded)
assert not bad, "lore_audit pulled forbidden imports: " + repr(bad)
"""


def test_lore_audit_imports_no_forbidden_dependencies():
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT % FORBIDDEN],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
