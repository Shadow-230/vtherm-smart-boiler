import { describe, expect, it } from "vitest";
import { LANGUAGES, keysOf, localize, textsFor } from "./localize";

describe("localize", () => {
  it("gives the text in Home Assistant's language", () => {
    expect(localize("pl", "panel.title")).toBe("Kocioł");
    expect(localize("en", "panel.title")).toBe("Boiler");
  });

  it("takes the language without its region", () => {
    expect(localize("pl-PL", "panel.title")).toBe("Kocioł");
    expect(textsFor("PL")).toBe(LANGUAGES.pl);
  });

  it("falls back to English for a language it does not have", () => {
    expect(localize("de", "panel.title")).toBe("Boiler");
    expect(localize(undefined, "panel.title")).toBe("Boiler");
  });

  it("shows the key itself for a text that does not exist", () => {
    expect(localize("pl", "panel.no_such_text")).toBe("panel.no_such_text");
    expect(localize("pl", "panel")).toBe("panel");
  });

  it("has the same keys in every language", () => {
    const source = keysOf(LANGUAGES.en).sort();
    for (const [code, texts] of Object.entries(LANGUAGES)) {
      expect(keysOf(texts).sort(), code).toEqual(source);
    }
  });

  it("has no empty text", () => {
    for (const [code, texts] of Object.entries(LANGUAGES)) {
      for (const key of keysOf(texts)) {
        expect(localize(code, key).trim(), `${code} ${key}`).not.toBe("");
      }
    }
  });
});

describe("localize with values", () => {
  it("puts the values in", () => {
    expect(localize("pl", "schematic.fixed_valve", { value: "35" })).toBe("zawór termostatyczny 35 °C");
  });
  it("leaves a placeholder it has no value for", () => {
    expect(localize("en", "schematic.aria", { status: "idle" })).toBe(
      "Installation: idle. Circuits taking heat: {circuits}.",
    );
  });
});
