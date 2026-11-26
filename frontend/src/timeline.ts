// The last 24 h (docs/en/development/plans/plan-0.2-i10.md, I10.3d): Home Assistant's recorded
// history of the entities the overview reads, turned into the states of any moment — so the whole
// overview can show that moment — and into the chart's series. Pure. Nothing of VT: the rooms
// calling at a moment are the plugin's own count and circuits, the call its "Heat call"
// (plan-0.2-i12.md, decision 6).
import { numberOf } from "./format";
import { wallClock } from "./time";
import type { HassEntity, Installation } from "./types";

export const HOUR_MS = 3600000;
export const WINDOW_MS = 24 * HOUR_MS;

/** One recorded state as Home Assistant's history answers it: state, attributes where they
 * changed, last updated (seconds). */
export interface RecordedState {
  s: string;
  a?: Record<string, unknown>;
  lu: number;
}

export interface Sample {
  t: number; // ms
  state: string;
  attributes: Record<string, unknown>;
}

export type History = Record<string, Sample[]>;

/** The entities the overview reads: the boiler's signals, the plugin's own entities and the
 * weather. */
export function watchedEntities(installation: Installation): string[] {
  const own = ["control_state", "control_setpoint", "demand_count", "boiler_called", "control"]
    .map((key) => installation.entities[key])
    .filter((id): id is string => Boolean(id));
  return [
    ...new Set([
      ...Object.values(installation.signals),
      ...own,
      ...(installation.weather ? [installation.weather] : []),
    ]),
  ];
}

/** The history in time order, each sample carrying the attributes in force then. */
export function parseHistory(answer: Record<string, RecordedState[]>): History {
  const out: History = {};
  for (const [entityId, states] of Object.entries(answer)) {
    let attributes: Record<string, unknown> = {};
    out[entityId] = [...states]
      .sort((x, y) => x.lu - y.lu)
      .map((state) => {
        if (state.a) attributes = state.a;
        return { t: state.lu * 1000, state: state.s, attributes };
      });
  }
  return out;
}

/** The last sample at or before `t`; `undefined` before the first. */
export function sampleAt(samples: Sample[] | undefined, t: number): Sample | undefined {
  if (!samples?.length || samples[0].t > t) return undefined;
  let lo = 0;
  let hi = samples.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (samples[mid].t <= t) lo = mid;
    else hi = mid - 1;
  }
  return samples[lo];
}

/** Home Assistant's states as they were at `t`: each recorded entity as it stood then (unknown
 * before its first record), every entity the recorder has nothing of as it is now. */
export function statesAt(
  history: History,
  t: number,
  now: Record<string, HassEntity>,
): Record<string, HassEntity> {
  const out: Record<string, HassEntity> = { ...now };
  for (const [entityId, samples] of Object.entries(history)) {
    if (!samples.length) continue;
    const sample = sampleAt(samples, t);
    const stamp = new Date(sample?.t ?? t).toISOString();
    out[entityId] = {
      entity_id: entityId,
      state: sample?.state ?? "unknown",
      attributes: sample?.attributes ?? now[entityId]?.attributes ?? {},
      last_changed: stamp,
      last_updated: stamp,
    };
  }
  return out;
}

/** A value over time; `null` while it is unknown — a gap, never the last value carried on. */
export type Series = [t: number, value: number | null][];

/** A number over time — the state, or one attribute of it — `null` where it is unknown. */
export function numbers(samples: Sample[] | undefined, attribute?: string): Series {
  return (samples ?? []).map((sample) => {
    const raw = attribute ? sample.attributes[attribute] : sample.state;
    const value = typeof raw === "number" ? raw : numberOf(typeof raw === "string" ? raw : null);
    return [sample.t, Number.isFinite(value) ? value : null];
  });
}

/** Whether a series holds any known value. */
export function known(series: Series): boolean {
  return series.some(([, v]) => v != null);
}

/** A series' value at `t`: the last at or before it. */
export function valueAt(series: Series, t: number): number | null {
  let found: number | null = null;
  for (const [time, value] of series) {
    if (time > t) break;
    found = value;
  }
  return found;
}

/** The stretches within `from`–`to` while `on` holds for the entity's state. */
export function stretches(
  samples: Sample[] | undefined,
  from: number,
  to: number,
  on: (state: string) => boolean,
): [start: number, end: number][] {
  const out: [number, number][] = [];
  let start: number | null = null;
  const list = samples ?? [];
  const before = sampleAt(list, from);
  if (before && on(before.state)) start = from;
  for (const sample of list) {
    if (sample.t <= from || sample.t > to) continue;
    if (on(sample.state) && start == null) start = sample.t;
    if (!on(sample.state) && start != null) {
      out.push([start, sample.t]);
      start = null;
    }
  }
  if (start != null) out.push([start, to]);
  return out;
}

/** A step path of a series in a `width` × `height` box over `from`–`to` and `low`–`high`: each
 * value holds until the next, as Home Assistant's states do. */
export function stepPath(
  series: Series,
  from: number,
  to: number,
  low: number,
  high: number,
  width: number,
  height: number,
): string {
  const x = (t: number) => ((Math.min(to, Math.max(from, t)) - from) / (to - from)) * width;
  const y = (v: number) => ((high - v) / (high - low)) * height;
  let path = "";
  let drawing = false;
  for (let i = 0; i < series.length; i++) {
    const [t, v] = series[i];
    const next = i + 1 < series.length ? series[i + 1][0] : to;
    if (next <= from || t >= to) continue;
    if (v == null) {
      drawing = false; // unknown: a gap
      continue;
    }
    const start = Math.max(t, from);
    path += `${drawing ? "L" : "M"}${x(start).toFixed(1)} ${y(v).toFixed(1)}L${x(next).toFixed(1)} ${y(v).toFixed(1)}`;
    drawing = true;
  }
  return path;
}

/** A range for the chart's values: whole tens around them, at least 20 °C wide. */
export function rangeOf(series: Series[]): [low: number, high: number] {
  const values = series.flat().flatMap(([, v]) => (v == null ? [] : [v]));
  if (!values.length) return [20, 60];
  let low = Math.floor((Math.min(...values) - 2) / 10) * 10;
  let high = Math.ceil((Math.max(...values) + 2) / 10) * 10;
  if (high - low < 20) high = low + 20;
  return [low, high];
}

/** The hours on the time axis, every `stepHours`, as `HH:MM` in the user's language. */
export function hourTicks(
  from: number,
  to: number,
  stepHours: number,
  language: string,
  timeZone?: string,
): { t: number; label: string }[] {
  const out: { t: number; label: string }[] = [];
  const first = Math.ceil(from / (stepHours * HOUR_MS)) * stepHours * HOUR_MS;
  for (let t = first; t <= to; t += stepHours * HOUR_MS) {
    out.push({ t, label: clock(t, language, timeZone) });
  }
  return out;
}

export function clock(t: number, language: string, timeZone?: string): string {
  try {
    return new Intl.DateTimeFormat(language, { hour: "2-digit", minute: "2-digit", timeZone }).format(t);
  } catch {
    return wallClock(t, timeZone);
  }
}
