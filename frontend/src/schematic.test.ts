import { describe, expect, it } from "vitest";
import type { LiveInputs } from "./live";
import { localize } from "./localize";
import {
  circuitKind,
  drawSchematic,
  emitterOf,
  hotWaterOf,
  modeOf,
  roomsView,
  schematicView,
} from "./schematic";
import type { CircuitInfo, HassEntity, Installation } from "./types";

function entity(entity_id: string, state: string, attributes: Record<string, unknown> = {}): HassEntity {
  return { entity_id, state, attributes, last_changed: "", last_updated: "" };
}

function circuit(id: string, control: CircuitInfo["control"], zones: [string, string][], extra = {}): CircuitInfo {
  return {
    id, name: id, control, fixed_temperature: null, max_flow: null, needed: null,
    zones: zones.map(([entity_id, emitter]) => ({ entity_id, emitter: emitter as "radiator" | "underfloor" })),
    ...extra,
  };
}

const INSTALLATION: Installation = {
  entry_id: "e", title: "Boiler",
  boiler: { type: "single_tank", dhw: "storage", condensing: true },
  circuits: [
    circuit("radiators", "unmixed_shared", [["climate.a", "radiator"], ["climate.b", "radiator"]]),
    circuit("floor", "passive_fixed", [["climate.c", "underfloor"]], { fixed_temperature: 35 }),
  ],
  signals: {
    flame: "binary_sensor.flame", flow: "sensor.flow", return: "sensor.return",
    dhw_active: "binary_sensor.dhw", pressure: "sensor.pressure", outdoor: "sensor.outdoor",
    modulation: "sensor.modulation",
  },
  weather: null,
  entities: { demand_count: "sensor.calling", boiler_called: "binary_sensor.called" },
  curve: null,
  short_burn_min: 10,
};

function inputs(states: HassEntity[], installation = INSTALLATION, language = "en"): LiveInputs {
  return {
    installation, language,
    states: Object.fromEntries(states.map((s) => [s.entity_id, s])),
    t: (key, values) => localize(language, key, values),
    stateText: (e) => e.state,
  };
}

const calling = (...zones: string[]) => entity("sensor.calling", String(zones.length), { calling_zones: zones });

describe("what the settings say", () => {
  it("draws a tank, the boiler's own hot water, or none, from the boiler's type", () => {
    expect(hotWaterOf({ type: "single_tank", dhw: "storage", condensing: true })).toBe("tank");
    expect(hotWaterOf({ type: "combi", dhw: "combi", condensing: true })).toBe("instant");
    expect(hotWaterOf({ type: "combi_tank", dhw: "storage", condensing: true })).toBe("instant");
    expect(hotWaterOf({ type: "single", dhw: "none", condensing: true })).toBe("none");
  });

  it("falls back to the hot-water kind for an entry without a boiler type", () => {
    expect(hotWaterOf({ type: null, dhw: "storage", condensing: true })).toBe("tank");
    expect(hotWaterOf({ type: null, dhw: "combi", condensing: true })).toBe("instant");
    expect(hotWaterOf({ type: null, dhw: "none", condensing: true })).toBe("none");
  });

  it("names how each circuit is fed", () => {
    expect(circuitKind(circuit("x", "unmixed_shared", []))).toBe("direct");
    expect(circuitKind(circuit("x", "passive_fixed", []))).toBe("fixed_valve");
    expect(circuitKind(circuit("x", "separate", []))).toBe("other");
    expect(circuitKind(circuit("x", "through_boiler", []))).toBe("boiler_mixed");
  });

  it("draws underfloor heating where any of a circuit's zones has it", () => {
    expect(emitterOf(circuit("x", "unmixed_shared", [["a", "radiator"], ["b", "underfloor"]]))).toBe("floor");
    expect(emitterOf(circuit("x", "unmixed_shared", [["a", "radiator"]]))).toBe("radiator");
  });
});

describe("what the water does now", () => {
  it("is hot water while the boiler reports it", () => {
    expect(modeOf(inputs([entity("binary_sensor.dhw", "on"), calling("climate.a")]))).toBe("dhw");
  });
  it("is heating while a zone calls or the plugin calls the boiler", () => {
    expect(modeOf(inputs([calling("climate.a")]))).toBe("heat");
    expect(modeOf(inputs([entity("binary_sensor.called", "on"), calling()]))).toBe("heat");
  });
  it("is still otherwise", () => {
    expect(modeOf(inputs([calling(), entity("binary_sensor.called", "off")]))).toBe("idle");
    expect(modeOf(inputs([]))).toBe("idle");
  });
});

describe("the drawing", () => {
  it("lets the water flow only to circuits whose rooms call", () => {
    const { paths, circuits } = drawSchematic(INSTALLATION, "heat", new Set(["radiators"]));
    expect(circuits.map((c) => [c.id, c.active])).toEqual([["radiators", true], ["floor", false]]);
    expect(paths.radOn).not.toBe("");
    expect(paths.floorOff).not.toBe("");
    expect(paths.floorOn).toBe("");
    expect(paths.pumpOn).not.toBe("");
    expect(paths.pumpOff).not.toBe("");
    expect(paths.flow).not.toBe("");
  });

  it("charges the tank and stills the circuits while hot water has priority", () => {
    const { paths, circuits } = drawSchematic(INSTALLATION, "dhw", new Set(["radiators"]));
    expect(circuits.every((c) => !c.active)).toBe(true);
    expect(paths.coilOn).not.toBe("");
    expect(paths.coilOff).toBe("");
  });

  it("moves no water while idle", () => {
    const { paths } = drawSchematic(INSTALLATION, "idle", new Set());
    expect(paths.flow).toBe("");
    expect(paths.red).toBe("M326 199V178"); // only the tank's stored hot water
  });

  it("gives a combi its hot water at the boiler and draws no tank", () => {
    const combi = { ...INSTALLATION, boiler: { type: "combi", dhw: "combi", condensing: true } };
    const { paths, hotWater } = drawSchematic(combi, "dhw", new Set());
    expect(hotWater).toBe("instant");
    expect(paths.coilOn + paths.coilOff).toBe("");
    expect(paths.flow).toContain("M60 300H30");
  });

  it("spreads the circuits across their room", () => {
    const three = { ...INSTALLATION, circuits: [INSTALLATION.circuits[0], INSTALLATION.circuits[1], circuit("x", "separate", [])] };
    const xs = drawSchematic(three, "idle", new Set()).circuits.map((c) => c.cx);
    expect(xs).toEqual([530, 710, 890]);
  });

  it("draws a boiler with no circuits", () => {
    const none = { ...INSTALLATION, circuits: [] };
    const { paths, circuits } = drawSchematic(none, "idle", new Set());
    expect(circuits).toEqual([]);
    expect(paths.body).not.toBe("");
  });
});

describe("the labels", () => {
  const heating = [
    calling("climate.a"),
    entity("binary_sensor.flame", "on"),
    entity("sensor.modulation", "34"),
    entity("sensor.flow", "41.2"),
    entity("sensor.return", "34.0"),
    entity("sensor.pressure", "1.6"),
    entity("sensor.outdoor", "3.8"),
  ];

  it("show the boiler's state and every measured value picked", () => {
    const view = schematicView(inputs(heating, INSTALLATION, "pl"));
    const texts = view.labels.map((l) => l.text);
    expect(texts).toContain("pali · ogrzewanie");
    expect(texts).toContain("modulacja 34 %");
    expect(texts).toContain("41,2 °C");
    expect(texts).toContain("1,6 bar");
    expect(texts).toContain("3,8 °C");
    expect(texts).toContain("zawór termostatyczny 35 °C");
    expect(texts).toContain("prosto z kotła");
    expect(view.flame).toBe(true);
    expect(view.mode).toBe("heat");
  });

  it("say a pause, hot water or idle", () => {
    const pause = schematicView(inputs([calling("climate.a"), entity("binary_sensor.flame", "off")]));
    expect(pause.labels.map((l) => l.text)).toContain("pause between burns");
    const hot = schematicView(inputs([entity("binary_sensor.dhw", "on"), entity("binary_sensor.flame", "on")]));
    expect(hot.labels.map((l) => l.text)).toContain("burning · hot water");
    const idle = schematicView(inputs([]));
    expect(idle.labels.map((l) => l.text)).toContain("idle");
  });

  it("leave out what is not picked", () => {
    const bare = { ...INSTALLATION, signals: {} };
    const texts = schematicView(inputs([], bare)).labels.map((l) => l.text);
    expect(texts.some((t) => t.includes("°C") && !t.includes("valve"))).toBe(false);
    expect(texts.some((t) => t.includes("bar"))).toBe(false);
  });

  it("show a pressure that cannot be read as a dash, and other automation's need", () => {
    const other = {
      ...INSTALLATION,
      circuits: [circuit("fan", "separate", [], { needed: 55 }), circuit("mixer", "separate", [])],
    };
    const texts = schematicView(inputs([entity("sensor.pressure", "unavailable")], other)).labels.map((l) => l.text);
    expect(texts).toContain("—");
    expect(texts).toContain("other automation · needs 55 °C");
    expect(texts).toContain("other automation");
  });

  it("name the hot water at a combi", () => {
    const combi = { ...INSTALLATION, boiler: { type: "combi", dhw: "combi", condensing: true } };
    expect(schematicView(inputs([], combi)).labels.map((l) => l.text)).toContain("hot water");
    const none = { ...INSTALLATION, boiler: { type: "single", dhw: "none", condensing: true } };
    expect(schematicView(inputs([], none)).labels.map((l) => l.text)).not.toContain("hot water");
  });

  // F21: in a narrow dashboard column the labels overlapped each other and the boiler.
  it("keep the outdoor temperature and its name in one block", () => {
    const view = schematicView(inputs(heating, INSTALLATION, "pl"));
    expect(view.labels.find((l) => l.text === "3,8 °C")?.caption).toBe("Na zewnątrz");
    expect(view.labels.map((l) => l.text)).not.toContain("Na zewnątrz");
  });

  it("end the words beside a combi before the boiler, and leave them out of a narrow card", () => {
    const combi = { ...INSTALLATION, boiler: { type: "combi", dhw: "combi", condensing: true } };
    const words = schematicView(inputs([], combi)).labels.filter((l) => ["hot water", "cold"].includes(l.text));
    expect(words).toHaveLength(2);
    for (const word of words) {
      expect(word.end).toBe(true);
      expect(word.x).toBeLessThan(60); // the boiler's body starts at 60
      expect(word.minor).toBe(true);
    }
  });

  it("wrap only the boiler's state", () => {
    const view = schematicView(inputs(heating, INSTALLATION, "pl"));
    const wrapping = view.labels.filter((l) => l.wrap).map((l) => l.text);
    expect(wrapping).toEqual(["pali · ogrzewanie"]);
  });
});

describe("the rooms", () => {
  it("show each circuit's rooms as VT shows them", () => {
    const states = [
      calling("climate.a"),
      entity("climate.a", "heat", { friendly_name: "Living room", current_temperature: 20.6, temperature: 21, on_percent: 0.64 }),
      entity("climate.b", "heat", { current_temperature: 18.7, temperature: 19, valve_open_percent: 38 }),
      entity("climate.c", "heat", { friendly_name: "Kitchen", current_temperature: 21.2, temperature: 21 }),
    ];
    const view = inputs(states, INSTALLATION, "pl");
    const rooms = roomsView(view, schematicView(view).circuits);
    expect(rooms).toEqual([
      [
        { entityId: "climate.a", name: "Living room", temperature: "20,6 °C", target: "21,0 °C", demand: 64, calling: true },
        { entityId: "climate.b", name: "climate.b", temperature: "18,7 °C", target: "19,0 °C", demand: 38, calling: false },
      ],
      [{ entityId: "climate.c", name: "Kitchen", temperature: "21,2 °C", target: "21,0 °C", demand: null, calling: false }],
    ]);
  });

  it("show a room Home Assistant does not know with dashes", () => {
    const view = inputs([]);
    const rooms = roomsView(view, schematicView(view).circuits);
    expect(rooms[0][0]).toMatchObject({ temperature: "—", target: "—", demand: null, calling: false });
  });
});
