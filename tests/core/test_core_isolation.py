"""``core`` stays pure: standard library and its own modules only, never Home Assistant."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = ROOT / "custom_components" / "vtherm_smart_boiler" / "core"
CORE_PACKAGE = "custom_components.vtherm_smart_boiler.core"


def _module_package(path: Path) -> str:
    """Dotted package that relative imports in ``path`` resolve against (its directory)."""
    return ".".join((CORE_PACKAGE, *path.relative_to(CORE_DIR).parent.parts))


def _resolve_relative(package: str, level: int, module: str | None) -> str:
    base = package.split(".")
    if level > 1:
        base = base[: -(level - 1)]
    return ".".join([*base, module] if module else base)


def _is_allowed(name: str) -> bool:
    top = name.split(".")[0]
    return top in sys.stdlib_module_names or name == CORE_PACKAGE or name.startswith(
        CORE_PACKAGE + "."
    )


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = _module_package(path)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names = [_resolve_relative(package, node.level, node.module)]
            else:
                names = [node.module or ""]
        else:
            continue
        found.extend(
            f"{path.relative_to(ROOT)}:{node.lineno} imports {name}"
            for name in names
            if not _is_allowed(name)
        )
    return found


def test_core_imports_only_stdlib_and_itself() -> None:
    modules = sorted(CORE_DIR.rglob("*.py"))
    assert modules, "core/ has no modules"
    violations = [v for module in modules for v in _violations(module)]
    assert violations == []


def test_core_imports_without_home_assistant_in_a_fresh_process() -> None:
    script = (
        "import importlib, pkgutil, sys\n"
        f"import {CORE_PACKAGE} as core\n"
        "for info in pkgutil.walk_packages(core.__path__, core.__name__ + '.'):\n"
        "    importlib.import_module(info.name)\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] == 'homeassistant')\n"
        "print(bad)\n"
        "sys.exit(1 if bad else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
