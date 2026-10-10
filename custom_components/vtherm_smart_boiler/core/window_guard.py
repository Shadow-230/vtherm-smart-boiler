"""A window probably open, seen without a sensor (G11 F; provisional, K4).

A room whose zone has no window sensor, and no automatic window detection in VT, looks with an
open window like a room the curve is too low for: it stays short however warm the water is. The
plugin's own guard tells them apart by speed: a room falling by ``WINDOW_DROP_K`` within
``WINDOW_DROP_S`` while its valve is open and heat flows — about VT's own 3 °C/h — has a window
probably open. Such a room is left out of the comfort correction's rise and of the long-run rule
until it warms again, ``WINDOW_WARM_K`` over its lowest reading since, and for at least
``WINDOW_HOLD_S``. It only informs: nothing else changes.

Reference values read on 2026-10-10: radiator-mounted sensors about 0.5 K in 2 min to 1.5 K in
10 min; room sensors away from the window about 0.3–0.5 K in 5–10 min; Danfoss Ally pauses
30 min. A tilted window cools slowly and is not caught here: its room stays short, and the
comfort correction's warning names the heat loss among the causes.
"""

from __future__ import annotations

from dataclasses import dataclass

WINDOW_DROP_K = 0.5  # this much fall ...
WINDOW_DROP_S = 600.0  # ... within this long, while the room heats
WINDOW_HOLD_S = 1800.0  # left out at least this long
WINDOW_WARM_K = 0.2  # and until the room is this far over its lowest reading since
_EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class WindowWatch:
    """One room: its readings within the last ``WINDOW_DROP_S``, oldest first, and — while a
    window is probably open — since when, and its lowest reading since."""

    readings: tuple[tuple[float, float], ...] = ()
    since: float | None = None
    lowest: float | None = None

    @property
    def suspected(self) -> bool:
        return self.since is not None


def follow_window(
    watch: WindowWatch, now: float, temperature: float | None, heating: bool
) -> WindowWatch:
    """One look at a room: its ``temperature`` now (``None``: unknown, kept out), and whether it
    ``heating`` — its valve open and heat flowing — which a fall must happen in to count. A
    moment before the last reading (the wall clock set back) starts the watch again."""
    if watch.readings and now < watch.readings[-1][0]:
        watch = WindowWatch()
    kept = tuple((t, value) for t, value in watch.readings if now - t <= WINDOW_DROP_S)
    if temperature is None:
        return WindowWatch(kept, watch.since, watch.lowest)
    readings = (*kept, (now, temperature))
    if watch.since is not None:
        lowest = temperature if watch.lowest is None else min(watch.lowest, temperature)
        warmed = temperature - lowest >= WINDOW_WARM_K - _EPSILON
        if now - watch.since >= WINDOW_HOLD_S and warmed:
            return WindowWatch(readings)
        return WindowWatch(readings, watch.since, lowest)
    highest = max(value for _t, value in readings)
    if heating and highest - temperature >= WINDOW_DROP_K - _EPSILON:
        return WindowWatch(readings, now, temperature)
    return WindowWatch(readings)
