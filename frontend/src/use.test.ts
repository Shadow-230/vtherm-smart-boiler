import { describe, expect, it } from "vitest";
import { causeBars, degreeDaysGap, weekGap, weekScale, type WeekUse } from "./use";

describe("the change against yesterday", () => {
  it("lays the report's causes around zero, scaled to the largest", () => {
    const bars = causeBars({
      contributions: { weather: 4.0, dhw: -0.8, settings: 1.0, other: 0.4 },
      not_judged: [],
      other_within_normal: true,
    });
    expect(bars.map((b) => [b.cause, b.amount, b.width, b.more, b.normal, b.judged])).toEqual([
      ["weather", 4, 100, true, false, true],
      ["dhw", -0.8, 20, false, false, true],
      ["settings", 1, 25, true, false, true],
      ["other", 0.4, 10, true, true, true],
    ]);
  });

  it("marks a cause not judged and an amount it lacks", () => {
    const bars = causeBars({ contributions: { weather: 2 }, not_judged: ["settings"] });
    expect(bars.find((b) => b.cause === "settings")).toMatchObject({ amount: null, width: 0, judged: false });
    expect(causeBars({})).toHaveLength(4);
    expect(causeBars({ contributions: { weather: 0 } })[0].width).toBe(0);
  });
});

describe("the weeks' scale", () => {
  const week = (v: number | null): WeekUse => ({ start: 0, end: 1, days: 7, gas: null, degree_days: null, per_degree_day: v });
  it("rounds up past the largest week", () => {
    expect(weekScale([week(4.4), week(5.1)])).toBe(6);
    expect(weekScale([week(0.21), week(null)])).toBeCloseTo(0.4);
    expect(weekScale([week(7.3)])).toBe(10);
    expect(weekScale([])).toBe(1);
  });
});

describe("why a week has no value (F20)", () => {
  const week = (changes: Partial<WeekUse>): WeekUse => ({
    start: 0, end: 1, days: 7, gas: 10, degree_days: 20, per_degree_day: 0.5, ...changes,
  });
  it("names what is missing, by the rule that reckons the week", () => {
    expect(weekGap(undefined)).toBe("no_week");
    expect(weekGap(week({}))).toBeNull();
    expect(weekGap(week({ days: 5, gas: null, degree_days: null, per_degree_day: null }))).toBe("days");
    expect(weekGap(week({ gas: null, degree_days: null, per_degree_day: null }))).toBe("gas");
    expect(weekGap(week({ degree_days: null, per_degree_day: null }))).toBe("degree_days");
    expect(weekGap(week({ degree_days: 0.2, per_degree_day: null }))).toBe("mild");
  });
  it("says the same of the degree-days alone", () => {
    expect(degreeDaysGap(undefined)).toBe("no_week");
    expect(degreeDaysGap(week({ gas: null, per_degree_day: null }))).toBeNull();
    expect(degreeDaysGap(week({ days: 3, degree_days: null }))).toBe("days");
    expect(degreeDaysGap(week({ degree_days: null }))).toBe("degree_days");
  });
});
