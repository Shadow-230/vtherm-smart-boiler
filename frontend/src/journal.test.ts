import { describe, expect, it } from "vitest";
import {
  DAY_MS,
  HOUR_MS,
  alarmSpans,
  callSpans,
  controlSpans,
  groupOf,
  shownEntries,
  timeTicks,
  waterRange,
  waterSteps,
  type JournalEntry,
} from "./journal";

const at = (hours: number) => (hours * HOUR_MS) / 1000;
const e = (hours: number, kind: JournalEntry["kind"], extra: Partial<JournalEntry> = {}): JournalEntry => ({
  at: at(hours),
  kind,
  ...extra,
});
const H = (hours: number) => hours * HOUR_MS;

describe("the spans", () => {
  const entries = [
    e(1, "took_over"),
    e(2, "call_on"),
    e(3, "call_off"),
    e(5, "call_on"),
    e(6, "handed_back"),
    e(6, "call_off"),
    e(7, "took_over"),
    e(8, "call_on"),
    e(9, "stopped"),
    e(10, "started"),
    e(11, "call_on"),
  ];

  it("pair the heat call's start and end; the stop ends it; one still on is open", () => {
    expect(callSpans(entries, 0, H(12))).toEqual([
      { start: H(2), end: H(3), open: false },
      { start: H(5), end: H(6), open: false },
      { start: H(8), end: H(9), open: false },
      { start: H(11), end: H(12), open: true },
    ]);
  });

  it("start at the window's beginning, and leave out what ended before it", () => {
    expect(callSpans(entries, H(5.5), H(12))[0]).toEqual({ start: H(5.5), end: H(6), open: false });
    expect(callSpans(entries, H(5.5), H(12))).toHaveLength(3);
    expect(callSpans(entries, 0, H(4))).toEqual([{ start: H(2), end: H(3), open: false }]);
  });

  it("show when control held the boiler", () => {
    expect(controlSpans(entries, 0, H(12))).toEqual([
      { start: H(1), end: H(6), open: false },
      { start: H(7), end: H(9), open: false },
    ]);
  });

  it("follow each alarm and the highest level it reached", () => {
    const alarms = [
      e(1, "alarm_on", { subject: "alarm_pressure_low", level: "warning" }),
      e(2, "alarm_on", { subject: "alarm_write_failed", level: "alarm" }),
      e(3, "alarm_on", { subject: "alarm_pressure_low", level: "alarm" }),
      e(4, "alarm_off", { subject: "alarm_pressure_low" }),
      e(5, "alarm_on", { subject: "alarm_pressure_low", level: "warning" }),
      e(6, "stopped"),
    ];
    expect(alarmSpans(alarms, 0, H(8))).toEqual([
      { subject: "alarm_pressure_low", level: "alarm", span: { start: H(1), end: H(4), open: false } },
      { subject: "alarm_pressure_low", level: "warning", span: { start: H(5), end: H(6), open: false } },
      { subject: "alarm_write_failed", level: "alarm", span: { start: H(2), end: H(6), open: false } },
    ]);
  });
});

describe("the water", () => {
  it("holds each value until the next, with a gap where control let go", () => {
    const entries = [
      e(1, "water", { value: 40 }),
      e(3, "water", { value: 42 }),
      e(4, "handed_back"),
      e(6, "water", { value: 38 }),
    ];
    expect(waterSteps(entries, H(2), H(8))).toEqual([
      [H(2), 40],
      [H(3), 42],
      [H(4), null],
      [H(6), 38],
      [H(8), 38],
    ]);
    expect(waterSteps([], H(2), H(8))).toEqual([
      [H(2), null],
      [H(8), null],
    ]);
  });

  it("is drawn over a range rounded out to 5 K, at least 10 K wide", () => {
    expect(waterRange([[0, 38.2], [1, 51.4], [2, null]])).toEqual([35, 55]);
    expect(waterRange([[0, 40]])).toEqual([35, 45]);
    expect(waterRange([[0, null]])).toEqual([20, 60]);
  });
});

describe("the list", () => {
  it("shows the groups picked within the window, newest first", () => {
    const entries = [
      e(1, "started"),
      e(2, "call_on"),
      e(3, "water", { value: 40 }),
      e(4, "alarm_on", { subject: "alarm_pressure_low" }),
      e(5, "settings", { subject: "page" }),
    ];
    expect(entries.map(groupOf)).toEqual(["control", "call", "water", "alarm", "settings"]);
    const shown = shownEntries(entries, H(1.5), H(10), new Set(["call", "alarm", "settings"]));
    expect(shown.map((x) => x.kind)).toEqual(["settings", "alarm_on", "call_on"]);
  });
});

describe("the time axis", () => {
  it("counts hours within a day and days beyond", () => {
    const from = new Date(2026, 10, 16, 0, 0).getTime();
    const hours = timeTicks(from, from + DAY_MS, "pl");
    expect(hours).toHaveLength(9);
    expect(hours[1].label).toBe("03:00");
    const days = timeTicks(from, from + 7 * DAY_MS, "en");
    expect(days.map((d) => new Date(d.t).getDate())).toEqual([17, 18, 19, 20, 21, 22, 23]);
    expect(timeTicks(from, from + 14 * DAY_MS, "en")).toHaveLength(7);
    expect(timeTicks(from, from + 14 * DAY_MS, "en", true)).toHaveLength(4);
  });
});
