"""Shared test setup.

``custom_components`` is imported here, before any Home Assistant fixture runs, as a namespace
package spanning this repository and ``vendor/custom_components`` (VT and SmartPI). Home
Assistant's loader imports ``custom_components`` from its test configuration directory only when
the module is not loaded yet, and that directory holds a regular package that would hide ours.
"""

from __future__ import annotations

import custom_components

assert getattr(custom_components, "__file__", None) is None, (
    "custom_components must stay a namespace package (no __init__.py) so vendor/ can join it"
)
