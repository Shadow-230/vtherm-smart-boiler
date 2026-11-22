import { describe, expect, it } from "vitest";
import { axisTicks, hourMeans, hourRows, levelOf, niceAxis, signatureRanges, type Signature } from "./analyses";

describe("the axes", () => {
  it("round out to a nice step", () => {
    expect(niceAxis(-7.2, 9.1)).toEqual({ low: -10, high: 10, step: 5 });
    expect(niceAxis(0, 13.4)).toEqual({ low: 0, high: 15, step: 5 });
    expect(niceAxis(0, 0.42)).toEqual({ low: 0, high: 0.5, step: 0.1 });
    expect(niceAxis(3, 3)).toEqual({ low: 3, high: 4, step: 0.2 });
    expect(axisTicks(-10, 10)).toEqual([-10, -5, 0, 5, 10]);
    expect(Object.is(axisTicks(0, 20)[0], -0)).toBe(false);
  });

  it("hold every day, the lines and zero gas", () => {
    const signature: Signature = {
      days: [
        { start: 0, outdoor: -4, gas: 14.8, controlled: false, fitted: true },
        { start: 1, outdoor: 9, gas: 4.1, controlled: true, fitted: true },
      ],
      observing: { line: { slope: -0.8, intercept: 12, low: -6, high: 8, days: 8, r_squared: 0.9, balance: 15 }, reason: null },
      control: { line: null, reason: "too_few_days" },
      comparison: null,
    };
    expect(signatureRanges(signature)).toEqual({ x: [-10, 10], y: [0, 20] });
    expect(signatureRanges({ ...signature, days: [], observing: { line: null, reason: "too_few_days" } })).toEqual({
      x: [-10, 20],
      y: [0, 10],
    });
  });
});

describe("the starts by hour", () => {
  const midnight = (y: number, m: number, d: number) => new Date(y, m, d).getTime() / 1000;

  it("place each hour of a day at its clock hour, newest day first", () => {
    const first = midnight(2026, 10, 16);
    const second = midnight(2026, 10, 17);
    const rows = hourRows(
      [
        { start: first, end: second, starts: 3, hourly_starts: [1, 0, 0, 0, 0, 0, 2, ...Array(17).fill(0)] },
        { start: second, end: second + 86400, starts: 5, hourly_starts: null },
      ],
      28,
    );
    expect(rows.map((r) => r.start)).toEqual([second, first]);
    expect(rows[0].hours.every((h) => h === null)).toBe(true);
    expect(rows[1].hours[0]).toBe(1);
    expect(rows[1].hours[6]).toBe(2);
    expect(rows[1].total).toBe(3);
    expect(hourMeans(rows)[6]).toBe(2); // the day without its hours is left out of the mean
    expect(hourMeans([rows[0]])[6]).toBeNull();
  });

  it("keep only the newest days asked for", () => {
    const days = Array.from({ length: 5 }, (_, k) => ({ start: k * 86400, end: (k + 1) * 86400, starts: 0 }));
    expect(hourRows(days, 3).map((r) => r.start)).toEqual([4 * 86400, 3 * 86400, 2 * 86400]);
  });

  it("put a count on a five-step scale", () => {
    expect([0, 1, 2, 5, 9, 10].map((n) => levelOf(n, 10))).toEqual([0, 1, 1, 3, 5, 5]);
    expect(levelOf(3, 0)).toBe(0);
  });
});
