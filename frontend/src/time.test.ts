import { describe, expect, it } from "vitest";
import { dayLabel, timeTicks } from "./journal";
import { hourRows, type StoredDay } from "./analyses";
import { dayOfMonth, homeZone, hourOf, nextMidnight, profileZone, wallClock, zonesDiffer } from "./time";
import { clock } from "./timeline";
import type { HomeAssistant } from "./types";

const hass = (time_zone: "local" | "server" | undefined, home = "Asia/Tokyo") =>
  ({ language: "en", locale: { language: "en", time_zone }, config: { time_zone: home } }) as HomeAssistant;

describe("the profile's time zone (F20)", () => {
  it("is Home Assistant's for a profile set to server, the browser's otherwise", () => {
    expect(profileZone(hass("server"))).toBe("Asia/Tokyo");
    expect(profileZone(hass("local"))).toBeUndefined();
    expect(profileZone(hass(undefined))).toBeUndefined();
    expect(profileZone(undefined)).toBeUndefined();
    expect(homeZone(hass("local"))).toBe("Asia/Tokyo");
  });

  it("says when the profile's times are not those of Home Assistant's days", () => {
    expect(zonesDiffer(hass("server"))).toBe(false);
    const browser = new Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(zonesDiffer(hass("local", browser))).toBe(false);
    expect(zonesDiffer(hass("local", browser === "Asia/Tokyo" ? "Europe/Warsaw" : "Asia/Tokyo"))).toBe(true);
    expect(zonesDiffer({ language: "en" } as HomeAssistant)).toBe(false);
  });

  it("reads the clock and the calendar in the zone", () => {
    const t = Date.UTC(2026, 0, 1, 22, 5);
    expect(hourOf(t, "Asia/Tokyo")).toBe(7);
    expect(hourOf(t, "America/New_York")).toBe(17);
    expect(dayOfMonth(t, "Asia/Tokyo")).toBe(2);
    expect(dayOfMonth(t, "America/New_York")).toBe(1);
    expect(wallClock(t, "Asia/Kolkata")).toBe("03:35");
    expect(clock(t, "en-GB", "Asia/Tokyo")).toBe("07:05");
    expect(clock(t, "xx-not-a-language-%%", "Asia/Tokyo")).toBe("07:05");
    expect(dayLabel(t, "en-GB", "Asia/Tokyo")).toMatch(/2/);
    expect(dayLabel(t, "xx-not-a-language-%%", "America/New_York")).toBe("1");
  });

  it("falls back to the browser's zone for one it does not know", () => {
    expect(hourOf(Date.UTC(2026, 0, 1, 6), "Not/AZone")).toBe(new Date(Date.UTC(2026, 0, 1, 6)).getHours());
  });

  it.each([
    ["an ordinary day", "Europe/Warsaw", Date.UTC(2026, 0, 10, 12), Date.UTC(2026, 0, 10, 23)],
    ["a day an hour short", "Europe/Warsaw", Date.UTC(2026, 2, 29, 0, 30), Date.UTC(2026, 2, 29, 22)],
    ["a day an hour long", "Europe/Warsaw", Date.UTC(2026, 9, 25, 0, 30), Date.UTC(2026, 9, 25, 23)],
    ["half an hour off", "Asia/Kolkata", Date.UTC(2026, 0, 10, 12), Date.UTC(2026, 0, 10, 18, 30)],
    ["the very moment of midnight", "Asia/Tokyo", Date.UTC(2026, 0, 9, 15), Date.UTC(2026, 0, 10, 15)],
    ["clocks that skip midnight", "America/Havana", Date.UTC(2026, 2, 7, 20), Date.UTC(2026, 2, 8, 5)],
  ])("finds the next day's start: %s", (_name, zone, from, expected) => {
    expect(nextMidnight(from, zone)).toBe(expected);
  });

  it("marks the days on the time axis at the zone's midnights", () => {
    const from = Date.UTC(2026, 0, 10, 12);
    const ticks = timeTicks(from, from + 3 * 24 * 3600000, "en", false, "Asia/Tokyo");
    expect(ticks.map((tick) => tick.t)).toEqual([15, 15, 15].map((h, k) => Date.UTC(2026, 0, 10 + k, h)));
  });

  it("files a day's starts under the clock hours of the zone it was counted in", () => {
    const start = Date.UTC(2026, 0, 9, 15) / 1000; // midnight in Tokyo
    const hourly = Array<number>(24).fill(0);
    hourly[6] = 3;
    const day = { start, starts: 3, hourly_starts: hourly } as unknown as StoredDay;
    expect(hourRows([day], 1, "Asia/Tokyo")[0].hours[6]).toBe(3);
    expect(hourRows([day], 1, "America/New_York")[0].hours[6]).toBe(0);
  });
});
