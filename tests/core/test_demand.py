"""Boiler demand from the zones."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.vtherm_smart_boiler.core.demand import (
    Demand,
    DemandConfig,
    boiler_demand,
    zone_wants_heat,
)
from custom_components.vtherm_smart_boiler.core.readings import ZoneState

NOW = 1000.0
AGE = 600.0


def zone(zid: str = "z", **kw) -> ZoneState:
    kw.setdefault("heating_enabled", True)
    kw.setdefault("reported_at", NOW)
    return ZoneState(zid, **kw)


@pytest.mark.parametrize(
    ("state", "wants"),
    [
        (zone(valve_open=0.3), True),
        (zone(valve_open=0.03), False),
        (zone(on_percent=0.5), True),
        (zone(calling=True), True),  # no opening: VT's own flag decides
        (zone(calling=False), False),
        (zone(valve_open=0.0, calling=True), False),  # the opening decides
        (zone(valve_open=0.8, heating_enabled=False), False),  # sleeping or off
        # VT's own view of its devices wins: a switch on, a valve open (its minimal activation
        # time respected), a climate heating.
        (zone(valve_open=0.03, device_active=True), True),
        (zone(on_percent=0.5, device_active=False), False),
        # "auto" or heat_cool: heats only while its action says so.
        (zone(auto_mode=True, calling=True), True),
        (zone(auto_mode=True, calling=False, on_percent=0.8, device_active=True), False),
        (zone(auto_mode=True, on_percent=0.8), True),
    ],
)
def test_zone_wants_heat(state: ZoneState, wants: bool) -> None:
    assert zone_wants_heat(state, 0.05) is wants


def test_count_threshold() -> None:
    zones = [zone("a", valve_open=0.5), zone("b", valve_open=0.0)]
    assert boiler_demand(zones, NOW, AGE, DemandConfig()).wanted is True
    two = DemandConfig(count_threshold=2)
    result = boiler_demand(zones, NOW, AGE, two)
    assert result == Demand(False, 1, None, 0.5, 2)
    assert result.unknown == ()


def test_power_threshold_can_add_demand() -> None:
    zones = [
        zone("a", on_percent=0.5, power=3.0),
        zone("b", on_percent=0.4, power=1.0),
        zone("c", on_percent=0.0, power=2.0),
    ]
    config = DemandConfig(count_threshold=3, power_threshold_kw=1.5)
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.power_kw == pytest.approx(1.9)
    assert result.wanted is True
    stricter = DemandConfig(count_threshold=3, power_threshold_kw=2.0)
    assert boiler_demand(zones, NOW, AGE, stricter).wanted is False


def test_opening_threshold_can_add_demand() -> None:
    zones = [zone("a", valve_open=0.6), zone("b", valve_open=0.2)]
    config = DemandConfig(count_threshold=3, opening_threshold=0.5)
    assert boiler_demand(zones, NOW, AGE, config).wanted is True


def test_stale_zones_do_not_count_and_no_fresh_zone_is_unknown() -> None:
    stale = zone("a", valve_open=0.9, reported_at=NOW - 2 * AGE)
    assert boiler_demand([stale], NOW, AGE, DemandConfig()).wanted is None
    assert boiler_demand([], NOW, AGE, DemandConfig()) == Demand(None)
    mixed = boiler_demand([stale, zone("b", valve_open=0.0)], NOW, AGE, DemandConfig())
    assert mixed.wanted is False
    assert mixed.fresh_zones == 1
    assert mixed.unknown == ("a",)


@pytest.mark.parametrize(
    "unknown",
    [
        zone("a", heating_enabled=None, valve_open=0.9),  # `unavailable`, or a mode not known
        zone("a", ready=False, valve_open=0.9),  # heating, but VT has not finished starting it
        zone("a", reported=False, valve_open=0.9),  # heating, VT's first refresh still to come
        zone("a", valve_open=0.9, temperature_at=NOW - 2 * AGE),  # its room sensor went quiet
    ],
)
def test_a_zone_that_is_not_known_never_means_no_demand(unknown: ZoneState) -> None:
    """Alone it makes demand unknown (decision 3 then decides); with others, the known ones
    decide."""
    assert boiler_demand([unknown], NOW, AGE, DemandConfig()) == Demand(None, unknown=("a",))
    other = boiler_demand([unknown, zone("b", valve_open=0.0)], NOW, AGE, DemandConfig())
    assert other.wanted is False
    assert other.unknown == ("a",)


def test_the_temperature_age_decides_freshness() -> None:
    """VT rewrites its climate often: its report time says little about the room sensor."""
    fresh = zone(valve_open=0.5, reported_at=NOW - 3 * AGE, temperature_at=NOW - 10.0)
    assert fresh.is_fresh(NOW, AGE)
    assert not zone(reported_at=NOW, temperature_at=NOW - 2 * AGE).is_fresh(NOW, AGE)


def test_each_criterion_can_stand_alone() -> None:
    """As in VT, a count threshold of 0 turns the count off."""
    zones = [zone("a", valve_open=0.3, power=1.0), zone("b", valve_open=0.2, power=1.0)]
    by_opening = DemandConfig(count_threshold=0, opening_threshold=0.5)
    assert boiler_demand(zones, NOW, AGE, by_opening).wanted is False
    by_power = DemandConfig(count_threshold=0, power_threshold_kw=0.4)
    assert boiler_demand(zones, NOW, AGE, by_power).wanted is True


def test_the_count_never_asks_for_more_zones_than_are_known() -> None:
    zones = [zone("a", valve_open=0.6), zone("b", heating_enabled=None)]
    assert boiler_demand(zones, NOW, AGE, DemandConfig(count_threshold=2)).wanted is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"count_threshold": -1},
        {"zone_opening": 1.0},
        {"count_threshold": 0},
        {"opening_threshold": 0.0},  # would mean demand for ever
        {"power_threshold_kw": 0.0},
    ],
)
def test_invalid_config(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must"):
        DemandConfig(**kwargs)


# --- X3: calling zones only, the power over the cycle, criteria without data, S-34, shedding ----


def test_the_opening_threshold_follows_calling_zones_only() -> None:
    """T-46 (P-13): an over_switch zone keeps its duty cycle through its off phase; VT's device
    is off, so the zone does not call, and its duty cycle is no opening of a calling zone."""
    switch = zone("a", on_percent=0.6, device_active=False)
    config = DemandConfig(count_threshold=0, opening_threshold=0.5)
    result = boiler_demand([switch], NOW, AGE, config)
    assert result.wanted is False
    assert result.widest_opening is None
    assert result.criteria_without_data == ()  # the zone publishes an opening: data, no call


def test_the_power_criterion_counts_a_switch_zone_through_its_off_phase() -> None:
    """VT counts a zone's mean power over its cycle — 0.6 of 2 kW for a switch zone in its off
    phase — while heat can flow: another zone's valve is open."""
    switch = zone("a", on_percent=0.6, power=2.0, device_active=False)
    valve = zone("b", valve_open=0.5)
    config = DemandConfig(count_threshold=0, power_threshold_kw=1.0)
    result = boiler_demand([switch, valve], NOW, AGE, config)
    assert result.power_kw == pytest.approx(1.2)
    assert result.wanted is True
    published = zone("a", on_percent=0.6, power=2.0, mean_power=1.2, device_active=False)
    assert boiler_demand([published, valve], NOW, AGE, config).power_kw == pytest.approx(1.2)


def test_the_power_criterion_needs_an_open_valve_or_an_active_device() -> None:
    """Mean power of 3 kW, but no zone has its valve open or its device on: no heat can flow,
    so the power criterion asks for nothing — and it still has data."""
    zones = [
        zone("a", on_percent=0.6, power=2.5, device_active=False),
        zone("b", on_percent=0.6, mean_power=1.5, power=2.5, device_active=False),
    ]
    config = DemandConfig(count_threshold=0, power_threshold_kw=1.0)
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.wanted is False
    assert result.criteria_without_data == ()
    active = [*zones[:1], zone("b", on_percent=0.6, power=2.5, device_active=True)]
    assert boiler_demand(active, NOW, AGE, config).wanted is True


def test_a_criterion_without_data_is_not_no_demand() -> None:
    """T-27 (P-14): a count of 0 and only a power threshold, while no zone has a device power
    (VT publishes 0 when none is set): whether to heat is not known — never a silent "no"."""
    zones = [zone("a", valve_open=0.6, device_active=True), zone("b", valve_open=0.3)]
    config = DemandConfig(count_threshold=0, power_threshold_kw=1.0)
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.wanted is None
    assert result.criteria_without_data == ("power",)
    assert result.power_kw is None


def test_an_opening_criterion_without_data_is_not_no_demand() -> None:
    """No zone publishes an opening or a duty cycle (VT's over_climate): the opening
    criterion cannot be judged."""
    zones = [zone("a", calling=True), zone("b", calling=False)]
    config = DemandConfig(count_threshold=0, opening_threshold=0.5)
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.wanted is None
    assert result.criteria_without_data == ("opening",)


@pytest.mark.parametrize(("calling", "wanted"), [(True, True), (False, False)])
def test_only_the_criterion_without_data_is_left_out(calling: bool, wanted: bool) -> None:
    """A count of 1 and a power threshold without data: the count decides. The power lacks
    data whether the zone calls or not — what the zones in a heating mode publish decides — so
    the criterion's state does not flip with each call (check C's F2)."""
    zones = [zone("a", valve_open=0.6 if calling else 0.0)]
    config = DemandConfig(count_threshold=1, power_threshold_kw=1.0)
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.wanted is wanted
    assert result.criteria_without_data == ("power",)


def test_a_device_power_of_zero_is_no_data_but_a_mean_power_of_zero_is_none_now() -> None:
    """A zone with its device power known and nothing flowing now feeds the criterion with 0."""
    zones = [zone("a", valve_open=0.6, power=2.0, mean_power=0.0)]
    config = DemandConfig(count_threshold=0, power_threshold_kw=1.0)
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.criteria_without_data == ()
    assert result.power_kw == 0.0
    assert result.wanted is False


@pytest.mark.parametrize(
    ("ready", "reported", "known"),
    [
        (None, False, False),  # VT's placeholder: neither ``is_ready`` nor ``specific_states``
        (False, False, False),  # ``is_ready`` false: VT cannot start it
        (None, True, True),  # an older VT: ``specific_states`` without ``is_ready``
        (True, True, True),  # started
    ],
)
def test_an_off_zone_not_started_after_the_recognition(
    ready: bool | None, reported: bool, known: bool
) -> None:
    """T-17 (S-34) and SB-02: "off" is the user's "off" — no demand — only on a zone VT has
    started. VT's placeholder, which VT 10.4.0 keeps for good while none of the thermostat's
    devices reports, and ``is_ready`` false stay unknown after the recognition period too
    (check C's F1)."""
    off = zone("a", heating_enabled=False, ready=ready, reported=reported, temperature=19.0)
    result = boiler_demand([off], NOW, AGE, DemandConfig())
    assert result.wanted is (False if known else None)
    assert result.unknown == (() if known else ("a",))


@pytest.mark.parametrize("ready", [None, False], ids=["placeholder", "not_ready"])
def test_a_zone_vt_has_not_started_never_blocks_the_count(ready: bool | None) -> None:
    """Check C's F1: a count of 2 over two zones, one calling, the other a thermostat VT has not
    started — its placeholder "off" or ``is_ready`` false. It is unknown, the count is capped by
    the known zones and the calling room gets heat: never a zone without demand."""
    calling = zone("a", valve_open=0.6, device_active=True, ready=True, reported=True)
    dead = zone("b", heating_enabled=False, ready=ready, reported=False, temperature=18.0)
    result = boiler_demand([calling, dead], NOW, AGE, DemandConfig(count_threshold=2))
    assert result.wanted is True
    assert result.unknown == ("b",)
    assert result.fresh_zones == 1


@pytest.mark.parametrize("ready", [False, None])
def test_a_heating_zone_not_ready_is_unknown(ready: bool | None) -> None:
    heating = zone("a", ready=ready, reported=False, valve_open=0.6)
    result = boiler_demand([heating], NOW, AGE, DemandConfig())
    assert result.wanted is None
    assert result.unknown == ("a",)


def test_a_shed_zone_has_no_demand_and_no_power() -> None:
    """T-45's core: VT's power shedding holds the zone off — whatever its duty cycle or its
    device showed last."""
    shed = zone("a", valve_open=0.6, device_active=True, power=2.0, on_percent=0.6, shedding=True)
    assert zone_wants_heat(shed, 0.05) is False
    config = DemandConfig(count_threshold=1, power_threshold_kw=0.5, opening_threshold=0.3)
    result = boiler_demand([shed], NOW, AGE, config)
    assert result.wanted is False
    assert result.zones_wanting == 0
    assert result.power_kw == 0.0
    assert result.widest_opening is None


def test_a_remembered_zone_keeps_its_last_answer() -> None:
    """The grace (decision 3): a zone that stopped answering keeps its last known state in
    demand, as a known zone — the count's cap included."""
    last = zone("a", valve_open=0.6, device_active=True, power=2.0, on_percent=0.6)
    gone = ZoneState("a")  # unavailable now
    other = zone("b", valve_open=0.0)
    result = boiler_demand([gone, other], NOW, AGE, DemandConfig(), memory={"a": last})
    assert result.wanted is True
    assert result.fresh_zones == 2
    assert result.unknown == ()
    two = DemandConfig(count_threshold=2)
    assert boiler_demand([gone], NOW, AGE, two, memory={"a": last}).wanted is True  # capped
    assert boiler_demand([gone, other], NOW, AGE, DemandConfig()).wanted is False  # no memory


@pytest.mark.parametrize(
    "zones",
    [
        [],
        [ZoneState("a")],
        [zone("a", heating_enabled=None, power=None, mean_power=None, valve_open=None)],
    ],
)
def test_no_zone_known_names_no_criterion(zones: list[ZoneState]) -> None:
    """Every zone unknown is decision 3's own case, not a criterion without data."""
    config = DemandConfig(count_threshold=0, power_threshold_kw=1.0, opening_threshold=0.5)
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.wanted is None
    assert result.criteria_without_data == ()


# --- PB-23: only heating zones give a criterion data; a calling zone no criterion can see ----

POWER_ONLY = DemandConfig(count_threshold=0, power_threshold_kw=1.0)
OPENING_ONLY = DemandConfig(count_threshold=0, opening_threshold=0.5)
BOTH = DemandConfig(count_threshold=0, power_threshold_kw=1.0, opening_threshold=0.5)


def test_an_off_zone_publishing_an_opening_gives_the_criterion_no_data() -> None:
    """PB-23: a count of 0 and only an opening threshold; an "off" valve zone publishes an
    opening of 0 and the calling room is a plain over_climate one without an opening. The off
    zone must not make the criterion "with data": no criterion can be judged (PB-03's case), and
    the calling zone is named — never a silent "no"."""
    zones = [zone("off", heating_enabled=False, valve_open=0.0), zone("trv", calling=True)]
    config = DemandConfig(count_threshold=0, opening_threshold=0.5)
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.wanted is None
    assert result.criteria_without_data == ("opening",)
    assert result.zones_without_data == ("trv",)


def test_an_idle_zone_with_a_device_power_gives_the_power_criterion_data() -> None:
    """A zone in a heating mode with a device power, idle — no cycle running, its power 0 now:
    a value, not "no data" — gives the power criterion data whether a zone calls or not (check
    C's F2); the calling zone that cannot feed it is named for the alarm (PB-23)."""
    zones = [zone("idle", power=2.0, on_percent=0.0), zone("valve", valve_open=0.6)]
    config = DemandConfig(count_threshold=0, power_threshold_kw=1.0)
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.wanted is False
    assert result.criteria_without_data == ()
    assert result.power_kw == 0.0
    assert result.zones_without_data == ("valve",)


def test_a_zone_whose_cycle_runs_gives_the_power_criterion_data() -> None:
    """A switch zone in the off part of its cycle keeps its mean power, which the criterion sums
    as VT does: the criterion has data and decides; the calling zone that cannot feed it is
    still named, as its own call is not what the boiler follows."""
    switch = zone("switch", on_percent=0.6, power=2.0, device_active=False)
    valve = zone("valve", valve_open=0.5)
    config = DemandConfig(count_threshold=0, power_threshold_kw=1.0)
    result = boiler_demand([switch, valve], NOW, AGE, config)
    assert result.wanted is True
    assert result.power_kw == pytest.approx(1.2)
    assert result.criteria_without_data == ()
    assert result.zones_without_data == ("valve",)


def test_a_calling_zone_no_criterion_can_see_is_named_while_others_decide() -> None:
    """PB-23 (b): a calling zone that feeds no configured criterion is not silently ignored:
    the others' data decides (0.5 kW, below the threshold) and the zone is named for the alarm
    — it never starts the boiler on its own."""
    fed = zone("fed", valve_open=0.6, power=1.0, mean_power=0.5, device_active=True)
    blind = zone("blind", valve_open=0.6)
    config = DemandConfig(count_threshold=0, power_threshold_kw=1.0)
    result = boiler_demand([fed, blind], NOW, AGE, config)
    assert result.wanted is False
    assert result.criteria_without_data == ()
    assert result.zones_without_data == ("blind",)


@pytest.mark.parametrize(
    "config",
    [
        DemandConfig(count_threshold=0, power_threshold_kw=1.0),
        DemandConfig(count_threshold=0, opening_threshold=0.5),
        DemandConfig(count_threshold=0, power_threshold_kw=1.0, opening_threshold=0.5),
        DemandConfig(count_threshold=1, power_threshold_kw=1.0),
    ],
)
def test_with_no_zone_in_a_heating_mode_there_is_no_demand(config: DemandConfig) -> None:
    """Summer: every known zone "off", the others not known — whatever the zones publish (power
    ``None``, no opening, an opening of 0): no demand, and no criterion lacks data, so no end
    state, no alarm and nothing handed back while the house needs no heat."""
    zones = [
        zone("blind", heating_enabled=False, calling=False),
        zone("off", heating_enabled=False, valve_open=0.0),
        zone("gone", heating_enabled=None, calling=True),
    ]
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.wanted is False
    assert result.criteria_without_data == ()
    assert result.zones_without_data == ()


@pytest.mark.parametrize(
    ("config", "without"),
    [(POWER_ONLY, ("power",)), (OPENING_ONLY, ("opening",)), (BOTH, ("power", "opening"))],
)
def test_a_criterion_lacks_data_whether_a_zone_calls_or_not(
    config: DemandConfig, without: tuple[str, ...]
) -> None:
    """Check C's F2: whether a criterion lacks data follows what the zones in a heating mode can
    feed — here a device power ``None`` and no opening — not whether one calls now. The answer
    stays "unknown" through every start and end of a call; a "no" at each call's end would take
    the boiler again at each edge."""
    for calling in (True, False, True, False):
        blind = zone("z", calling=calling, power=None, mean_power=None)
        result = boiler_demand([blind], NOW, AGE, config)
        assert result.wanted is None
        assert result.criteria_without_data == without
        assert result.power_kw is None
        assert result.zones_without_data == (("z",) if calling else ())


def test_an_opening_or_a_mean_power_of_0_is_a_value() -> None:
    """Negative: an idle zone in a heating mode publishing an opening of 0, or a mean power of
    0 beside its device power, gives its criterion data: "no", never "unknown"."""
    idle = zone("z", valve_open=0.0, power=2.0, mean_power=0.0, calling=False)
    result = boiler_demand([idle], NOW, AGE, BOTH)
    assert result.wanted is False
    assert result.criteria_without_data == ()
    assert result.power_kw == 0.0


def test_power_shedding_does_not_change_which_criteria_have_data() -> None:
    """A zone VT's power shedding holds off is still in its heating mode: it removes the zone's
    demand and power, not its data — the criterion does not flip to "unknown" while it lasts."""
    fed = zone("fed", power=2.0, on_percent=0.6, device_active=True)
    blind = zone("blind", valve_open=0.6)
    for shedding, wanted in ((False, True), (True, False)):
        result = boiler_demand([replace(fed, shedding=shedding), blind], NOW, AGE, POWER_ONLY)
        assert result.wanted is wanted
        assert result.criteria_without_data == ()


@pytest.mark.parametrize(
    ("calling", "config", "without"),
    [
        # The zone's device power and mean power unknown (``None``).
        (zone("z", valve_open=0.6, power=None, mean_power=None), POWER_ONLY, ("power",)),
        # No opening and no duty cycle (``None``): VT's over_climate.
        (zone("z", calling=True, valve_open=None, on_percent=None), OPENING_ONLY, ("opening",)),
        (zone("z", calling=True, power=None), BOTH, ("power", "opening")),
    ],
)
def test_a_calling_zone_without_the_data_is_named_with_its_criterion(
    calling: ZoneState, config: DemandConfig, without: tuple[str, ...]
) -> None:
    result = boiler_demand([calling], NOW, AGE, config)
    assert result.wanted is None
    assert result.criteria_without_data == without
    assert result.zones_without_data == ("z",)


def test_a_count_sees_every_calling_zone_and_an_unknown_zone_is_never_named() -> None:
    """Negative: with a count of 1 or more every calling zone feeds a criterion — none is
    named; an unknown zone (no mode, or stale) is decision 3's case, never named here."""
    calling = zone("z", valve_open=0.6)
    config = DemandConfig(count_threshold=1, power_threshold_kw=1.0)
    result = boiler_demand([calling], NOW, AGE, config)
    assert result.wanted is True
    assert result.zones_without_data == ()
    stale = zone("stale", valve_open=0.6, reported_at=NOW - 2 * AGE)
    unknown = zone("unknown", heating_enabled=None, valve_open=0.6)
    fed = zone("fed", valve_open=0.6, power=2.0)
    result = boiler_demand([stale, unknown, fed], NOW, AGE, POWER_ONLY)
    assert result.zones_without_data == ()
    assert result.unknown == ("stale", "unknown")
    assert result.wanted is True


# --- P-126: VT's own states as scenarios, zone by zone and step by step -----------------------
# What each zone shows is what the plugin reads from VT 10.4.0 (``vtherm_attributes``): its HVAC
# mode (``heating_enabled``), whether VT has started it (``ready``/``reported``), its devices
# (``device_active``), its duty cycle, and the safety and power managers' states. The
# vendored-VT versions of the first two are X3's T-44 and T-45.


ONE_ZONE = DemandConfig()


def demand_over(
    steps: list[list[ZoneState]], config: DemandConfig = ONE_ZONE, **kwargs
) -> list[tuple[bool | None, int, tuple[str, ...]]]:
    """Demand at each step: wanted, the zones known, the zones unknown."""
    results = [boiler_demand(zones, NOW, AGE, config, **kwargs) for zones in steps]
    return [(r.wanted, r.fresh_zones, r.unknown) for r in results]


def test_a_zone_in_vts_safety_mode_is_followed_as_vt_runs_it() -> None:
    """VT's safety mode (the room sensor gone quiet): VT keeps running the zone on its safety
    duty cycle, its device pulsing on and off. The zone stays known and demand follows VT's
    pulses — never unknown, never "no demand" for the whole mode; the lost sensor only raises
    the zone's alarm (S-35)."""
    normal = zone("a", on_percent=0.6, device_active=True, temperature=19.0)
    pulse_on = replace(
        normal, on_percent=0.1, device_active=True, safety_on=True, room_sensor_lost=True
    )
    pulse_off = replace(pulse_on, device_active=False)
    other = zone("b", on_percent=0.0, device_active=False)
    assert demand_over(
        [[normal, other], [pulse_on, other], [pulse_off, other], [pulse_on, other]]
    ) == [(True, 2, ()), (True, 2, ()), (False, 2, ()), (True, 2, ())]
    power = DemandConfig(count_threshold=0, power_threshold_kw=0.5)
    safety = boiler_demand([replace(pulse_on, power=2.0, mean_power=0.2)], NOW, AGE, power)
    assert (safety.wanted, safety.power_kw) == (False, 0.2)  # its safety duty's power


def test_vts_power_shedding_takes_a_zone_out_of_demand_until_it_ends() -> None:
    """VT's power manager sheds a zone (overpowering on): the zone is known and wants nothing,
    its power counts nothing — whatever its duty cycle or device showed last — while the other
    zones decide; demand comes back with the zone once the shedding ends."""
    calling = zone("a", on_percent=0.6, device_active=True, power=2.0)
    shed = replace(calling, shedding=True)
    quiet = zone("b", on_percent=0.0, device_active=False, power=1.0)
    warm = replace(quiet, on_percent=0.5, device_active=True)
    config = DemandConfig(count_threshold=1, power_threshold_kw=1.5)
    results = [
        boiler_demand(zones, NOW, AGE, config)
        for zones in ([calling, quiet], [shed, quiet], [shed, warm], [calling, quiet])
    ]
    assert [(r.wanted, r.zones_wanting, r.power_kw, r.fresh_zones) for r in results] == [
        (True, 1, 1.2, 2),
        (False, 0, 0.0, 2),  # a shed zone known, not unknown: no end state
        (True, 1, 0.5, 2),
        (True, 1, 1.2, 2),
    ]


def test_an_open_window_switching_a_zone_off_leaves_it_known_without_demand() -> None:
    """VT's window detection with its "turn off" action: the zone goes to "off" while VT keeps
    it started — known, no demand, so the others decide and no "no zone known" end state
    follows; its "frost" or "eco" action keeps the mode and lowers the target, and the valve
    closing ends the demand. The window closed, the zone heats again."""
    heating = zone("a", valve_open=0.7, calling=True, ready=True, reported=True)
    window_off = replace(heating, heating_enabled=False, valve_open=0.0, calling=False)
    window_frost = replace(heating, target=7.0, valve_open=0.0, calling=False)
    assert demand_over([[heating], [window_off], [window_frost], [heating]]) == [
        (True, 1, ()),
        (False, 1, ()),
        (False, 1, ()),
        (True, 1, ()),
    ]
    other = zone("b", valve_open=0.4)
    assert demand_over([[window_off, other]], DemandConfig(count_threshold=2)) == [
        (False, 2, ())  # the window's zone counts as known: two zones, one wants heat
    ]


def test_a_vt_restart_off_and_not_ready_then_started() -> None:
    """VT reloads: before its first refresh each thermostat shows a placeholder "off", without
    ``is_ready`` — kept by VT 10.4.0 while none of its devices reports. Such a zone is unknown,
    during the recognition period and after it (check C's F1), as is a heating mode VT has not
    started. Once VT has started the zone, it counts as it shows."""
    placeholder = zone("a", heating_enabled=False, ready=None, reported=False, temperature=None)
    heat_unstarted = zone("a", valve_open=0.6, ready=False, reported=False)
    started = zone("a", valve_open=0.6, ready=True, reported=True)
    assert demand_over([[placeholder], [heat_unstarted], [started]]) == [
        (None, 0, ("a",)),
        (None, 0, ("a",)),
        (True, 1, ()),
    ]
