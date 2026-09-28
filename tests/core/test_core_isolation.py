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
    return (
        top in sys.stdlib_module_names
        or name == CORE_PACKAGE
        or name.startswith(CORE_PACKAGE + ".")
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


# Review question 11: bounded learning (principle 13) covers what control uses — the comfort
# correction; the building model feeds the monitor only. These core modules hold it or feed on
# it; control's core must reach none of them, directly or through another module.
BUILDING_MODEL = frozenset({"building", "analysis", "daily", "verdict", "monitor"})
CONTROL_CORE = ("controller", "loop", "limits", "demand")


def _core_modules_imported(name: str) -> set[str]:
    """The core modules ``core/<name>.py`` imports directly, by their short names (core imports
    its own modules with ``from``)."""
    path = CORE_DIR / f"{name}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = _module_package(path)
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            module = _resolve_relative(package, node.level, node.module)
        else:
            module = node.module or ""
        if module == CORE_PACKAGE:  # ``from . import x``
            found.update(alias.name for alias in node.names)
        elif module.startswith(CORE_PACKAGE + "."):
            found.add(module.removeprefix(CORE_PACKAGE + ".").split(".")[0])
    return {module for module in found if (CORE_DIR / f"{module}.py").is_file()}


def test_control_uses_no_building_model() -> None:
    """Question 11: the controller, the loop, the limits and the demand reach no module of the
    building model, through any chain of imports; and the Home Assistant side of control reads
    none of its values."""
    for start in CONTROL_CORE:
        reached: set[str] = set()
        todo = [start]
        while todo:
            module = todo.pop()
            for imported in _core_modules_imported(module) - reached:
                reached.add(imported)
                todo.append(imported)
        assert not reached & BUILDING_MODEL, (start, sorted(reached & BUILDING_MODEL))
    package = CORE_DIR.parent
    for name in ("control.py", "control_config.py"):
        text = (package / name).read_text(encoding="utf-8")
        for word in ("core.building", "LoadModel", "LOSS_COEFFICIENT", "HEATING_THRESHOLD"):
            assert word not in text, (name, word)
    # The check itself sees a chain: the analysis reaches the building model.
    assert "building" in _core_modules_imported("analysis")
