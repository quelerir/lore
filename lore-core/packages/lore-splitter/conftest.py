"""Root conftest for lore-splitter tests.

Changes the working directory to the package root before each test so that
relative paths like Path("tests/fixtures/...") resolve correctly regardless
of where pytest is invoked from.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _set_package_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(Path(__file__).parent)
