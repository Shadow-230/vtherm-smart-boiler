// The hydraulic schematic (docs/en/development/plans/plan-0.2-i10.md, I10.3b), drawn from the
// entry's settings — the boiler's hot water, the circuits and their emitters — so it fits any
// installation, and coloured by what Home Assistant's states say now. Pure: the card draws the
// paths and labels this returns. Coordinates are in a 1000 × 500 box (x 0–1000, y 70–570).
import { formatNumber, formatTemperature, numberOf } from "./format";
import { callingZones, type LiveInputs } from "./live";
import type { CircuitInfo, Installation } from "./types";

export type Mode = "heat" | "dhw" | "idle";
export type HotWater = "tank" | "instant" | "none";
export type CircuitKind = "direct" | "fixed_valve" | "other" | "boiler_mixed";
export type Emitter = "radiator" | "floor";

export const VIEW_BOX = { x: 0, y: 70, width: 1000, height: 500 };
const CIRCUITS_FROM = 440; // the circuits share x 440–980
const CIRCUITS_WIDTH = 540;
const SUPPLY_Y = 150;
const RETURN_Y = 470;

export interface Paths {
  body: string;
  gray: string;
  blue: string;
  red: string;
  mix: string;
  coilOn: string;
  coilOff: string;
  floorOn: string;
  floorOff: string;
  radOn: string;
  radOff: string;
  flow: string;
  arrRed: string;
  arrBlue: string;
  valveOn: string;
  valveOff: string;
  pumps: string;
  pumpOn: string;
  pumpOff: string;
}

export interface CircuitDraw {
  id: string;
  name: string;
  kind: CircuitKind;
  emitter: Emitter;
  active: boolean;
  cx: number;
  setting: number | null;
  need: number | null;
  zones: string[];
}

export interface Label {
  /** "text" beside the drawing, "inside" on the boiler's light body, "value" a measured value. */
  kind: "text" | "inside" | "value";
  x: number;
  y: number;
  text: string;
  /** Left out of a narrow card, where it would overlap: the rooms below name the circuits. */
  minor?: boolean;
  /** Ends at `x` instead of centring on it: a label left of the boiler never reaches its body. */
  end?: boolean;
  /** A value's name, shown above it as one block, so the two cannot overlap at any width. */
  caption?: string;
  /** Wraps to the boiler's width: its state, which can be long. */
  wrap?: boolean;
}

export interface Schematic {
  paths: Paths;
  circuits: CircuitDraw[];
  hotWater: HotWater;
  mode: Mode;
  labels: Label[];
  /** The flame is lit: heating or hot water. */
  flame: boolean;
}

export function hotWaterOf(boiler: Installation["boiler"]): HotWater {
  switch (boiler.type) {
    case "single_tank":
      return "tank";
    case "combi":
    case "combi_tank": // its tank is inside the boiler: drawn as the boiler's own hot water
      return "instant";
    case "single":
      return "none";
  }
  return boiler.dhw === "storage" ? "tank" : boiler.dhw === "combi" ? "instant" : "none";
}

export function circuitKind(circuit: CircuitInfo): CircuitKind {
  switch (circuit.control) {
    case "passive_fixed":
      return "fixed_valve";
    case "separate":
      return "other";
    case "through_boiler":
      return "boiler_mixed";
    default:
      return "direct";
  }
}

export function emitterOf(circuit: CircuitInfo): Emitter {
  return circuit.zones.some((zone) => zone.emitter === "underfloor") ? "floor" : "radiator";
}

/** What the water does now: hot water while the boiler reports it; heating while a zone calls
 * or the plugin calls the boiler; otherwise nothing. */
export function modeOf(inputs: LiveInputs): Mode {
  const signal = (name: string) => inputs.states[inputs.installation.signals[name] ?? ""];
  if (signal("dhw_active")?.state === "on") return "dhw";
  const called = inputs.states[inputs.installation.entities.boiler_called ?? ""]?.state === "on";
  return called || callingZones(inputs).length > 0 ? "heat" : "idle";
}

function circle(x: number, y: number, r: number): string {
  return `M${x - r} ${y}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`;
}

type Port = "left" | "right" | "top" | "bottom";

function valvePort(x: number, y: number, port: Port): string {
  const s = 11;
  const h = s * 0.75;
  switch (port) {
    case "left":
      return `M${x - s} ${y - h}L${x} ${y}L${x - s} ${y + h}Z`;
    case "right":
      return `M${x + s} ${y - h}L${x} ${y}L${x + s} ${y + h}Z`;
    case "top":
      return `M${x - h} ${y - s}L${x} ${y}L${x + h} ${y - s}Z`;
    case "bottom":
      return `M${x - h} ${y + s}L${x} ${y}L${x + h} ${y + s}Z`;
  }
}

function emptyPaths(): Paths {
  return {
    body: "", gray: "", blue: "", red: "", mix: "", coilOn: "", coilOff: "", floorOn: "",
    floorOff: "", radOn: "", radOff: "", flow: "", arrRed: "", arrBlue: "", valveOn: "",
    valveOff: "", pumps: "", pumpOn: "", pumpOff: "",
  };
}

/** The pipes, the boiler, the tank, the valves, the pumps and the emitters for `mode`, with the
 * circuits in `active` drawn as taking heat. */
export function drawSchematic(installation: Installation, mode: Mode, active: Set<string>): {
  paths: Paths;
  circuits: CircuitDraw[];
  hotWater: HotWater;
} {
  const p = emptyPaths();
  const add = (d: string, kind: "gray" | "blue" | "red" | "mix", flowing: boolean) => {
    p[kind] += d;
    if (flowing) p.flow += d;
  };
  const heat = mode === "heat";
  const hotWater = hotWaterOf(installation.boiler);
  const tank = hotWater === "tank";
  const toTank = mode === "dhw" && tank;
  const count = Math.max(1, installation.circuits.length);
  const width = CIRCUITS_WIDTH / count;
  const circuits: CircuitDraw[] = installation.circuits.map((circuit, k) => ({
    id: circuit.id,
    name: circuit.name,
    kind: circuitKind(circuit),
    emitter: emitterOf(circuit),
    active: heat && active.has(circuit.id),
    cx: CIRCUITS_FROM + width * (k + 0.5),
    setting: circuit.fixed_temperature,
    need: circuit.needed,
    zones: [...new Set(circuit.zones.map((z) => z.entity_id))],
  }));
  const lastSupply = circuits.length ? circuits[circuits.length - 1].cx - 25 : 300;
  const lastReturn = circuits.length ? circuits[circuits.length - 1].cx + 35 : 300;

  p.body += "M60 124a14 14 0 0 1 14-14h122a14 14 0 0 1 14 14v222a14 14 0 0 1-14 14h-122a14 14 0 0 1-14-14Z";
  const boilerFlows = heat || toTank;
  add(`M210 ${SUPPLY_Y}H300`, boilerFlows ? "red" : "gray", boilerFlows);
  add(`M300 ${SUPPLY_Y}H${lastSupply}`, heat ? "red" : "gray", heat);
  add(`M${lastReturn} ${RETURN_Y}H300`, heat ? "blue" : "gray", heat);
  add(`M300 ${RETURN_Y}H135V360`, boilerFlows ? "blue" : "gray", boilerFlows);

  if (tank) {
    p.body += "M255 205a45 10 0 0 1 90 0V410a45 10 0 0 1-90 0Z";
    add(`M300 ${SUPPLY_Y + 11}V228`, toTank ? "red" : "gray", toTank);
    const coil = "M300 228H272V243H328V258H272V273H328V288H272V303H328V318H272V333H328V348H300V412";
    if (toTank) {
      p.coilOn += coil;
      p.flow += coil;
    } else {
      p.coilOff += coil;
    }
    add(`M300 412V${RETURN_Y}`, toTank ? "blue" : "gray", toTank);
    add("M326 199V178", "red", false);
    p.arrRed += "M318 180L326 166L334 180Z";
    add("M398 392H352", "blue", false);
    p.arrBlue += "M354 384L341 392L354 400Z";
    p[boilerFlows ? "valveOn" : "valveOff"] += valvePort(300, SUPPLY_Y, "left");
    p[heat ? "valveOn" : "valveOff"] += valvePort(300, SUPPLY_Y, "right");
    p[toTank ? "valveOn" : "valveOff"] += valvePort(300, SUPPLY_Y, "bottom");
  } else if (hotWater === "instant") {
    add("M60 300H30", "red", mode === "dhw");
    p.arrRed += "M32 292L18 300L32 308Z";
    add("M16 330H50", "blue", mode === "dhw");
    p.arrBlue += "M48 322L62 330L48 338Z";
  }

  for (const c of circuits) {
    const sx = c.cx - 25;
    const rx = c.cx + 35;
    const on = c.active;
    const mixing = c.kind !== "direct";
    if (mixing) {
      add(`M${sx} ${SUPPLY_Y}V194`, on ? "red" : "gray", on);
      add(`M${sx} 216V290`, on ? "mix" : "gray", on);
      for (const port of ["top", "bottom", "left"] as const) {
        p[on ? "valveOn" : "valveOff"] += valvePort(sx, 205, port);
      }
      add(`M${rx} 432H${c.cx - 68}V205H${sx - 11}`, on ? "blue" : "gray", on);
    } else {
      add(`M${sx} ${SUPPLY_Y}V290`, on ? "red" : "gray", on);
    }
    p.pumps += circle(sx, 252, 13);
    p[on ? "pumpOn" : "pumpOff"] += `M${sx - 7} 246L${sx + 7} 246L${sx} 260Z`;
    if (c.emitter === "radiator") {
      add(`M${sx} 290H${c.cx + 38}`, on ? (mixing ? "mix" : "red") : "gray", on);
      for (let bar = 0; bar < 6; bar++) {
        const x = (c.cx - 41 + bar * 14.6).toFixed(1);
        p[on ? "radOn" : "radOff"] += `M${x} 296h10v88h-10Z`;
      }
      add(`M${c.cx - 38} 390H${rx}`, on ? "blue" : "gray", on);
    } else {
      const loop = `M${sx} 290V300H${c.cx + 42}V318H${c.cx - 42}V336H${c.cx + 42}V354H${c.cx - 42}V372H${rx}V390`;
      if (on) {
        p.floorOn += loop;
        p.flow += loop;
      } else {
        p.floorOff += loop;
      }
    }
    add(`M${rx} 390V${RETURN_Y}`, on ? "blue" : "gray", on);
  }
  return { paths: p, circuits, hotWater };
}

/** The whole schematic now: the drawing, and its labels — the boiler's state, the measured
 * temperatures where their entities are picked, each circuit's name and how it is fed. */
export function schematicView(inputs: LiveInputs): Schematic {
  const { installation, states, language, t } = inputs;
  const mode = modeOf(inputs);
  const calling = new Set(callingZones(inputs));
  const active = new Set(
    installation.circuits
      .filter((c) => c.zones.some((z) => calling.has(z.entity_id)))
      .map((c) => c.id),
  );
  const { paths, circuits, hotWater } = drawSchematic(installation, mode, active);
  const signal = (name: string) => states[installation.signals[name] ?? ""];
  const flame = signal("flame")?.state === "on";
  const labels: Label[] = [{ kind: "inside", x: 135, y: 132, text: t("schematic.boiler"), minor: true }];
  const status = flame
    ? mode === "dhw"
      ? t("schematic.burning_hot_water")
      : t("schematic.burning_heating")
    : mode === "heat"
      ? t("schematic.pause")
      : t("schematic.idle");
  labels.push({ kind: "inside", x: 135, y: 262, text: status, wrap: true });
  const modulation = numberOf(signal("modulation")?.state);
  if (flame && modulation != null) {
    labels.push({
      kind: "inside", x: 135, y: 298, minor: true,
      text: t("tiles.flame_modulation", { value: formatNumber(modulation, language, 0) }),
    });
  }
  const flow = signal("flow");
  if (flow) labels.push({ kind: "value", x: 252, y: 126, text: formatTemperature(numberOf(flow.state), language) });
  const ret = signal("return");
  if (ret) labels.push({ kind: "value", x: 220, y: 492, text: formatTemperature(numberOf(ret.state), language) });
  const pressure = signal("pressure");
  if (pressure) {
    const bar = numberOf(pressure.state);
    labels.push({ kind: "value", x: 88, y: 390, text: bar == null ? "—" : `${formatNumber(bar, language, 1)} bar` });
  }
  const outdoor = numberOf(signal("outdoor")?.state);
  if (outdoor != null) {
    labels.push({ kind: "value", x: 925, y: 108, text: formatTemperature(outdoor, language), caption: t("tiles.outdoor") });
  }
  if (hotWater === "tank") {
    labels.push({ kind: "text", x: 376, y: 444, text: t("schematic.tank") });
    labels.push({ kind: "text", x: 380, y: 170, text: t("schematic.hot_water") });
    labels.push({ kind: "text", x: 414, y: 372, text: t("schematic.cold_water") });
  } else if (hotWater === "instant") {
    // Left of the boiler, where a narrow card has no room for them: the arrows stay.
    labels.push({ kind: "text", x: 56, y: 282, text: t("schematic.hot_water"), end: true, minor: true });
    labels.push({ kind: "text", x: 56, y: 348, text: t("schematic.cold_water"), end: true, minor: true });
  }
  for (const c of circuits) {
    // Below the return pipe, where nothing is drawn: under the circuit, clear of its pipes.
    labels.push({ kind: "text", x: c.cx, y: 500, text: c.name, minor: true });
    const fed =
      c.kind === "fixed_valve" && c.setting != null
        ? t("schematic.fixed_valve", { value: formatNumber(c.setting, language, 0) })
        : c.kind === "other" && c.need != null
          ? t("schematic.other_need", { value: formatNumber(c.need, language, 0) })
          : t(`schematic.${c.kind}`);
    labels.push({ kind: "text", x: c.cx, y: 520, text: fed, minor: true });
  }
  return { paths, circuits, hotWater, mode, labels, flame };
}

export interface RoomView {
  entityId: string;
  name: string;
  temperature: string;
  target: string;
  /** How hard the room's own controller heats, 0–100; `null` where VT does not say. */
  demand: number | null;
  calling: boolean;
}

/** The rooms of each circuit, as VT shows them, and whether the plugin counts them calling. */
export function roomsView(inputs: LiveInputs, circuits: CircuitDraw[]): RoomView[][] {
  const { states, language } = inputs;
  const calling = new Set(callingZones(inputs));
  return circuits.map((circuit) =>
    circuit.zones.map((entityId) => {
      const zone = states[entityId];
      const attributes = zone?.attributes ?? {};
      const onPercent = numberOf(String(attributes.on_percent ?? ""));
      const valve = numberOf(String(attributes.valve_open_percent ?? ""));
      const demand = onPercent != null ? onPercent * 100 : valve;
      const name = attributes.friendly_name;
      return {
        entityId,
        name: typeof name === "string" && name ? name : entityId,
        temperature: formatTemperature(numberOf(String(attributes.current_temperature ?? "")), language),
        target: formatTemperature(numberOf(String(attributes.temperature ?? "")), language),
        demand: demand == null ? null : Math.max(0, Math.min(100, Math.round(demand))),
        calling: calling.has(entityId),
      };
    }),
  );
}
