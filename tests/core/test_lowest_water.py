"""The lowest water temperature's evidence and suggestion, the estimate from the boiler's minimum
power, and the wall thermostat's fallback (X6; decision 2, S-02, S-56; Q3.4)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from custom_components.vtherm_smart_boiler.core.building import (
    COARSE_CONFIDENCE,
    InsulationClass,
    loss_from_annual_energy,
    loss_from_coarse_answers,
    loss_from_design_load,
)
from custom_components.vtherm_smart_boiler.core.curve import HeatingCurve
from custom_components.vtherm_smart_boiler.core.history import History, ZoneSeries
from custom_components.vtherm_smart_boiler.core.lowest_water import (
    WALL_THERMOSTAT_ISSUE_S,
    EstimateGap,
    SetpointSource,
    SuggestionContext,
    SuggestionState,
    WallWarning,
    WaterSetBy,
    design_load_kw,
    estimate_from_power,
    suggest_lowest_water,
    wall_issue_due,
    wall_thermostat_fallback,
    wall_warning_since,
)
from custom_components.vtherm_smart_boiler.core.monitor import MonitorOptions
from custom_components.vtherm_smart_boiler.core.parameters import (
    Estimate,
    ParameterKey,
    ParameterSet,
    Source,
)
from custom_components.vtherm_smart_boiler.core.series import Series
from custom_components.vtherm_smart_boiler.core.signals import Signal

DAY = 86400.0
NOW = 100 * DAY
START = NOW - 6 * DAY  # inside the 7-day window
OPTIONS = MonitorOptions(has_dhw=False)  # declared without hot water: every burn heats
PLUGIN = SuggestionContext(set_by=WaterSetBy.PLUGIN, lowest=20.0, caps=(70.0,))
DEVICE = SuggestionContext(set_by=WaterSetBy.DEVICE, caps=(70.0,))
ZONE = "climate.a"


@dataclass
class Plant:
    """A boiler's burns as the history records them: the flame, the flow, the setpoint in force,
    one VT zone calling with its valve, hot water — from ``begin`` on."""

    begin: float = START
    t: float = 0.0
    flame: Series[bool] = field(default_factory=Series)
    flow: Series[float] = field(default_factory=Series)
    setpoint: Series[float] = field(default_factory=Series)
    calling: Series[bool] = field(default_factory=Series)
    valve: Series[float] = field(default_factory=Series)
    dhw: Series[bool] = field(default_factory=Series)

    def __post_init__(self) -> None:
        self.flame.append(self.begin, False)
        self.flow.append(self.begin, 15.0)
        self.calling.append(self.begin, True)
        self.dhw.append(self.begin, False)
        self.t = self.begin + 600.0

    def burn(
        self,
        minutes: float,
        *,
        setpoint: float = 20.0,
        end_flow: float | None = None,
        demand_ends: bool = False,
        calling: bool | None = True,
        dhw: bool = False,
        valve: float | None = 1.0,
        pause_min: float = 10.0,
        midway: bool | str | None = "calling",
    ) -> None:
        """One heating burn; by default it ends because the water reached its setpoint while
        the zone still calls, its valve fully open. ``midway``: what the zone shows for a minute
        in the middle of the burn (by default, still calling)."""
        start = self.t
        end = start + minutes * 60.0
        self.setpoint.append(start - 1.0, setpoint)
        self.calling.append(start - 1.0, calling)
        self.valve.append(start - 1.0, valve)
        self.flame.append(start, True)
        self.flow.append(start + 1.0, setpoint - 8.0)
        if midway != "calling":
            self.calling.append(start + 30.0, midway if isinstance(midway, bool) else None)
            self.calling.append(start + 90.0, calling)
        if dhw:
            self.dhw.append(start + 5.0, True)
        self.flow.append(end - 5.0, setpoint + 0.5 if end_flow is None else end_flow)
        if demand_ends:
            self.calling.append(end, False)
        self.flame.append(end, False)
        if dhw:
            self.dhw.append(end + 5.0, False)
        self.flow.append(end + 60.0, setpoint - 8.0)
        self.t = end + pause_min * 60.0

    def burns(self, count: int, minutes: float, **kw) -> None:
        for _ in range(count):
            self.burn(minutes, **kw)

    def history(
        self,
        *,
        flame: bool = True,
        flow: bool = True,
        setpoint: bool = True,
        read_back: bool = False,
        valve: bool = True,
    ) -> History:
        signals: dict[Signal, Series] = {Signal.DHW_ACTIVE: self.dhw}
        if flame:
            signals[Signal.FLAME] = self.flame
        if flow:
            signals[Signal.FLOW] = self.flow
        if setpoint and not read_back:
            signals[Signal.CH_SETPOINT] = self.setpoint
        zone = ZoneSeries(ZONE, calling=self.calling)
        if valve:
            zone.valve_open = self.valve
        history = History(signals=signals, zones={ZONE: zone})
        if read_back:
            history.setpoint_read_back = self.setpoint
        return history


def suggest(
    plant: Plant,
    context: SuggestionContext = PLUGIN,
    source: SetpointSource | None = SetpointSource.CH_SETPOINT,
    options: MonitorOptions = OPTIONS,
    **history,
):
    return suggest_lowest_water(
        plant.history(**history), source, NOW, ParameterSet(), options, context
    )


# --- the suggestion ------------------------------------------------------------------------------


@pytest.mark.parametrize(("count", "state"), [(19, "no_data"), (20, "suggestion")])
def test_no_suggestion_without_enough_burns(count: int, state: str) -> None:
    """Fewer than 20 counted burns (the verdict's minimum): "no data", no value. Negative: 20
    short burns at the floor qualify."""
    plant = Plant()
    plant.burns(count, 3)
    result = suggest(plant)
    assert result.state.value == state
    assert result.counted == count
    assert (result.value is None) is (count < 20)


def test_short_burns_at_the_floor_suggest_two_kelvin_more() -> None:
    """Under control: 30 counted burns at the lowest water temperature (20 °C), 70 % shorter
    than 10 min, each ended because the water was warm enough while the room still called — the
    suggestion is the reference + 2 K. Rounded up to 0.5 °C; a half short or fewer is good
    enough (a share of 0.5 does not qualify)."""
    plant = Plant()
    plant.burns(21, 3)
    plant.burns(9, 25)
    result = suggest(plant)
    assert result.state is SuggestionState.SUGGESTION
    assert result.value == 22.0
    assert (result.counted, result.short) == (30, 21)
    assert result.short_share == pytest.approx(0.7)
    assert result.reference == 20.0
    assert result.source is SetpointSource.CH_SETPOINT
    assert result.set_by is WaterSetBy.PLUGIN
    assert result.window_days == 7
    rounded = Plant()
    rounded.burns(30, 3, setpoint=20.3)
    context = SuggestionContext(set_by=WaterSetBy.PLUGIN, lowest=20.3, caps=(70.0,))
    assert suggest(rounded, context).value == 22.5  # 22.3 rounded up
    half = Plant()
    half.burns(15, 3)
    half.burns(15, 25)
    good = suggest(half)
    assert good.state is SuggestionState.GOOD_ENOUGH
    assert good.value is None


def test_burns_at_another_setpoint_do_not_count_under_control() -> None:
    """Under control only burns whose setpoint at their start was within 1 K of the lowest
    water temperature count: warmer water was the curve's, not the floor's."""
    plant = Plant()
    plant.burns(30, 3, setpoint=21.0)  # within 1 K
    assert suggest(plant).counted == 30
    warmer = Plant()
    warmer.burns(30, 3, setpoint=21.5)
    result = suggest(warmer)
    assert result.counted == 0
    assert result.state is SuggestionState.NO_DATA


@pytest.mark.parametrize(
    "case",
    [
        "demand_ends",
        "demand_unknown",
        "demand_unknown_midway",
        "demand_paused_midway",
        "hot_water",
        "hot_water_kind",
        "flame_lost",
        "valve_half_closed",
        "no_zone_data",
    ],
)
def test_burns_ended_by_demand_or_hot_water_do_not_count(case: str) -> None:
    """Burns that end because the rooms stopped asking (a TPI pulse), with hot water during
    them, of the hot-water kind, with the flame lost below the setpoint, with the calling zones'
    valves less than half open, or while the demand is not known, are no evidence: none of
    30 counts. Negative: a zone that reports no opening does not exclude a burn."""
    plant = Plant()
    options = OPTIONS
    kw: dict = {
        "demand_ends": {"demand_ends": True},
        "demand_unknown": {"calling": None, "valve": None},  # neither flag nor opening known
        "demand_unknown_midway": {"midway": None, "valve": None},  # known at the end only
        "demand_paused_midway": {"midway": False},  # a TPI pause inside the burn
        "hot_water": {"dhw": True},
        "flame_lost": {"end_flow": 18.5},  # more than 1 K under the setpoint
        "valve_half_closed": {"valve": 0.3},
    }.get(case, {})
    if case == "hot_water_kind":
        options = MonitorOptions(has_dhw=True)
        kw = {"dhw": True, "minutes": 3}
    minutes = kw.pop("minutes", 3)
    plant.burns(30, minutes, **kw)
    if case == "no_zone_data":
        history = plant.history()
        history.zones = {}
        result = suggest_lowest_water(
            history, SetpointSource.CH_SETPOINT, NOW, ParameterSet(), options, PLUGIN
        )
    else:
        result = suggest(plant, options=options)
    assert result.counted == 0, case
    assert result.state is SuggestionState.NO_DATA
    assert result.value is None
    unreported = Plant()
    unreported.burns(30, 3)
    assert suggest(unreported, valve=False).state is SuggestionState.SUGGESTION


@pytest.mark.parametrize(("dropped_at", "counted"), [(0.0, 30), (1.0, 30), (-60.0, 0)])
def test_the_flow_as_the_burn_ends_is_the_one_just_before_the_flame_went_out(
    dropped_at: float, counted: int
) -> None:
    """A flow reading that shares its moment with the flame going out, or comes after it, does
    not hide the flow the burn ended at; one that fell a minute before the end (a flame lost
    below the setpoint) does."""
    plant = Plant()
    for _ in range(30):
        end = plant.t + 180.0
        plant.burn(3)
        # The flow falls back at (or around) the flame's going out.
        plant.flow = Series((s.t, s.value) for s in plant.flow if s.t < end + dropped_at)
        plant.flow.append(end + dropped_at, 12.0)
        plant.flow.append(end + 60.0, 12.0)
    assert suggest(plant).counted == counted


def test_a_burn_cut_by_the_window_does_not_count() -> None:
    """A burn whose start or end is not seen (it began before the window, or runs on now) is
    not complete: not counted. Burns older than seven days are out of the window."""
    plant = Plant(begin=NOW - 9 * DAY)
    plant.burns(30, 3)  # nine days ago
    result = suggest(plant)
    assert result.counted == 0
    running = Plant()
    running.flame.append(NOW - 60.0, True)
    running.setpoint.append(NOW - 120.0, 20.0)
    assert suggest(running).counted == 0


@pytest.mark.parametrize(
    ("absent", "missing"),
    [
        ({"flame": False}, ("flame",)),
        ({"flow": False}, ("flow",)),
        ({"source": None}, ("ch_setpoint",)),
        ({"flame": False, "flow": False, "source": None}, ("flame", "flow", "ch_setpoint")),
    ],
)
def test_missing_flame_flow_or_setpoint_names_what_is_missing(
    absent: dict, missing: tuple[str, ...]
) -> None:
    """The missing-data rule: without the flame, the flow (an end on temperature cannot be told)
    or a setpoint source the suggestion is inactive, naming what is missing — never a guess."""
    plant = Plant()
    plant.burns(30, 3)
    source = absent.pop("source", SetpointSource.CH_SETPOINT)
    result = suggest(plant, source=source, **absent)
    assert result.state is SuggestionState.INACTIVE
    assert result.missing == missing
    assert result.value is None


def test_a_source_that_is_not_recorded_is_missing() -> None:
    """A source named, its series absent (a setpoint signal not mapped): inactive, naming it."""
    plant = Plant()
    plant.burns(30, 3)
    result = suggest(plant, setpoint=False)
    assert result.state is SuggestionState.INACTIVE
    assert result.missing == ("ch_setpoint",)


def test_the_read_back_is_a_source_of_its_own() -> None:
    """Under control without the setpoint signal, the control's setpoint read-back recorded into
    the history is the source; named so."""
    plant = Plant()
    plant.burns(30, 3)
    result = suggest(plant, source=SetpointSource.READ_BACK, read_back=True)
    assert result.state is SuggestionState.SUGGESTION
    assert result.source is SetpointSource.READ_BACK
    empty = suggest(plant, source=SetpointSource.READ_BACK)  # nothing recorded yet
    assert empty.state is SuggestionState.NO_DATA


@pytest.mark.parametrize(
    ("lowest", "caps", "value"),
    [
        (36.0, (70.0, 40.0), 38.0),  # the circuit's maximum 40 − 2 K
        (36.0, (39.3,), 37.0),  # 37.3 rounded down to 0.5 °C, still above the reference
        (49.5, (70.0,), 50.0),  # never above 50 °C
        (20.0, (), 22.0),  # no cap known: the setting's own ceiling only
    ],
)
def test_the_suggestion_stays_under_the_caps(
    lowest: float, caps: tuple[float, ...], value: float
) -> None:
    """Never above min(highest water temperature, circuit maximum, boiler maximum) − 2 K, nor
    above 50 °C."""
    plant = Plant()
    plant.burns(30, 3, setpoint=lowest)
    context = SuggestionContext(set_by=WaterSetBy.PLUGIN, lowest=lowest, caps=caps)
    result = suggest(plant, context)
    assert result.state is SuggestionState.SUGGESTION
    assert result.value == value


def test_no_raise_that_fits_under_the_caps_is_no_suggestion() -> None:
    """The evidence holds, but the caps leave no room above the reference: nothing to suggest
    — shown as not applicable with its evidence, never a value at or below the reference."""
    plant = Plant()
    plant.burns(30, 3, setpoint=38.5)
    context = SuggestionContext(set_by=WaterSetBy.PLUGIN, lowest=38.5, caps=(40.0,))
    result = suggest(plant, context)
    assert result.state is SuggestionState.NOT_APPLICABLE
    assert result.value is None
    assert result.counted == 30


@pytest.mark.parametrize("nothing_heats", [True, False])
def test_no_suggestion_while_standalone_is_handed_back(nothing_heats: bool) -> None:
    """A stand-alone gateway handed back: nothing heats, so there is nothing to suggest (not
    applicable), whatever the history holds — a missing source included. Negative: the same
    evidence otherwise suggests."""
    plant = Plant()
    plant.burns(30, 3)
    context = SuggestionContext(set_by=WaterSetBy.DEVICE, nothing_heats=nothing_heats)
    result = suggest(plant, context)
    assert (result.state is SuggestionState.NOT_APPLICABLE) is nothing_heats
    assert (result.value is None) is nothing_heats
    if nothing_heats:
        without = suggest(plant, context, source=None)
        assert without.state is SuggestionState.NOT_APPLICABLE
        assert without.missing == ()


def test_the_boilers_own_curve_is_judged_from_its_reported_setpoint() -> None:
    """Where the boiler's own curve (or a thermostat) sets the water: the reference is the
    lowest setpoint the source showed at the start of the burns that count otherwise; burns
    within 1 K of it count, warmer ones do not; the suggestion is worded for that device."""
    plant = Plant()
    plant.burns(12, 3, setpoint=30.0)
    plant.burns(10, 3, setpoint=31.0)
    plant.burns(15, 20, setpoint=36.0)  # milder burns at warmer water: another band
    result = suggest(plant, DEVICE)
    assert result.set_by is WaterSetBy.DEVICE
    assert result.reference == 30.0
    assert result.counted == 22
    assert result.state is SuggestionState.SUGGESTION
    assert result.value == 32.0
    lower = Plant()
    lower.burns(30, 3, setpoint=31.0)
    lower.burn(3, setpoint=28.0, end_flow=20.0)  # a flame loss: not counted, not the reference
    assert suggest(lower, DEVICE).reference == 31.0


def test_under_control_the_lowest_water_temperature_is_needed() -> None:
    with pytest.raises(ValueError, match="lowest temperature is needed"):
        SuggestionContext(set_by=WaterSetBy.PLUGIN)


# --- the estimate from the boiler's minimum power ------------------------------------------------

CURVE = HeatingCurve(design_outdoor=-15.0, design_flow=55.0, room=20.0, exponent=1.3)


def test_the_estimate_from_power_is_the_curves_flow_at_the_crossover() -> None:
    """Q3.4: T ≈ room + (design flow − room)·(P_min/P_design)^(1/n) — the curve's flow at the
    outdoor temperature where the house needs the boiler's minimum power; rounded to 0.5 °C.
    The research's example: 3 kW of 10 kW, radiators 55/20, n 1.3 → about 34 °C."""
    estimate = estimate_from_power(3.0, 10.0, CURVE, condensing=True)
    assert estimate.gap is None
    assert estimate.value == 34.0
    crossover = CURVE.room - (CURVE.room - CURVE.design_outdoor) * 0.3
    assert CURVE.flow(crossover) == pytest.approx(33.87, abs=0.01)


@pytest.mark.parametrize(
    ("min_power", "load", "curve", "condensing", "gap"),
    [
        (None, 10.0, CURVE, True, EstimateGap.MIN_POWER),
        (3.0, None, CURVE, True, EstimateGap.DESIGN_LOAD),
        (3.0, 10.0, None, True, EstimateGap.CURVE),
        (10.0, 10.0, CURVE, True, EstimateGap.MIN_POWER_NOT_BELOW_LOAD),
        (12.0, 10.0, CURVE, True, EstimateGap.MIN_POWER_NOT_BELOW_LOAD),
        (3.0, 10.0, CURVE, False, EstimateGap.NOT_CONDENSING),
        (None, None, None, False, EstimateGap.NOT_CONDENSING),  # never, whatever else
    ],
)
def test_no_estimate_without_its_inputs(
    min_power: float | None,
    load: float | None,
    curve: HeatingCurve | None,
    condensing: bool,
    gap: EstimateGap,
) -> None:
    """Shown only with the minimum power entered, a design load entered or measured with
    confidence, an entered curve and the minimum below the load — never for a boiler that does
    not condense (its manual's minimum governs, and a low figure could read as safe)."""
    estimate = estimate_from_power(min_power, load, curve, condensing=condensing)
    assert estimate.value is None
    assert estimate.gap is gap


def _with_loss(estimate: Estimate) -> ParameterSet:
    return ParameterSet().with_estimate(ParameterKey.LOSS_COEFFICIENT, estimate)


def test_only_an_entered_or_confidently_measured_load_counts() -> None:
    """The design load at the curve's design point: the loss entered (or given as a design
    load), or measured with the confidence the plugin counts (0.5) — never the coarse
    floor-area or annual-energy estimates, which move the result by several kelvin."""
    entered = _with_loss(loss_from_design_load(10.0, -15.0, 20.0))
    assert design_load_kw(entered, CURVE) == pytest.approx(10.0)
    measured = _with_loss(Estimate(0.3, Source.MEASURED, 0.6))
    assert design_load_kw(measured, CURVE) == pytest.approx(0.3 * 35.0)
    unsure = _with_loss(Estimate(0.3, Source.MEASURED, 0.4))
    assert design_load_kw(unsure, CURVE) is None
    coarse = _with_loss(loss_from_coarse_answers(120.0, InsulationClass.AVERAGE, -15.0, 20.0))
    assert coarse.get(ParameterKey.LOSS_COEFFICIENT).effective().confidence == COARSE_CONFIDENCE
    assert design_load_kw(coarse, CURVE) is None
    annual = _with_loss(loss_from_annual_energy(12000.0, 3000.0))
    assert design_load_kw(annual, CURVE) is None
    assert design_load_kw(ParameterSet(), CURVE) is None


def test_the_estimate_is_carried_beside_the_suggestion_and_never_applied() -> None:
    """The estimate travels with the suggestion only as information: the suggested value is the
    evidence's, whatever the estimate says."""
    plant = Plant()
    plant.burns(30, 3)
    estimate = estimate_from_power(3.0, 10.0, CURVE, condensing=True)
    context = SuggestionContext(
        set_by=WaterSetBy.PLUGIN, lowest=20.0, caps=(70.0,), estimate=estimate
    )
    result = suggest(plant, context)
    assert result.value == 22.0
    assert result.estimate == estimate


# --- the wall thermostat's fallback -------------------------------------------------------------


@pytest.mark.parametrize(
    ("mapped", "value", "warning"),
    [
        (False, None, WallWarning.NOT_MAPPED),
        (False, 20.0, WallWarning.NOT_MAPPED),
        (True, None, WallWarning.UNKNOWN),
        (True, 12.0, WallWarning.LOW),
        (True, 14.9, WallWarning.LOW),
        (True, 15.0, None),
        (True, 20.0, None),
    ],
)
def test_the_wall_thermostat_fallback_is_shown_and_warned(
    mapped: bool, value: float | None, warning: WallWarning | None
) -> None:
    """The temperature the wall thermostat keeps after a hand-back: from the optional signal,
    warned when it is not mapped, unknown or below 15 °C."""
    fallback = wall_thermostat_fallback(mapped, value)
    assert fallback.warning is warning
    assert fallback.setpoint == (value if mapped else None)


def test_the_wall_thermostat_issue_waits_30_minutes() -> None:
    """The repair issue once the mapped value has been low or unknown for 30 minutes; low then
    unknown is one stretch; a good value ends it; not mapped never starts one; a clock set back
    does not push it into the future."""
    low = wall_thermostat_fallback(True, 12.0)
    unknown = wall_thermostat_fallback(True, None)
    fine = wall_thermostat_fallback(True, 20.0)
    assert WALL_THERMOSTAT_ISSUE_S == 30 * 60.0  # provisional, K4
    since = wall_warning_since(None, low, 0.0)
    assert since == 0.0
    assert not wall_issue_due(since, WALL_THERMOSTAT_ISSUE_S - 1.0)
    since = wall_warning_since(since, unknown, 600.0)
    assert since == 0.0
    assert wall_issue_due(since, WALL_THERMOSTAT_ISSUE_S)
    assert wall_warning_since(since, fine, 2000.0) is None
    assert wall_warning_since(None, wall_thermostat_fallback(False, None), 0.0) is None
    assert wall_warning_since(5000.0, low, 100.0) == 100.0
    assert not wall_issue_due(None, 1e9)
