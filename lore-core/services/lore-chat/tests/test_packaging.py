"""Guard the datacraft-chainlit wheel contents.

The service ships as a setuptools package whose loose top-level modules are listed
explicitly in [tool.setuptools] py-modules. A module imported by packaged code but
missing from that list is silently dropped from the wheel — exactly how
`langfuse_tracing` (and `toast_binding` before it) went missing in the deployed
image, disabling the SQL tool / tracer with a ModuleNotFoundError.
"""
import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_IMPORT = re.compile(r"^\s*(?:from|import)\s+([a-zA-Z_]\w*)", re.MULTILINE)


def test_runtime_imported_modules_are_all_packaged():
    cfg = tomllib.loads((_ROOT / "pyproject.toml").read_text())
    py_modules = set(cfg["tool"]["setuptools"]["py-modules"])
    packages = set(cfg["tool"]["setuptools"]["packages"])
    loose = {p.stem for p in _ROOT.glob("*.py")}

    packaged_sources = [_ROOT / f"{m}.py" for m in py_modules]
    for pkg in packages:
        packaged_sources += list((_ROOT / pkg).rglob("*.py"))

    missing: dict[str, list[str]] = {}
    for src in packaged_sources:
        if not src.exists():
            continue
        for name in _IMPORT.findall(src.read_text()):
            if name in loose and name not in py_modules:
                missing.setdefault(name, []).append(src.name)

    assert not missing, (
        "loose modules imported by packaged code but absent from py-modules "
        f"(they won't ship in the wheel): {missing}"
    )


def test_container_puts_lore_chat_on_pythonpath():
    """datacraft-chainlit is a virtual uv member (no [build-system]) → uv doesn't
    install it, so its directory isn't on sys.path in the container. The Dockerfile
    must add it explicitly (PYTHONPATH), otherwise deferred sibling imports
    (toast_binding / langfuse_tracing inside retrieval) fail once cwd moves."""
    dockerfile = (_ROOT / "Dockerfile").read_text()
    assert "PYTHONPATH=/workspace/services/lore-chat" in dockerfile
