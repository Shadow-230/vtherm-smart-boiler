// What the Journal tab draws from the plugin's journal (vtherm_smart_boiler/journal): each entry's
// group, the spans the heat call, control and each alarm lasted, the water's steps and the time
// axis. The entries are the plugin's own; nothing is decided here.
import { dayOfMonth, nextMidnight } from "./time";
import { clock } from "./timeline";

export const HOUR_MS = 3600000;
export const DAY_MS = 24 * HOUR_MS;
/** The windows the tab offers, in days. */
export const WINDOWS = [1, 3, 7, 14] as const;

export type Kind =
  | "started"
  | "stopped"
  | "call_on"
  | "call_off"
  | "water"
  | "circuit_need"
  | "circuit_need_end"
  | "handed_back"
  | "took_over"
  | "alarm_on"
  | "alarm_off"
  | "settings";

export interface JournalEntry {
  /** Seconds since the epoch, as the plugin keeps them. */
  at: number;
  kind: Kind;
  reasons?: string[];
  value?: number;
  previous?: number;
  subject?: string;
  level?: string;
}

export interface JournalAnswer {
  entries: JournalEntry[];
  days: number;
  max: number;
}

export type Group = "control" | "call" | "water" | "alarm" | "settings";
export const GROUPS: Group[] = ["control", "call", "water", "alarm", "settings"];

const GROUP_OF: Record<Kind, Group> = {
  started: "control",
  stopped: "control",
  took_over: "control",
  handed_back: "control",
  call_on: "call",
  call_off: "call",
  water: "water",
  circuit_need: "water",
  circuit_need_end: "water",
  alarm_on: "alarm",
  alarm_off: "alarm",
  settings: "settings",
};

export function groupOf(entry: JournalEntry): Group {
  return GROUP_OF[entry.kind] ?? "control";
}

/** A stretch of time, in milliseconds; `open` while it has not ended by `to`. */
export interface Span {
  start: number;
  end: number;
  open: boolean;
}

const ms = (entry: JournalEntry) => entry.at * 1000;

/** The spans between an entry that starts something and the one that ends it, within
 * [from, to]: one still running at `to` is open; one running at `from` starts there. The
 * plugin's stop ends whatever ran, since nothing is known of the time it did not run. */
export function spans(
  entries: JournalEntry[],
  from: number,
  to: number,
  starts: (e: JournalEntry) => boolean,
  ends: (e: JournalEntry) => boolean,
): Span[] {
  const out: Span[] = [];
  let begun: number | null = null;
  for (const entry of entries) {
    const at = ms(entry);
    if (at > to) break;
    if (begun == null && starts(entry)) begun = at;
    else if (begun != null && (ends(entry) || entry.kind === "stopped")) {
      if (at >= from) out.push({ start: Math.max(begun, from), end: at, open: false });
      begun = null;
    }
  }
  if (begun != null) out.push({ start: Math.max(begun, from), end: to, open: true });
  return out;
}

/** The heat call's spans. */
export function callSpans(entries: JournalEntry[], from: number, to: number): Span[] {
  return spans(entries, from, to, (e) => e.kind === "call_on", (e) => e.kind === "call_off");
}

/** The spans control held the boiler. */
export function controlSpans(entries: JournalEntry[], from: number, to: number): Span[] {
  return spans(entries, from, to, (e) => e.kind === "took_over", (e) => e.kind === "handed_back");
}

/** Each alarm's spans, by its entity key, with the highest level it reached in each. */
export function alarmSpans(
  entries: JournalEntry[],
  from: number,
  to: number,
): { subject: string; level: string; span: Span }[] {
  const subjects = [...new Set(entries.filter((e) => e.kind === "alarm_on").map((e) => e.subject ?? ""))];
  return subjects.flatMap((subject) => {
    const out: { subject: string; level: string; span: Span }[] = [];
    let begun: number | null = null;
    let level = "warning";
    for (const entry of entries) {
      const at = ms(entry);
      if (at > to) break;
      const mine = entry.subject === subject;
      if (mine && entry.kind === "alarm_on") {
        if (begun == null) {
          begun = at;
          level = entry.level ?? "alarm";
        } else if (entry.level !== "warning") level = "alarm";
      } else if (begun != null && ((mine && entry.kind === "alarm_off") || entry.kind === "stopped")) {
        if (at >= from) out.push({ subject, level, span: { start: Math.max(begun, from), end: at, open: false } });
        begun = null;
      }
    }
    if (begun != null) out.push({ subject, level, span: { start: Math.max(begun, from), end: to, open: true } });
    return out;
  });
}

/** The water's steps within [from, to] as [time, °C | null]: each value held until the next,
 * a gap (null) where control let go or the plugin stopped. */
export function waterSteps(entries: JournalEntry[], from: number, to: number): [number, number | null][] {
  const out: [number, number | null][] = [];
  let current: number | null = null;
  for (const entry of entries) {
    const at = ms(entry);
    if (at > to) break;
    let next: number | null = current;
    if (entry.kind === "water" && typeof entry.value === "number") next = entry.value;
    else if (entry.kind === "handed_back" || entry.kind === "stopped" || entry.kind === "started") next = null;
    else continue;
    if (at < from) {
      current = next;
      continue;
    }
    if (!out.length) out.push([from, current]);
    out.push([at, next]);
    current = next;
  }
  if (!out.length) out.push([from, current]);
  out.push([to, current]);
  return out;
}

/** The entries within [from, to] of the groups shown, newest first. */
export function shownEntries(entries: JournalEntry[], from: number, to: number, groups: Set<Group>): JournalEntry[] {
  return entries.filter((e) => ms(e) >= from && ms(e) <= to && groups.has(groupOf(e))).reverse();
}

/** The time axis: every few hours within a day or so, else each day at midnight. */
export function timeTicks(
  from: number,
  to: number,
  language: string,
  narrow = false,
  timeZone?: string,
): { t: number; label: string }[] {
  const span = to - from;
  if (span <= 36 * HOUR_MS) {
    const step = (span <= 12 * HOUR_MS ? 2 : narrow ? 6 : 3) * HOUR_MS;
    const out: { t: number; label: string }[] = [];
    for (let t = Math.ceil(from / step) * step; t <= to; t += step) out.push({ t, label: clock(t, language, timeZone) });
    return out;
  }
  const days = span / DAY_MS;
  const every = days > 8 ? (narrow ? 4 : 2) : narrow && days > 4 ? 2 : 1;
  const out: { t: number; label: string }[] = [];
  let k = 0;
  for (let t = nextMidnight(from, timeZone); t <= to; t = nextMidnight(t, timeZone), k++) {
    if (k % every) continue;
    out.push({ t, label: dayLabel(t, language, timeZone) });
  }
  return out;
}

export function dayLabel(t: number, language: string, timeZone?: string): string {
  try {
    return new Intl.DateTimeFormat(language, { weekday: "short", day: "numeric", timeZone }).format(t);
  } catch {
    return String(dayOfMonth(t, timeZone));
  }
}

/** The range of the water's values, rounded out to 5 K, at least 10 K wide. */
export function waterRange(steps: [number, number | null][]): [number, number] {
  const values = steps.flatMap(([, v]) => (v == null ? [] : [v]));
  if (!values.length) return [20, 60];
  let low = Math.floor((Math.min(...values) - 1) / 5) * 5;
  let high = Math.ceil((Math.max(...values) + 1) / 5) * 5;
  if (high - low < 10) high = low + 10;
  return [low, high];
}
