import { describe, expect, it } from "vitest";
import { chartFor, dragTo, pastDecisions, pathOf, place, ticks, waterAt, whereNow } from "./curve";
import type { CurveSettings, HassEntity } from "./types";

const SETTINGS: CurveSettings = {
  entered: true, design_outdoor: -15, design_flow: 55, room: 21, exponent: 1.3, offset: 0,
  hard_min: 20, hard_max: 70, circuit_max: null, boiler_max: null, room_auto: true,
  comfort_correction: false, correction_max_k: 3, advanced: false,
};

function state(attributes: Record<string, unknown>, value = "heating"): HassEntity {
  return { entity_id: "sensor.control_state", state: value, attributes, last_changed: "", last_updated: "" };
}

describe("the chart", () => {
  it("reaches past the design frost and the highest water", () => {
    expect(chartFor(SETTINGS)).toEqual({ outdoorFrom: -20, outdoorTo: 20, waterFrom: 15, waterTo: 75 });
    expect(chartFor({ ...SETTINGS, design_outdoor: -22, hard_max: 80 })).toMatchObject({
      outdoorFrom: -30, waterTo: 85,
    });
  });

  it("places points and draws a path through them", () => {
    const chart = chartFor(SETTINGS);
    expect(place(chart, -20, 75)).toEqual({ x: 0, y: 0 });
    expect(place(chart, 20, 15)).toEqual({ x: 1, y: 1 });
    expect(pathOf(chart, [[-20, 75], [0, 45]], 1000, 280)).toBe("M0.0 0.0L500.0 140.0");
    expect(pathOf(chart, [], 1000, 280)).toBe("");
  });

  it("puts ticks on round values", () => {
    expect(ticks(-20, 20, 10)).toEqual([-20, -10, 0, 10, 20]);
    expect(ticks(15, 75, 10)).toEqual([20, 30, 40, 50, 60, 70]);
  });
});

describe("where we are", () => {
  it("is the decided water at the curve's outdoor temperature", () => {
    expect(whereNow(state({ curve_outdoor: 3.8, target: 41.1, curve_room: 21 }))).toEqual({
      outdoor: 3.8, water: 41.1, room: 21,
    });
  });
  it("is nowhere before a decision", () => {
    expect(whereNow(state({ curve_outdoor: null, target: 41 }))).toBeNull();
    expect(whereNow(state({ curve_outdoor: 3, target: null }))).toBeNull();
    expect(whereNow(undefined)).toBeNull();
    expect(whereNow(state({ curve_outdoor: 3, target: 40 }))).toMatchObject({ room: null });
  });
});

describe("the last days' decisions", () => {
  it("keeps one heating decision an hour, carrying attributes forward", () => {
    const hour = 3600;
    const dots = pastDecisions([
      { s: "heating", a: { curve_outdoor: 2, target: 44 }, lu: 10 * hour },
      { s: "heating", lu: 10 * hour + 600 }, // the same hour
      { s: "idle", a: { curve_outdoor: 3, target: 43 }, lu: 11 * hour },
      { s: "heating", lu: 12 * hour }, // the attributes of the state before
      { s: "heating", a: { curve_outdoor: null, target: 40 }, lu: 13 * hour },
      { s: "heating", a: { curve_outdoor: 6, target: 39.5 }, lu: 14 * hour },
    ]);
    expect(dots).toEqual([[2, 44], [3, 43], [6, 39.5]]);
  });
});

describe("dragging the design point", () => {
  const chart = chartFor(SETTINGS);
  it("lands on half degrees", () => {
    const at = place(chart, -12.3, 57.8);
    expect(dragTo(chart, at.x, at.y)).toEqual({ design_outdoor: -12.5, design_flow: 58 });
  });
  it("stays where a curve can stand", () => {
    expect(dragTo(chart, 1, 0)).toEqual({ design_outdoor: -5, design_flow: 75 });
    expect(dragTo(chart, -1, 2)).toEqual({ design_outdoor: -20, design_flow: 25 });
  });
});

describe("reading the water off the points", () => {
  const points: [number, number][] = [[-10, 50], [0, 40], [10, 30]];
  it("interpolates between points", () => {
    expect(waterAt(points, -5)).toBe(45);
    expect(waterAt(points, 10)).toBe(30);
  });
  it("gives nothing outside them", () => {
    expect(waterAt(points, 15)).toBeNull();
    expect(waterAt([], 0)).toBeNull();
    expect(waterAt([[0, 40], [0, 40]], 0)).toBe(40);
  });
});
