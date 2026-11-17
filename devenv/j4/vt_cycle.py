"""J4: every VT thermostat of a test instance switched in cycles of MINUTES (VT's ``cycle_min``)
through VT's own options flow — the starts criterion's runs with VT's default 5 min and with
15 min, the cycle the plugin advises for zones that call a boiler (K4, 2026-11-17, #150). VT
reloads each thermostat it saves; the plugin's options are not touched. Then each VT climate's
published cycle is read back.

Usage: HA_INSTANCE=N scripts/env.sh python devenv/j4/vt_cycle.py MINUTES
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from lib import HA
from walk import set_vt_cycle


async def main(argv: list[str]) -> int:
    if len(argv) != 1 or not argv[0].isdigit() or not 1 <= int(argv[0]) <= 1000:
        print(__doc__)
        return 2
    minutes = int(argv[0])
    async with HA() as ha:
        _status, entries = await ha.rest("GET", "/api/config/config_entries/entry")
        saved = [
            entry["title"]
            for entry in entries
            if entry["domain"] == "versatile_thermostat"
            and await set_vt_cycle(ha.rest, entry["entry_id"], minutes)
        ]
        print(f"VT thermostats saved with a {minutes}-min cycle: {', '.join(saved) or 'none'}")
        await ha.wait(30)  # VT reloads them
        _status, states = await ha.rest("GET", "/api/states")
        cycles = {
            state["entity_id"]: state["attributes"]["configuration"].get("cycle_min")
            for state in states
            if state["entity_id"].startswith("climate.")
            and isinstance(state["attributes"].get("configuration"), dict)
        }
        for entity_id, cycle in sorted(cycles.items()):
            print(f"  {entity_id}: {cycle} min")
        return 0 if saved and all(cycle == minutes for cycle in cycles.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
