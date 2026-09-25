"""Minimal physics simulator for tests: a boiler, one circuit, a house split into zones.

Not shipped with the plugin. The physics lives in the test-only component
(``custom_components/boiler_sim``), which the test Home Assistant can import; this package runs
whole scenarios on it offline. Its output is the core's ``History``, so simulated data runs
through exactly the code that analyses recorded and live data.
"""

from __future__ import annotations
