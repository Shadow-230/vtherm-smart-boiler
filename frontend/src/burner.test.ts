import { describe, expect, it } from "vitest";
import { histogram, minutesOf, recentBurns, veryShortShare, type BurnInfo } from "./burner";

const burn = (start: number, minutes: number, kind: BurnInfo["kind"] = "ch"): BurnInfo => ({
  start, end: start + minutes * 60, kind, start_seen: true, end_seen: true,
});

describe("the burns", () => {
  it("keeps the last day's, oldest first", () => {
    const burns = [burn(90000, 10), burn(1000, 10), burn(50000, 5)];
    expect(recentBurns(burns, 100000, 86400).map((b) => b.start)).toEqual([50000, 90000]);
  });

  it("counts heating burns by length, the short ones marked", () => {
    const burns = [burn(0, 3), burn(0, 7), burn(0, 9.9), burn(0, 12), burn(0, 50), burn(0, 4, "dhw"), burn(0, 2, "unknown")];
    const buckets = histogram(burns, 10);
    expect(buckets.map((b) => [b.from, b.count, b.short])).toEqual([
      [0, 1, true], [5, 2, true], [10, 1, false], [15, 0, false], [20, 0, false], [30, 0, false], [45, 1, false],
    ]);
    expect(buckets[buckets.length - 1].to).toBe(Number.POSITIVE_INFINITY);
  });

  it("makes the monitor's short-burn length an edge", () => {
    const buckets = histogram([burn(0, 6), burn(0, 8)], 7);
    expect(buckets.map((b) => [b.from, b.to, b.count, b.short]).slice(0, 4)).toEqual([
      [0, 5, 0, true], [5, 7, 1, true], [7, 10, 1, false], [10, 15, 0, false],
    ]);
  });

  it("gives a burn's minutes, at least one", () => {
    expect(minutesOf(burn(0, 0.2))).toBe(1);
    expect(minutesOf(burn(0, 22.4))).toBe(22);
  });
});

describe("the share under 3 minutes (I13.5)", () => {
  const sensor = (attributes: Record<string, unknown>) => ({
    entity_id: "sensor.short",
    state: "40",
    attributes,
    last_changed: "",
    last_updated: "",
  });
  it("is read from the short burns' sensor", () => {
    expect(veryShortShare(sensor({ under_3_min: 12.5 }))).toBe(12.5);
  });
  it("is none where the sensor gives none", () => {
    expect(veryShortShare(undefined)).toBeNull();
    expect(veryShortShare(sensor({ under_3_min: null }))).toBeNull();
    expect(veryShortShare(sensor({}))).toBeNull();
  });
});
