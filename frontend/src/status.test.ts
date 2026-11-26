import { describe, expect, it } from "vitest";
import { alarmList, buildingValue, entityText, signalList, verdictReasons, verdictSizing } from "./status";
import type { HassEntity } from "./types";

const entity = (entity_id: string, state: string, attributes: Record<string, unknown> = {}): HassEntity => ({
  entity_id,
  state,
  attributes,
  last_changed: "",
  last_updated: "",
});

describe("the plugin's own texts", () => {
  it("reads a key from the plugin's translations, else the fallback", () => {
    const texts: Record<string, string> = {
      "component.vtherm_smart_boiler.entity.sensor.verdict.state.worth_it": "Worth enabling",
    };
    const localize = (key: string) => texts[key] ?? "";
    expect(entityText(localize, "sensor", "verdict", "state.worth_it", "worth_it")).toBe("Worth enabling");
    expect(entityText(localize, "sensor", "verdict", "state.other", "other")).toBe("other");
    expect(entityText(null, "sensor", "verdict", "state.worth_it", "worth_it")).toBe("worth_it");
  });
});

describe("the verdict's reasons", () => {
  it("puts problems first, then what is missing, the data and what is fine", () => {
    const verdict = entity("sensor.verdict", "not_worth_it", {
      reasons: [
        { code: "long_burns", kind: "fine", value: 0.1, limit: 0.3 },
        { code: "load_unknown", kind: "missing", value: null, limit: null, detail: "estimate_only" },
        { code: "frequent_starts", kind: "problem", value: 4.2, limit: 3, changed_by_control: false },
        { code: "odd", kind: "something else" },
        "not a reason",
      ],
    });
    expect(verdictReasons(verdict)).toEqual([
      { code: "frequent_starts", kind: "problem", value: 4.2, limit: 3, changed_by_control: false },
      { code: "load_unknown", kind: "missing", value: null, limit: null, detail: "estimate_only" },
      { code: "long_burns", kind: "fine", value: 0.1, limit: 0.3 },
    ]);
  });

  it("has none without the sensor or its reasons", () => {
    expect(verdictReasons(undefined)).toEqual([]);
    expect(verdictReasons(entity("sensor.verdict", "unknown"))).toEqual([]);
  });
});

describe("the boiler against the house (I13.4)", () => {
  it("reads the outputs and the design load where known", () => {
    const verdict = entity("sensor.verdict", "not_worth_it", {
      sizing: { min_power_kw: 4, max_power_kw: 25, design_load_kw: 8.8, design_outdoor: -15 },
    });
    expect(verdictSizing(verdict)).toEqual({ minPower: 4, maxPower: 25, designLoad: 8.8, designOutdoor: -15 });
    const partial = entity("sensor.verdict", "not_worth_it", { sizing: { min_power_kw: 4, max_power_kw: "x" } });
    expect(verdictSizing(partial)).toEqual({ minPower: 4, maxPower: null, designLoad: null, designOutdoor: null });
  });

  it("has none without any of them", () => {
    expect(verdictSizing(undefined)).toBeNull();
    expect(verdictSizing(entity("sensor.verdict", "unknown", { sizing: null }))).toBeNull();
    expect(verdictSizing(entity("sensor.verdict", "unknown", { sizing: { design_outdoor: -15 } }))).toBeNull();
  });
});

describe("the alarms", () => {
  const entities = {
    alarm_pressure_low: "binary_sensor.pressure_low",
    alarm_flue_gas_rising: "binary_sensor.flue_rising",
    alarm_write_failed: "binary_sensor.write_failed",
    alarm_handed_back_in_frost: "binary_sensor.in_frost",
    connection: "binary_sensor.signals",
    long_burn: "binary_sensor.long_burn",
    outdoor_sensor_problem: "binary_sensor.outdoor_problem",
    verdict: "sensor.verdict",
  };

  it("lists alarms, then warnings, then the unknown ones, then the clear ones", () => {
    const states = Object.fromEntries(
      [
        entity("binary_sensor.pressure_low", "on", { level: "alarm", limit: 0.8 }),
        entity("binary_sensor.flue_rising", "on", { level: "warning" }),
        entity("binary_sensor.write_failed", "off"),
        entity("binary_sensor.in_frost", "unknown"),
        entity("binary_sensor.signals", "on", { problems: [] }),
        entity("binary_sensor.long_burn", "on", { reason: "water_too_cool" }),
        entity("binary_sensor.outdoor_problem", "off", { status: "ok" }),
        entity("sensor.verdict", "worth_it"),
      ].map((e) => [e.entity_id, e]),
    );
    expect(alarmList(entities, states).map((a) => [a.key, a.severity, a.reason, a.limit])).toEqual([
      ["alarm_pressure_low", "alarm", null, 0.8],
      ["alarm_flue_gas_rising", "warning", null, null],
      ["long_burn", "warning", "water_too_cool", null],
      ["alarm_handed_back_in_frost", "unknown", null, null],
      ["alarm_write_failed", "clear", null, null],
      ["connection", "clear", null, null],
      ["outdoor_sensor_problem", "clear", "ok", null],
    ]);
  });

  it("reads the boiler link as an alarm while it is off", () => {
    const states = { "binary_sensor.signals": entity("binary_sensor.signals", "off", { problems: ["flame"] }) };
    expect(alarmList({ connection: "binary_sensor.signals" }, states)[0].severity).toBe("alarm");
  });

  it("says why one cannot be judged, and skips an entity not in the states", () => {
    const states = {
      "binary_sensor.pressure_low": entity("binary_sensor.pressure_low", "unknown", { reason: "unknown_input" }),
    };
    expect(alarmList(entities, states)).toEqual([
      {
        key: "alarm_pressure_low",
        entityId: "binary_sensor.pressure_low",
        severity: "unknown",
        reason: "unknown_input",
        limit: null,
      },
    ]);
  });
});

describe("the signals' health", () => {
  it("puts the problems first and the signals not mapped last", () => {
    const sensor = entity("sensor.signal_problems", "1", {
      signals: { flame: "ok", flow: "stale", pressure: "not_mapped", return: "unavailable", outdoor: "ok", odd: "?" },
    });
    expect(signalList(sensor)).toEqual([
      { signal: "return", status: "unavailable" },
      { signal: "flow", status: "stale" },
      { signal: "flame", status: "ok" },
      { signal: "outdoor", status: "ok" },
      { signal: "pressure", status: "not_mapped" },
    ]);
    expect(signalList(undefined)).toEqual([]);
    expect(signalList(entity("sensor.signal_problems", "0", { signals: ["flame"] }))).toEqual([]);
  });
});

describe("a building value", () => {
  it("reads the value in use with its source and the measured one beside it", () => {
    const sensor = entity("sensor.loss", "0.182", {
      unit_of_measurement: "kW/K",
      source: "entered",
      confidence: 1,
      entered: 0.182,
      measured: 0.214,
      measured_confidence: 0.71,
      measured_range: [0.171, 0.257],
      mismatch: true,
    });
    expect(buildingValue(sensor)).toEqual({
      value: 0.182,
      unit: "kW/K",
      source: "entered",
      confidence: 1,
      entered: 0.182,
      measured: 0.214,
      measuredConfidence: 0.71,
      measuredRange: [0.171, 0.257],
      mismatch: true,
    });
  });

  it("keeps unknowns unknown", () => {
    expect(buildingValue(entity("sensor.threshold", "unknown"))).toEqual({
      value: null,
      unit: "",
      source: null,
      confidence: null,
      entered: null,
      measured: null,
      measuredConfidence: null,
      measuredRange: null,
      mismatch: false,
    });
    expect(buildingValue(undefined)).toBeNull();
  });
});
