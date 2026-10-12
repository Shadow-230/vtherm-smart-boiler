"""Installation model: lookups and configuration issues."""

from __future__ import annotations

from custom_components.vtherm_smart_boiler.core.installation import (
    Boiler,
    BoilerClass,
    BoilerType,
    Circuit,
    CircuitControl,
    DhwType,
    EmitterType,
    HeatSource,
    Installation,
    Issue,
    IssueCode,
    Severity,
    Zone,
)

BOILER = Boiler(BoilerClass.READ_ONLY)


def test_lookups() -> None:
    installation = Installation(
        BOILER,
        circuits=(Circuit("main"), Circuit("floor", CircuitControl.SEPARATE)),
        zones=(
            Zone("a", "main"),
            Zone("b", "floor", EmitterType.UNDERFLOOR),
            Zone("c", "floor", EmitterType.UNDERFLOOR),
        ),
    )
    assert installation.circuit("floor") == Circuit("floor", CircuitControl.SEPARATE)
    assert installation.circuit("nope") is None
    assert installation.zone("a") == Zone("a", "main")
    assert [z.zone_id for z in installation.zones_in("floor")] == ["b", "c"]
    assert installation.emitters_in("floor") == {EmitterType.UNDERFLOOR}
    assert installation.issues() == []
    assert installation.is_valid


def test_errors_make_it_invalid() -> None:
    installation = Installation(
        BOILER,
        circuits=(
            Circuit("main"),
            Circuit("main"),
            Circuit("tmv", CircuitControl.PASSIVE_FIXED),
        ),
        zones=(Zone("a", "main"), Zone("a", "main"), Zone("b", "ghost"), Zone("c", "tmv")),
    )
    issues = installation.issues()
    assert Issue(IssueCode.DUPLICATE_CIRCUIT, Severity.ERROR, "main") in issues
    assert Issue(IssueCode.DUPLICATE_ZONE, Severity.ERROR, "a") in issues
    assert Issue(IssueCode.UNKNOWN_CIRCUIT, Severity.ERROR, "b") in issues
    assert Issue(IssueCode.FIXED_TEMPERATURE_MISSING, Severity.ERROR, "tmv") in issues
    assert not installation.is_valid


def test_no_circuit_is_an_error() -> None:
    installation = Installation(BOILER, circuits=())
    assert installation.issues() == [Issue(IssueCode.NO_CIRCUIT, Severity.ERROR)]


def test_warnings_keep_it_valid() -> None:
    installation = Installation(
        BOILER,
        circuits=(Circuit("shared"), Circuit("spare")),
        zones=(Zone("a", "shared", EmitterType.UNDERFLOOR), Zone("b", "shared")),
    )
    assert set(installation.issues()) == {
        Issue(IssueCode.UNDERFLOOR_WITHOUT_MAX_FLOW, Severity.WARNING, "shared"),
        Issue(IssueCode.EMPTY_CIRCUIT, Severity.WARNING, "spare"),
    }
    assert installation.is_valid


def test_underfloor_cap_given_or_circuit_mixed_is_fine() -> None:
    installation = Installation(
        BOILER,
        circuits=(
            Circuit("shared", max_flow=45.0),
            Circuit("mixed", CircuitControl.THROUGH_BOILER),
        ),
        zones=(
            Zone("a", "shared", EmitterType.UNDERFLOOR),
            Zone("b", "mixed", EmitterType.UNDERFLOOR),
        ),
    )
    assert installation.issues() == []


def test_a_circuit_carries_its_alarm_temperature_and_time() -> None:
    """Decision 10: a circuit with a maximum carries the too-hot alarm's temperature and time;
    none by default."""
    circuit = Circuit("main", max_flow=40.0, max_flow_alarm=45.0, max_flow_alarm_s=600.0)
    assert (circuit.max_flow_alarm, circuit.max_flow_alarm_s) == (45.0, 600.0)
    assert Circuit("main").max_flow_alarm is None
    assert Circuit("main").max_flow_alarm_s is None


def test_a_zone_may_close_when_vt_switches_it_off() -> None:
    """Decision 4's per-zone option: off by default."""
    assert not Zone("a", "main").closes_when_off
    assert Zone("a", "main", closes_when_off=True).closes_when_off


def test_each_boiler_type_names_its_hot_water() -> None:
    """I6 (decision 8): the boiler type by its standard name keeps the hot-water kind the analysis
    reads — a combi with a built-in tank behaves as a tank (it reheats now and then), so an
    entry stored with it reads the same in a version that has only none, storage and combi."""
    assert {kind: kind.dhw for kind in BoilerType} == {
        BoilerType.SINGLE: DhwType.NONE,
        BoilerType.SINGLE_TANK: DhwType.STORAGE,
        BoilerType.COMBI: DhwType.COMBI,
        BoilerType.COMBI_TANK: DhwType.STORAGE,
    }
    assert [kind for kind in BoilerType if kind.heats_hot_water] == [
        BoilerType.SINGLE_TANK,
        BoilerType.COMBI,
        BoilerType.COMBI_TANK,
    ]


def test_a_stored_hot_water_kind_suggests_a_boiler_type() -> None:
    """I6 (decision 12): an entry made before the boiler type has its hot-water kind only; the
    form suggests the type it most likely is — a tank on a single-function boiler, the commoner
    one — and nothing for a value it cannot read."""
    assert BoilerType.suggested_for("none") is BoilerType.SINGLE
    assert BoilerType.suggested_for("storage") is BoilerType.SINGLE_TANK
    assert BoilerType.suggested_for("combi") is BoilerType.COMBI
    for raw in (None, "", "boiling", 3):
        assert BoilerType.suggested_for(raw) is None


def test_heat_sources_burn_fuel_except_electric() -> None:
    """I6 (decision 7): only a burner has a flame, flue gas and maybe condensing; an electric
    boiler has none of them. "Other" keeps every field, as an entry without an answer does."""
    assert [source for source in HeatSource if source.burns_fuel] == [
        HeatSource.GAS,
        HeatSource.OIL,
        HeatSource.OTHER,
    ]


def test_a_zone_split_by_its_devices_is_in_each_of_its_circuits() -> None:
    """I8.8b (decision F2): a zone may feed two circuits through its single devices — a radiator
    on the straight circuit, a floor loop behind a mixer — each listing with its own emitter;
    the zone itself is one, its devices are each circuit's."""
    installation = Installation(
        BOILER,
        circuits=(Circuit("main"), Circuit("floor", CircuitControl.SEPARATE)),
        zones=(
            Zone("living", "main", devices=frozenset({"switch.radiator"})),
            Zone("living", "floor", EmitterType.UNDERFLOOR, devices=frozenset({"switch.loop"})),
            Zone("bath", "main"),
        ),
    )
    assert installation.issues() == []
    assert installation.zone_ids == ("living", "bath")
    assert [z.devices for z in installation.zones_in("floor")] == [frozenset({"switch.loop"})]
    assert installation.emitters_in("main") == {EmitterType.RADIATOR}
    assert installation.emitters_in("floor") == {EmitterType.UNDERFLOOR}


def test_a_zone_listed_whole_twice_or_a_device_in_two_circuits_is_an_error() -> None:
    """A whole zone is one circuit's: listed again, whole or by devices, it is a duplicate; a
    device is one circuit's too."""
    whole = Installation(
        BOILER,
        circuits=(Circuit("main"), Circuit("floor", CircuitControl.SEPARATE)),
        zones=(Zone("a", "main"), Zone("a", "floor", devices=frozenset({"switch.loop"}))),
    )
    assert whole.issues() == [Issue(IssueCode.DUPLICATE_ZONE, Severity.ERROR, "a")]
    shared = Installation(
        BOILER,
        circuits=(Circuit("main"), Circuit("floor", CircuitControl.SEPARATE)),
        zones=(
            Zone("a", "main", devices=frozenset({"switch.one", "switch.two"})),
            Zone("a", "floor", devices=frozenset({"switch.two"})),
        ),
    )
    assert shared.issues() == [Issue(IssueCode.DUPLICATE_DEVICE, Severity.ERROR, "switch.two")]
    twice = Installation(
        BOILER,
        circuits=(Circuit("main"),),
        zones=(
            Zone("a", "main", devices=frozenset({"switch.one"})),
            Zone("a", "main", devices=frozenset({"switch.two"})),
        ),
    )
    assert twice.issues() == [Issue(IssueCode.DUPLICATE_ZONE, Severity.ERROR, "a")]
