import { describe, expect, it } from "vitest";
import { localize } from "./localize";
import { liveView, zoneIds, type LiveInputs } from "./live";
import type { HassEntity, Installation } from "./types";

function entity(entity_id: string, state: string, attributes: Record<string, unknown> = {}): HassEntity {
  return { entity_id, state, attributes, last_changed: "", last_updated: "" };
}

const INSTALLATION: Installation = {
  entry_id: "e1",
  title: "Boiler",
  boiler: { type: "single_tank", dhw: "storage", condensing: true },
  circuits: [
    {
      id: "c1", name: "Radiators", control: "unmixed_shared", fixed_temperature: null,
      max_flow: null, needed: null,
      zones: [
        { entity_id: "climate.a", emitter: "radiator" },
        { entity_id: "climate.b", emitter: "radiator" },
      ],
    },
    {
      id: "c2", name: "Floor", control: "passive_fixed", fixed_temperature: 35, max_flow: 45,
      needed: null,
      zones: [
        { entity_id: "climate.b", emitter: "underfloor" },
        { entity_id: "climate.c", emitter: "underfloor" },
      ],
    },
  ],
  signals: {
    flame: "binary_sensor.flame", flow: "sensor.flow", return: "sensor.return",
    outdoor: "sensor.outdoor", modulation: "sensor.modulation", dhw_active: "binary_sensor.dhw",
  },
  weather: "weather.home",
  entities: {
    control: "switch.control", control_state: "sensor.control_state",
    control_setpoint: "sensor.setpoint", demand_count: "sensor.calling",
  },
  curve: null,
};

function inputs(
  states: HassEntity[],
  installation: Installation = INSTALLATION,
  language = "en",
): LiveInputs {
  return {
    installation,
    states: Object.fromEntries(states.map((s) => [s.entity_id, s])),
    language,
    t: (key, values) => localize(language, key, values),
    stateText: (e) => `«${e.state}»`,
  };
}

const HEATING = [
  entity("sensor.control_state", "heating", { reasons_text: "rooms call for heat" }),
  entity("switch.control", "on"),
  entity("sensor.setpoint", "41.0", { requested: 41.0, read_back: 41.0 }),
  entity("sensor.flow", "40.6"),
  entity("sensor.return", "34.2"),
  entity("sensor.outdoor", "3.8"),
  entity("binary_sensor.flame", "on"),
  entity("sensor.modulation", "34"),
  entity("binary_sensor.dhw", "off"),
  entity("sensor.calling", "2", { calling_zones: ["climate.a", "climate.c", "climate.elsewhere"] }),
  entity("weather.home", "cloudy", { temperature: 4.4 }),
];

describe("liveView", () => {
  it("shows the control state in Home Assistant's own words, with its reasons", () => {
    const view = liveView(inputs(HEATING));
    expect(view.status).toEqual({
      title: "«heating»", detail: "rooms call for heat", flame: true, code: "heating",
    });
    expect(view.control).toEqual({ entityId: "switch.control", on: true, available: true });
  });

  it("gives every tile its value and what it means", () => {
    const tiles = Object.fromEntries(liveView(inputs(HEATING)).tiles.map((t) => [t.key, t]));
    expect(Object.keys(tiles)).toEqual(["water", "flow", "return", "outdoor", "flame", "rooms"]);
    expect(tiles.water).toMatchObject({ value: "41.0 °C", detail: "confirmed by the boiler" });
    expect(tiles.return.detail).toBe("below 55 °C — the boiler condenses");
    expect(tiles.outdoor).toMatchObject({ value: "3.8 °C", detail: "the boiler's sensor" });
    expect(tiles.flame).toMatchObject({ value: "On", detail: "modulation 34 %" });
    // A zone the installation does not have is not counted; a zone in two circuits counts once.
    expect(tiles.rooms.value).toBe("2 of 3");
  });

  it("writes the numbers in the user's language", () => {
    const tiles = liveView(inputs(HEATING, INSTALLATION, "pl")).tiles;
    expect(tiles.find((t) => t.key === "flow")?.value).toBe("40,6 °C");
    expect(tiles.find((t) => t.key === "rooms")?.value).toBe("2 z 3");
  });

  it("says when the boiler has not confirmed, and when nothing is asked", () => {
    const waiting = liveView(inputs([entity("sensor.setpoint", "unknown", { requested: 45, read_back: 41 })]));
    expect(waiting.tiles[0].detail).toBe("waiting for the boiler to confirm");
    const none = liveView(inputs([entity("sensor.setpoint", "unknown", { requested: null })]));
    expect(none.tiles[0]).toMatchObject({ value: "—", detail: "nothing asked now" });
  });

  it("names hot water and the weather's temperature where the sensor is missing", () => {
    const view = liveView(
      inputs([
        entity("binary_sensor.flame", "on"),
        entity("binary_sensor.dhw", "on"),
        entity("sensor.outdoor", "unavailable"),
        entity("weather.home", "rainy", { temperature: 4.4 }),
        entity("sensor.return", "58"),
      ]),
    );
    const tiles = Object.fromEntries(view.tiles.map((t) => [t.key, t]));
    expect(tiles.flame.detail).toBe("hot water");
    expect(tiles.outdoor).toMatchObject({ value: "4.4 °C", detail: "from the weather" });
    expect(tiles.return.detail).toBe("water coming back");
  });

  it("shows nothing it has no entity for", () => {
    const bare: Installation = { ...INSTALLATION, signals: {}, weather: null, entities: {}, circuits: [] };
    const view = liveView(inputs([], bare));
    expect(view.tiles).toEqual([]);
    expect(view.control).toBeNull();
    expect(view.status).toMatchObject({ code: "monitoring", flame: false });
    expect(view.status.detail).toContain("Control is not set up");
  });

  it("tells the burner's state where control is not set up", () => {
    const monitorOnly: Installation = { ...INSTALLATION, entities: {} };
    expect(liveView(inputs([entity("binary_sensor.flame", "on")], monitorOnly)).status.detail).toBe(
      "The burner is on.",
    );
    expect(liveView(inputs([entity("binary_sensor.flame", "off")], monitorOnly)).status.detail).toBe(
      "The burner is off.",
    );
  });

  it("marks an unavailable Control switch", () => {
    const view = liveView(inputs([entity("switch.control", "unavailable")]));
    expect(view.control).toMatchObject({ on: false, available: false });
  });
});

describe("zoneIds", () => {
  it("lists each zone once", () => {
    expect(zoneIds(INSTALLATION)).toEqual(["climate.a", "climate.b", "climate.c"]);
  });
});
