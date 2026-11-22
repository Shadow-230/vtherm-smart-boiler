// The curve card's arithmetic (docs/en/development/plans/plan-0.2-i10.md, I10.3c): where things
// fall on the chart, "where we are" from the control state, and the last days' decisions from the
// recorder. The curve's points themselves come from the plugin (vtherm_smart_boiler/curve): the
// page never computes a curve of its own.
import type { CurveSettings, HassEntity } from "./types";

export type Point = [outdoor: number, water: number];

export interface Chart {
  outdoorFrom: number;
  outdoorTo: number;
  waterFrom: number;
  waterTo: number;
}

/** The chart's ranges: down past the design point's frost, up to 20 °C outdoors; the water from
 * 15 °C to past the highest. */
export function chartFor(settings: CurveSettings): Chart {
  return {
    outdoorFrom: Math.min(-20, Math.floor(settings.design_outdoor / 5) * 5 - 5),
    outdoorTo: 20,
    waterFrom: 15,
    waterTo: Math.max(75, Math.ceil(settings.hard_max / 5) * 5 + 5),
  };
}

/** A point's place as shares of the chart (0–1, left to right and top to bottom): warmer to the
 * left and colder to the right, as boiler manuals draw a heating curve — it rises to the right. */
export function place(chart: Chart, outdoor: number, water: number): { x: number; y: number } {
  return {
    x: (chart.outdoorTo - outdoor) / (chart.outdoorTo - chart.outdoorFrom),
    y: (chart.waterTo - water) / (chart.waterTo - chart.waterFrom),
  };
}

/** An SVG path through `points` in a `width` × `height` box. */
export function pathOf(chart: Chart, points: Point[], width: number, height: number): string {
  return points
    .map(([o, w], i) => {
      const { x, y } = place(chart, o, w);
      return `${i ? "L" : "M"}${(x * width).toFixed(1)} ${(y * height).toFixed(1)}`;
    })
    .join("");
}

/** The ticks every `step` within `from`–`to`. */
export function ticks(from: number, to: number, step: number): number[] {
  const out: number[] = [];
  for (let v = Math.ceil(from / step) * step; v <= to + 1e-9; v += step) out.push(Math.round(v * 10) / 10);
  return out;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export interface Where {
  outdoor: number;
  water: number;
  room: number | null;
}

/** "Where we are": the outdoor temperature the water was decided with and the water decided,
 * from the control state; nothing before a decision. */
export function whereNow(controlState: HassEntity | undefined): Where | null {
  const a = controlState?.attributes ?? {};
  const outdoor = num(a.curve_outdoor);
  const water = num(a.target);
  if (outdoor == null || water == null) return null;
  return { outdoor, water, room: num(a.curve_room) };
}

/** One recorded state of the control state sensor, as Home Assistant's history answers it. */
export interface Recorded {
  s: string;
  a?: Record<string, unknown>;
  lu: number;
}

/** The decisions of the last days while heating, at most one an hour — the dots beside the
 * curve, where the water really went. */
export function pastDecisions(states: Recorded[]): Point[] {
  const out: Point[] = [];
  let lastHour = Number.NEGATIVE_INFINITY;
  let attributes: Record<string, unknown> = {};
  for (const state of states) {
    if (state.a) attributes = state.a;
    if (state.s !== "heating") continue;
    const outdoor = num(attributes.curve_outdoor);
    const water = num(attributes.target);
    const hour = Math.floor(state.lu / 3600);
    if (outdoor == null || water == null || hour === lastHour) continue;
    lastHour = hour;
    out.push([outdoor, water]);
  }
  return out;
}

export interface Draft {
  design_outdoor: number;
  design_flow: number;
  offset: number;
}

/** A dragged design point, kept where a curve can stand: the frost between −30 and −5 °C, the
 * water between 25 and 80 °C, on half degrees. The plugin's checks still judge it. */
export function dragTo(chart: Chart, x: number, y: number): Pick<Draft, "design_outdoor" | "design_flow"> {
  const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
  const outdoor = chart.outdoorTo - clamp(x, 0, 1) * (chart.outdoorTo - chart.outdoorFrom);
  const water = chart.waterTo - clamp(y, 0, 1) * (chart.waterTo - chart.waterFrom);
  return {
    design_outdoor: clamp(Math.round(outdoor * 2) / 2, -30, -5),
    design_flow: clamp(Math.round(water * 2) / 2, 25, 80),
  };
}

/** The draft's water at one outdoor temperature, read off the points the plugin gave. */
export function waterAt(points: Point[], outdoor: number): number | null {
  for (let i = 1; i < points.length; i++) {
    const [o0, w0] = points[i - 1];
    const [o1, w1] = points[i];
    if (outdoor >= o0 && outdoor <= o1) {
      return o1 === o0 ? w0 : w0 + ((w1 - w0) * (outdoor - o0)) / (o1 - o0);
    }
  }
  return null;
}
