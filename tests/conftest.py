"""Shared test setup.

``custom_components`` is imported here, before any Home Assistant fixture runs, as a namespace
package spanning this repository and ``vendor/custom_components`` (VT). Home
Assistant's loader imports ``custom_components`` from its test configuration directory only when
the module is not loaded yet, and that directory holds a regular package that would hide ours.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
from types import ModuleType

import custom_components

# The test harness: pytest-homeassistant from Home Assistant 2026.11 (pyproject's group ``ha``),
# its predecessor pytest-homeassistant-custom-component on the declared minimum (``ha-minimum``).
# The tests import the new name; where only the old package is installed, that name points to
# it, module by module.
_NEW, _OLD = "pytest_homeassistant", "pytest_homeassistant_custom_component"


class _OldHarness(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """``pytest_homeassistant[.x]`` served by ``pytest_homeassistant_custom_component[.x]``."""

    def find_spec(
        self, fullname: str, path: object = None, target: object = None
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname != _NEW and not fullname.startswith(_NEW + "."):
            return None
        return importlib.machinery.ModuleSpec(fullname, self)

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType:
        return importlib.import_module(_OLD + spec.name[len(_NEW) :])

    def exec_module(self, module: ModuleType) -> None:
        """Already run as the old package's module."""


if importlib.util.find_spec(_NEW) is None and importlib.util.find_spec(_OLD) is not None:
    sys.meta_path.insert(0, _OldHarness())

assert getattr(custom_components, "__file__", None) is None, (
    "custom_components must stay a namespace package (no __init__.py) so vendor/ can join it"
)
