"""Installation model: lookups and configuration issues."""

from __future__ import annotations

from custom_components.vtherm_smart_boiler.core.installation import (
    Boiler,
    BoilerClass,
    Circuit,
    CircuitControl,
    EmitterType,
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
