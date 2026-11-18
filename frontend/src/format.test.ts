import { describe, expect, it } from "vitest";
import { formatNumber, formatTemperature, numberOf } from "./format";

describe("numberOf", () => {
  it("reads a number from a state", () => {
    expect(numberOf("41.5")).toBe(41.5);
    expect(numberOf("-3")).toBe(-3);
  });
  it("gives nothing for an unknown state", () => {
    for (const state of ["unknown", "unavailable", "none", "", "on", undefined, null]) {
      expect(numberOf(state)).toBeNull();
    }
  });
});

describe("formatNumber", () => {
  it("writes numbers as the language does", () => {
    expect(formatNumber(41.25, "pl")).toBe("41,3");
    expect(formatNumber(41.25, "en")).toBe("41.3");
    expect(formatNumber(34, "en", 0)).toBe("34");
  });
  it("writes a dash for no value", () => {
    expect(formatNumber(null, "en")).toBe("—");
    expect(formatNumber(Number.NaN, "en")).toBe("—");
    expect(formatTemperature(null, "pl")).toBe("—");
  });
  it("still writes a number for a language the browser does not know", () => {
    expect(formatNumber(1.5, "xx-not-a-language-%%")).toBe("1.5");
  });
  it("puts the unit after the number", () => {
    expect(formatTemperature(4.1, "pl")).toBe("4,1 °C");
  });
});
