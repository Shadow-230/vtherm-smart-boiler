# Plan 0.2, step I9 — The water data for zone algorithms

Goal: build Smart Boiler's side of the water interface, as specified in
`documentation/en/water-interface.md` (the user's decisions of 2026-10-12). Per VT thermostat
that is one of the plugin's zones, the plugin exposes the water reaching the zone's circuit and
whether heat reaches the zone; it reads one key a zone algorithm writes; it keeps pausing
SmartPI's learning on its own conditions. Data flows one way, from the plugin to the zone
algorithm. Step I9 of `docs/plan-0.2.md`, before 0.3; the user's go-ahead of 2026-10-12.
Nothing here writes anything new to the boiler.

Status on 2026-10-12: the plan made; I9.0 to I9.2 done.

## How to read this plan

- ✅ marks a finished step. Every step is one pull request into `dev`, with its "J4 impact".
  After each step the main session reports to the user in Polish.
- A change in `core/` starts with a test.
- The specification is the authority: a difference found while building is raised with the
  user, not decided here.

## Facts (checked in the code, 2026-10-12)

- `core/supply.py` `circuit_supply`: a measured circuit flow wins; a mixed circuit
  (`THROUGH_BOILER`, `SEPARATE`) without it is `circuit_not_measured`; otherwise the boiler's
  flow — `flow_unknown` without a value, `flow_stale` past its age limit; a passive fixed circuit
  gives `min(boiler flow, declared)`. Its only caller is `coordinator._compute`, which falls back
  to the boiler's flow when a circuit's own sensor is not fresh — also for a mixed circuit,
  which then reads `circuit_not_measured`, a lasting reason for a momentary loss.
- `core/heat.py` `heat_available`: `HeatReason` has no `not_mapped`; a boiler flow that is not
  mapped reads `flow_unknown`. Its result feeds the VT attribute and `heat_through_any` only.
- `coordinator._compute` builds a `ZoneView` per zone (its circuits, its state, its `Heat`);
  `feature_manager.zone_values` reads it for the managers through the stable access point
  `hass.data["vtherm_smart_boiler_feature_manager"]["coordinators"]`.
- The manager publishes `{"heat_available": …}` as the `smart_boiler` attribute, replaced only
  when it changes (P-63).
- `vtherm_link.zone_algorithm` reads the VT climate's `specific_states`
  (`smartpi_learning_enabled`, Auto-TPI's keys); `control.py` builds `ZoneLearning` from it.
- `core/learning.py`: hot water and the boiler-fault "off" pause only zones with an open valve
  (`NO_HEAT`); a water swing pauses every SmartPI zone.
- VT 10.4.0 has no `get_feature_manager` (from 10.5.0.beta1); it keeps external managers in the
  private `_external_managers`.

## Steps

| Step | Work | J4 impact |
|---|---|---|
| I9.0 ✅ | this plan; `docs/plan-0.2.md` and `CLAUDE.md` point to it | none |
| I9.1 ✅ | **Core.** `SupplyReason.NOT_MAPPED`: no boiler flow mapped and no circuit sensor. A circuit's own sensor that is mapped but unknown or stale gives `flow_unknown` / `flow_stale` (momentary) — for a mixed circuit too, which no longer reads `circuit_not_measured` then; a circuit fed straight from the boiler still falls back to the boiler's flow. `Supply.measured_at`: the time of the reading used. `HeatReason.NOT_MAPPED`, from `heat_available` for a supply `not_mapped`. A new `core/water.py`: `ZoneWater` (the five fields of the specification's section 4, the time as a timestamp) and `zone_water(supplies, heat)` — one circuit: its supply; several: their common supply where all are known and equal, else `None` with `several_circuits`. Tests first, among them every row of the specification's 5.1 the core can see | none — the VT attribute carries only `heat_available`, whose value does not change |
| I9.2 ✅ | **Exposing.** `coordinator._compute` gives each `ZoneView` its `ZoneWater` (the readings' times, `Signal.FLOW` mapped or not). `zone_values` returns the five fields (the time as a UTC `datetime`); the manager gets them as read-only properties. The `smart_boiler` attribute: `heat_available` on every change, `supply_temperature` rounded to 1 °C on a change of at least 1 K from the value last published, or to or from `None`. `hass.data["vtherm_smart_boiler_api"]`: an object with `zone_water(entity_id)` → a read-only mapping or `None` (not a zone, no running installation, any error), set with the first running installation and removed with the last. Integration tests: the properties, the API (no `get_feature_manager` needed), the attribute's publishing, monitoring only, a zone in no circuit, Smart Boiler stopped | the scenarios that read the `smart_boiler` attribute: it gains `supply_temperature` |
| I9.3 | **The consumer's key and the pauses.** `ZoneAlgorithm.uses_water_data`: the VT climate's `specific_states` holds `water_factor` (the key SmartPI writes, Annex A). `ZoneLearning` carries it; a zone that uses the water data is not paused for a water swing; hot water and the boiler fault pause as today. Tests first (core), then the read through `vtherm_link` | none with SmartPI 0.4.0, which writes no such key |
| I9.4 | **Contract and documents.** A contract test pins every name, type and allowed value of the specification (the fields, the reasons, the API key and function, the attribute's keys, the consumer's key) and checks that the specification's tables list the same reason values. The specification marked built; `SCOPE.md` §5; the technical documentation EN and PL, section 8; `CHANGELOG.md`; this plan and `docs/plan-0.2.md` marked done | none |

## Documents

- `documentation/en/water-interface.md` — the specification; its status changes in I9.4 only.
- `SCOPE.md` §5, `documentation/en/technical.md` and `documentation/pl/technical.md` §8,
  `CHANGELOG.md`, `README.md` and `README.pl.md` (documentation tables) — in I9.4.
