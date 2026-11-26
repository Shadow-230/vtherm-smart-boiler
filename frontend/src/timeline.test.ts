import { describe, expect, it } from "vitest";
import {
  HOUR_MS,
  clock,
  hourTicks,
  known,
  numbers,
  parseHistory,
  rangeOf,
  sampleAt,
  statesAt,
  valueAt,
  stepPath,
  stretches,
  watchedEntities,
} from "./timeline";
import type { HassEntity, Installation } from "./types";

const INSTALLATION: Installation = {
  entry_id: "e", title: "Boiler", boiler: { type: "combi", dhw: "combi", condensing: true },
  circuits: [{
    id: "c", name: "c", control: "unmixed_shared", fixed_temperature: null, max_flow: null, needed: null,
    zones: [{ entity_id: "climate.a", emitter: "radiator" }, { entity_id: "climate.a", emitter: "underfloor" }],
  }],
  signals: { flame: "binary_sensor.flame", flow: "sensor.flow" },
  weather: "weather.home",
  entities: { control_state: "sensor.state", control: "switch.control", features: "sensor.features" },
  curve: null,
  short_burn_min: 10,
};

describe("the entities followed", () => {
  it("are the signals, the plugin's own the overview reads and the weather — never VT's rooms", () => {
    expect(watchedEntities(INSTALLATION)).toEqual([
      "binary_sensor.flame", "sensor.flow", "sensor.state", "switch.control", "weather.home",
    ]);
    expect(watchedEntities({ ...INSTALLATION, weather: null })).not.toContain("weather.home");
  });
});

const HISTORY = parseHistory({
  "sensor.flow": [
    { s: "45.0", lu: 3600 },
    { s: "40.0", lu: 1800 }, // out of order: sorted
    { s: "unavailable", lu: 5400 },
  ],
  "sensor.state": [
    { s: "heating", a: { target: 44, curve_outdoor: 3 }, lu: 1000 },
    { s: "idle", lu: 2000 }, // its attributes carried forward
  ],
});

describe("the history", () => {
  it("is in time order, in milliseconds, with the attributes in force", () => {
    expect(HISTORY["sensor.flow"].map((s) => [s.t, s.state])).toEqual([
      [1800000, "40.0"], [3600000, "45.0"], [5400000, "unavailable"],
    ]);
    expect(HISTORY["sensor.state"][1].attributes).toEqual({ target: 44, curve_outdoor: 3 });
  });

  it("finds the state at any moment", () => {
    const flow = HISTORY["sensor.flow"];
    expect(sampleAt(flow, 1799999)).toBeUndefined();
    expect(sampleAt(flow, 1800000)?.state).toBe("40.0");
    expect(sampleAt(flow, 3599999)?.state).toBe("40.0");
    expect(sampleAt(flow, 9e9)?.state).toBe("unavailable");
    expect(sampleAt([], 1)).toBeUndefined();
    expect(sampleAt(undefined, 1)).toBeUndefined();
  });

  it("gives every recorded entity as it stood, every other one as it is now", () => {
    const now: Record<string, HassEntity> = {
      "sensor.flow": { entity_id: "sensor.flow", state: "50", attributes: { unit: "°C" }, last_changed: "", last_updated: "" },
      "sensor.other": { entity_id: "sensor.other", state: "1", attributes: {}, last_changed: "", last_updated: "" },
    };
    const then = statesAt(HISTORY, 2500000, now);
    expect(then["sensor.flow"].state).toBe("40.0");
    expect(then["sensor.state"]).toMatchObject({ state: "idle", attributes: { target: 44 } });
    expect(then["sensor.other"].state).toBe("1");
    const none = statesAt({ "sensor.flow": [] }, 2500000, now);
    expect(none["sensor.flow"].state).toBe("50"); // the recorder has nothing of it: as it is now
    const before = statesAt(HISTORY, 0, now);
    expect(before["sensor.flow"]).toMatchObject({ state: "unknown", attributes: { unit: "°C" } });
    expect(before["sensor.state"]).toMatchObject({ state: "unknown", attributes: {} });
  });
});

describe("the chart's series", () => {
  it("reads numbers from the state or an attribute, the unknown as gaps", () => {
    expect(numbers(HISTORY["sensor.flow"])).toEqual([[1800000, 40], [3600000, 45], [5400000, null]]);
    expect(known(numbers(HISTORY["sensor.flow"]))).toBe(true);
    expect(known([[1, null]])).toBe(false);
    expect(numbers(HISTORY["sensor.state"], "target")).toEqual([[1000000, 44], [2000000, 44]]);
    expect(numbers(undefined)).toEqual([]);
  });

  it("reads a series' value at a moment", () => {
    const series: [number, number][] = [[10, 1], [20, 2]];
    expect(valueAt(series, 5)).toBeNull();
    expect(valueAt(series, 15)).toBe(1);
    expect(valueAt(series, 99)).toBe(2);
    expect(valueAt([[10, 1], [20, null]], 25)).toBeNull();
  });

  it("finds the stretches while the burner is on, cut to the window", () => {
    const flame = parseHistory({
      f: [{ s: "on", lu: 0 }, { s: "off", lu: 10 }, { s: "on", lu: 20 }, { s: "off", lu: 30 }, { s: "on", lu: 40 }],
    }).f;
    expect(stretches(flame, 5000, 50000, (s) => s === "on")).toEqual([
      [5000, 10000], [20000, 30000], [40000, 50000],
    ]);
    expect(stretches(flame, 12000, 18000, (s) => s === "on")).toEqual([]);
    expect(stretches(undefined, 0, 1, () => true)).toEqual([]);
  });

  it("draws steps, each value holding until the next", () => {
    const path = stepPath([[0, 40], [50, 50]], 0, 100, 40, 60, 100, 20);
    expect(path).toBe("M0.0 20.0L50.0 20.0L50.0 10.0L100.0 10.0");
    expect(stepPath([[-50, 40], [-10, 50]], 0, 100, 40, 60, 100, 20)).toBe("M0.0 10.0L100.0 10.0");
    expect(stepPath([], 0, 100, 40, 60, 100, 20)).toBe("");
    // an unknown value breaks the line: no water drawn while nothing is asked
    expect(stepPath([[0, 40], [30, null], [60, 50]], 0, 100, 40, 60, 100, 20)).toBe(
      "M0.0 20.0L30.0 20.0M60.0 10.0L100.0 10.0",
    );
  });

  it("chooses a range in whole tens around the values", () => {
    expect(rangeOf([[[0, 33], [1, 47]], [[0, 29]]])).toEqual([20, 50]);
    expect(rangeOf([[[0, 41], [1, 42]]])).toEqual([30, 50]);
    expect(rangeOf([])).toEqual([20, 60]);
    expect(rangeOf([[[0, null], [1, 45]]])).toEqual([40, 60]);
  });
});

describe("the time axis", () => {
  it("puts ticks on whole hours", () => {
    const from = Date.UTC(2026, 10, 18, 13, 30);
    const ticks = hourTicks(from, from + 24 * HOUR_MS, 4, "en-GB");
    expect(ticks).toHaveLength(6);
    expect(ticks.every((t) => new Date(t.t).getUTCMinutes() === 0)).toBe(true);
  });
  it("writes the clock in the user's language", () => {
    expect(clock(Date.UTC(2026, 0, 1, 6, 5), "pl")).toMatch(/^\d{2}:05$/);
    expect(clock(Date.UTC(2026, 0, 1, 6, 5), "xx-not-a-language-%%")).toMatch(/^\d{2}:05$/);
  });
});
