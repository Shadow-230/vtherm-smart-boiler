"""``core`` stays pure: standard library and its own modules only, never Home Assistant."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

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


def _core_modules_in(path: Path, package: str | None = None) -> set[str]:
    """The core modules a file imports directly, by their short names: ``from`` imports,
    relative or absolute (``from .core import building`` too), and plain ``import`` statements
    (PB-97). ``package``: what its relative imports resolve against, by default its own
    directory's."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    if package is None:
        package = ".".join(path.parent.relative_to(ROOT).parts)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                module = _resolve_relative(package, node.level, node.module)
            else:
                module = node.module or ""
            if module == CORE_PACKAGE:  # ``from . import x``, ``from .core import x``
                found.update(alias.name for alias in node.names)
                continue
            modules = [module]
        else:
            continue
        found.update(
            module.removeprefix(CORE_PACKAGE + ".").split(".")[0]
            for module in modules
            if module.startswith(CORE_PACKAGE + ".")
        )
    return {module for module in found if (CORE_DIR / f"{module}.py").is_file()}


def _core_reached(path: Path) -> set[str]:
    """Every core module a file reaches, through any chain of imports."""
    reached: set[str] = set()
    todo = [path]
    while todo:
        for imported in _core_modules_in(todo.pop()) - reached:
            reached.add(imported)
            todo.append(CORE_DIR / f"{imported}.py")
    return reached


def test_control_uses_no_building_model() -> None:
    """Question 11: the controller, the loop, the limits and the demand reach no module of the
    building model, through any chain of imports; and the Home Assistant side of control reads
    none of its values."""
    for start in CONTROL_CORE:
        reached = _core_reached(CORE_DIR / f"{start}.py")
        assert not reached & BUILDING_MODEL, (start, sorted(reached & BUILDING_MODEL))
    package = CORE_DIR.parent
    for name in ("control.py", "control_config.py"):
        reached = _core_reached(package / name)  # PB-97: the same resolver
        assert not reached & BUILDING_MODEL, (name, sorted(reached & BUILDING_MODEL))
        text = (package / name).read_text(encoding="utf-8")
        for word in ("core.building", "LoadModel", "LOSS_COEFFICIENT", "HEATING_THRESHOLD"):
            assert word not in text, (name, word)
    # The check itself sees a chain: the analysis reaches the building model.
    assert "building" in _core_modules_in(CORE_DIR / "analysis.py")


@pytest.mark.parametrize(
    ("source", "package"),
    [
        (f"import {CORE_PACKAGE}.building\n", CORE_PACKAGE),
        (f"import {CORE_PACKAGE}.building as model\n", CORE_PACKAGE),
        ("from .core import building\n", "custom_components.vtherm_smart_boiler"),
        ("from .core.building import fit_daily_load\n", "custom_components.vtherm_smart_boiler"),
        ("from . import building\n", CORE_PACKAGE),
        ("from .building import fit_daily_load\n", CORE_PACKAGE),
    ],
)
def test_the_isolation_check_sees_every_form_of_import(
    tmp_path: Path, source: str, package: str
) -> None:
    """PB-97, negative: a plain ``import`` of a core module, and a ``from .core import`` in
    control.py, are seen — the check once followed only ``from`` imports within core."""
    path = tmp_path / "module.py"
    path.write_text(source, encoding="utf-8")
    assert _core_modules_in(path, package) == {"building"}
