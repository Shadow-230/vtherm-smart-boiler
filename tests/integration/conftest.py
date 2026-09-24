"""Integration tests: Home Assistant runs inside the test process (no instance, no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

VENDOR_COMPONENTS = Path(__file__).resolve().parents[2] / "vendor" / "custom_components"

requires_vendor = pytest.mark.skipif(
    not (VENDOR_COMPONENTS / "versatile_thermostat").is_dir(),
    reason="vendor/ is not set up (docs/plan-0.1.md, A5)",
)
