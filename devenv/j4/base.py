"""J4: an instance's options walked back to a base (``options.py``) — instance 1's gateway base,
or the starts criterion's house on instances 2 to 5 (docs/en/testing/test-environment.md §5), the comfort correction
on where a run compares it (K4: F8). Refused while control is on: a change of how the hand-back
is made waits until none is owed — switch control off first, and let the hand-back finish.

Usage: HA_INSTANCE=N scripts/env.sh python devenv/j4/base.py gateway|starts [--correction]
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from lib import HA
from options import BASE_GATEWAY, BASE_STARTS, GATEWAY_ITEMS
from walk import save_options

BASES = {"gateway": BASE_GATEWAY, "starts": BASE_STARTS}


async def main(argv: list[str]) -> int:
    name = argv[0] if argv else ""
    if name not in BASES or set(argv[1:]) - {"--correction"}:
        print(__doc__)
        return 2
    changes = dict(BASES[name])
    if "--correction" in argv[1:]:
        changes["comfort_correction"] = True
    async with HA() as ha:
        entities = await ha.entities()
        control = await ha.state(entities["control"]) if "control" in entities else None
        if control is not None and control.get("state") == "on":
            print("control is on: switch it off and let the hand-back finish first")
            return 1
        entry = await ha.entry("vtherm_smart_boiler")
        result = await save_options(ha.rest, entry["entry_id"], changes, GATEWAY_ITEMS, note=print)
    print(f"{name}: {result.get('type')} {result.get('errors') or ''}".rstrip())
    return 0 if not result.get("errors") else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
