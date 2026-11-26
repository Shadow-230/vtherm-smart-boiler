import { describe, expect, it } from "vitest";
import type { LiveInputs } from "./live";
import { localize } from "./localize";
import {
  circuitKind,
  drawSchematic,
  emitterOf,
  hotWaterOf,
  modeOf,
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

// The plugin's "Calling for heat": how many rooms call, and the circuits they are on.
const calling = (...circuits: string[]) =>
  entity("sensor.calling", String(circuits.length), { calling_zones: [], calling_circuits: circuits });
const called = (state: string) => entity("binary_sensor.called", state);

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
    expect(modeOf(inputs([entity("binary_sensor.dhw", "on"), called("on"), calling("radiators")]))).toBe("dhw");
  });
  it("is heating while the plugin calls the boiler, or the burner burns for heating", () => {
    expect(modeOf(inputs([called("on"), calling()]))).toBe("heat");
    // The plugin not holding the boiler: the flame alone says it heats.
    expect(modeOf(inputs([called("unknown"), entity("binary_sensor.flame", "on")]))).toBe("heat");
  });
  it("is still otherwise — rooms calling alone do not make the water flow", () => {
    expect(modeOf(inputs([calling("radiators"), called("off")]))).toBe("idle");
    expect(modeOf(inputs([calling("radiators")]))).toBe("idle");
    expect(modeOf(inputs([]))).toBe("idle");
  });
});

describe("the drawing", () => {
  it("lets the water flow only to the circuits taking it", () => {
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

describe("the circuits taking water", () => {
  it("are those the plugin names with the rooms calling, while the boiler heats", () => {
    const view = schematicView(inputs([called("on"), calling("floor")]));
    expect(view.circuits.map((c) => [c.id, c.active])).toEqual([["radiators", false], ["floor", true]]);
    const still = schematicView(inputs([called("off"), calling("floor")]));
    expect(still.circuits.every((c) => !c.active)).toBe(true);
  });

  it("are none where the plugin does not say, whatever VT's thermostats show", () => {
    const vt = [
      entity("climate.a", "heat", { hvac_action: "heating", on_percent: 0.9 }),
      entity("climate.c", "heat", { hvac_action: "heating", valve_open_percent: 80 }),
    ];
    const view = schematicView(inputs([called("on"), entity("sensor.calling", "2"), ...vt]));
    expect(view.circuits.every((c) => !c.active)).toBe(true);
    expect(view.mode).toBe("heat");
  });
});

describe("the labels", () => {
  const heating = [
    called("on"),
    calling("radiators"),
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
    const pause = schematicView(inputs([called("on"), entity("binary_sensor.flame", "off")]));
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
