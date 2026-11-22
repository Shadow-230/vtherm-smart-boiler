// When things happened, in the time zone the user's profile asks for (F20, J4 of 2026-11-20):
// Home Assistant's for a profile set to "server", the browser's for "local". A day the plugin
// counted is a day in Home Assistant's zone, wherever the browser is. Pure.
import type { HomeAssistant } from "./types";

const MINUTE_MS = 60000;
const DAY_MINUTES = 24 * 60;

/** The zone the profile asks for; `undefined` is the browser's. */
export function profileZone(hass: HomeAssistant | undefined): string | undefined {
  return hass?.locale?.time_zone === "server" ? hass.config?.time_zone : undefined;
}

/** Home Assistant's own zone, the one the plugin counts its days in. */
export function homeZone(hass: HomeAssistant | undefined): string | undefined {
  return hass?.config?.time_zone;
}

/** Whether the times of the profile are not those of Home Assistant's days. */
export function zonesDiffer(hass: HomeAssistant | undefined): boolean {
  const home = homeZone(hass);
  if (!home) return false;
  return (profileZone(hass) ?? new Intl.DateTimeFormat().resolvedOptions().timeZone) !== home;
}

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(zone: string | undefined): Intl.DateTimeFormat {
  const key = zone ?? "";
  let found = formatters.get(key);
  if (!found) {
    const options: Intl.DateTimeFormatOptions = {
      hourCycle: "h23",
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "numeric",
    };
    try {
      found = new Intl.DateTimeFormat("en-US", { ...options, timeZone: zone });
    } catch {
      found = new Intl.DateTimeFormat("en-US", options); // a zone this browser does not know
    }
    formatters.set(key, found);
  }
  return found;
}

interface Wall {
  date: string;
  day: number;
  hour: number;
  minute: number;
}

/** What a clock and a calendar on the wall show at `t` in `zone`. */
function wall(t: number, zone: string | undefined): Wall {
  const parts = Object.fromEntries(formatter(zone).formatToParts(t).map((p) => [p.type, p.value]));
  return {
    date: `${parts.year}-${parts.month}-${parts.day}`,
    day: Number(parts.day),
    hour: Number(parts.hour),
    minute: Number(parts.minute),
  };
}

/** The clock hour, 0–23. */
export function hourOf(t: number, zone?: string): number {
  return wall(t, zone).hour;
}

/** The day of the month. */
export function dayOfMonth(t: number, zone?: string): number {
  return wall(t, zone).day;
}

/** "HH:MM", for where the language's own format is not to be had. */
export function wallClock(t: number, zone?: string): string {
  const { hour, minute } = wall(t, zone);
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

/** The first moment of the next calendar day after `t`: its midnight, or where the clocks skip
 * midnight that night, the moment they land on. */
export function nextMidnight(t: number, zone?: string): number {
  const now = wall(t, zone);
  const whole = Math.floor(t / MINUTE_MS) * MINUTE_MS;
  let at = whole + (DAY_MINUTES - now.hour * 60 - now.minute) * MINUTE_MS;
  // A change of the clocks that day leaves this up to an hour off midnight.
  const seen = wall(at, zone);
  const past = seen.hour * 60 + seen.minute;
  if (past !== 0) at += (past > DAY_MINUTES / 2 ? DAY_MINUTES - past : -past) * MINUTE_MS;
  if (wall(at, zone).date === now.date) at += 60 * MINUTE_MS;
  return at;
}
