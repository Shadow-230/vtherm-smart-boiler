// What the Status and alarms tab shows, read from the plugin's own entities: the verdict's
// reasons in order, the alarms with the active ones first, the signals' health and the building
// values with where they come from. Nothing is judged here: the plugin's entities say it all.
import { numberOf } from "./format";
import type { HassEntity } from "./types";

/** The plugin's own texts, from its translations (`translations/*.json`), loaded by Home
 * Assistant in the user's language. */
export type Localize = (key: string) => string;

export const DOMAIN = "vtherm_smart_boiler";

/** The text of an entity's name, state or attribute state from the plugin's translations;
 * `fallback` where the translations do not have it. */
export function entityText(
  localize: Localize | null,
  platform: "sensor" | "binary_sensor" | "button",
  key: string,
  path: string,
  fallback: string,
): string {
  const text = localize?.(`component.${DOMAIN}.entity.${platform}.${key}.${path}`);
  return text || fallback;
}

// ---------------------------------------------------------------------------------- the verdict

export type ReasonKind = "problem" | "missing" | "data" | "fine";

export interface ReasonInfo {
  code: string;
  kind: ReasonKind;
  value: number | null;
  limit: number | null;
  changed_by_control?: boolean;
  detail?: string;
}

const KIND_ORDER: ReasonKind[] = ["problem", "missing", "data", "fine"];

/** How a reason's value and limit read: days, a count, starts per hour, or a share (0–1) shown
 * as a percentage — the codes of `core/verdict.py`. */
export const REASON_UNITS: Record<string, "days" | "count" | "per_hour" | "share"> = {
  monitored_days: "days",
  heating_burns: "count",
  criteria_judged: "count",
  frequent_starts: "per_hour",
  few_starts: "per_hour",
  short_burns: "share",
  long_burns: "share",
  low_condensing: "share",
  good_condensing: "share",
  load_often_below_min_power: "share",
  load_rarely_below_min_power: "share",
};

/** The verdict's reasons from its sensor's attributes, problems first, then what could not be
 * judged, what data is missing, and what is fine — each kind in the plugin's own order. */
export function verdictReasons(entity: HassEntity | undefined): ReasonInfo[] {
  const reasons = entity?.attributes.reasons;
  if (!Array.isArray(reasons)) return [];
  const read = reasons.flatMap((reason): ReasonInfo[] => {
    if (typeof reason !== "object" || reason === null) return [];
    const r = reason as Record<string, unknown>;
    if (typeof r.code !== "string" || !KIND_ORDER.includes(r.kind as ReasonKind)) return [];
    return [
      {
        code: r.code,
        kind: r.kind as ReasonKind,
        value: typeof r.value === "number" ? r.value : null,
        limit: typeof r.limit === "number" ? r.limit : null,
        ...(typeof r.changed_by_control === "boolean" ? { changed_by_control: r.changed_by_control } : {}),
        ...(typeof r.detail === "string" ? { detail: r.detail } : {}),
      },
    ];
  });
  return KIND_ORDER.flatMap((kind) => read.filter((r) => r.kind === kind));
}

/** I13.4: the boiler's lowest and highest output against the house's design load, as the
 * verdict's sensor gives them; `null` where it gives none. */
export interface Sizing {
  minPower: number | null;
  maxPower: number | null;
  designLoad: number | null;
  designOutdoor: number | null;
}

export function verdictSizing(entity: HassEntity | undefined): Sizing | null {
  const sizing = entity?.attributes.sizing;
  if (typeof sizing !== "object" || sizing === null) return null;
  const s = sizing as Record<string, unknown>;
  const found: Sizing = {
    minPower: numberAttribute(s.min_power_kw),
    maxPower: numberAttribute(s.max_power_kw),
    designLoad: numberAttribute(s.design_load_kw),
    designOutdoor: numberAttribute(s.design_outdoor),
  };
  return found.minPower == null && found.maxPower == null && found.designLoad == null ? null : found;
}

// ----------------------------------------------------------------------------------- the alarms

/** The entities that report a problem besides the `alarm_*` ones; "Signals" is on while the
 * boiler link is fine, the others are on while there is a problem. */
const OTHER_ALARMS = ["connection", "long_burn", "outdoor_sensor_problem"] as const;

export type Severity = "alarm" | "warning" | "unknown" | "clear";

export interface AlarmInfo {
  key: string;
  entityId: string;
  severity: Severity;
  /** Why it cannot be judged (`held`, `unknown_input`), the long burn's or the outdoor check's
   * reason; `null` where there is none. */
  reason: string | null;
  /** The limit an alarm compares with, in the alarm's own unit. */
  limit: number | null;
}

const SEVERITY_ORDER: Severity[] = ["alarm", "warning", "unknown", "clear"];

function severityOf(key: string, entity: HassEntity): Severity {
  const state = entity.state;
  if (state === "unavailable" || state === "unknown") return "unknown";
  if (key === "connection") return state === "off" ? "alarm" : "clear";
  if (state !== "on") return "clear";
  // A monitor alarm says its level; the long burn and the outdoor sensor are warnings: the
  // plugin's control changes nothing for them. A control alarm is an alarm.
  if (entity.attributes.level === "warning") return "warning";
  if (key === "long_burn" || key === "outdoor_sensor_problem") return "warning";
  return "alarm";
}

/** Every alarm the plugin has, active ones first (alarms, then warnings), then the ones that
 * cannot be judged now, then the clear ones; by key within each. */
export function alarmList(entities: Record<string, string>, states: Record<string, HassEntity>): AlarmInfo[] {
  const keys = Object.keys(entities).filter(
    (key) => key.startsWith("alarm_") || (OTHER_ALARMS as readonly string[]).includes(key),
  );
  const found = keys.flatMap((key): AlarmInfo[] => {
    const entity = states[entities[key]];
    if (!entity) return [];
    const attributes = entity.attributes;
    const reason =
      typeof attributes.reason === "string"
        ? attributes.reason
        : key === "outdoor_sensor_problem" && typeof attributes.status === "string"
          ? attributes.status
          : null;
    return [
      {
        key,
        entityId: entity.entity_id,
        severity: severityOf(key, entity),
        reason,
        limit: typeof attributes.limit === "number" ? attributes.limit : null,
      },
    ];
  });
  return found.sort(
    (a, b) =>
      SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity) || a.key.localeCompare(b.key),
  );
}

// ---------------------------------------------------------------------------------- the signals

export type SignalStatus = "ok" | "stale" | "unavailable" | "not_mapped";

export interface SignalInfo {
  signal: string;
  status: SignalStatus;
}

const SIGNAL_ORDER: SignalStatus[] = ["unavailable", "stale", "ok", "not_mapped"];

/** Each signal's health from the "Signal problems" sensor: the ones with a problem first, then
 * those that are fine, then those not mapped; in the plugin's own order within each. */
export function signalList(entity: HassEntity | undefined): SignalInfo[] {
  const signals = entity?.attributes.signals;
  if (typeof signals !== "object" || signals === null || Array.isArray(signals)) return [];
  const read = Object.entries(signals as Record<string, unknown>).flatMap(([signal, status]): SignalInfo[] =>
    SIGNAL_ORDER.includes(status as SignalStatus) ? [{ signal, status: status as SignalStatus }] : [],
  );
  return SIGNAL_ORDER.flatMap((status) => read.filter((s) => s.status === status));
}

// ------------------------------------------------------------------------- the building values

export interface BuildingValue {
  value: number | null;
  unit: string;
  /** default, suggested, entered, measured or learned. */
  source: string | null;
  confidence: number | null;
  entered: number | null;
  measured: number | null;
  measuredConfidence: number | null;
  measuredRange: [number, number] | null;
  mismatch: boolean;
}

const numberAttribute = (value: unknown): number | null => (typeof value === "number" ? value : null);

/** A building value's sensor read: the value in use with its source, and the entered and
 * measured values beside it. */
export function buildingValue(entity: HassEntity | undefined): BuildingValue | null {
  if (!entity) return null;
  const a = entity.attributes;
  const range = a.measured_range;
  return {
    value: numberOf(entity.state),
    unit: typeof a.unit_of_measurement === "string" ? a.unit_of_measurement : "",
    source: typeof a.source === "string" ? a.source : null,
    confidence: numberAttribute(a.confidence),
    entered: numberAttribute(a.entered),
    measured: numberAttribute(a.measured),
    measuredConfidence: numberAttribute(a.measured_confidence),
    measuredRange:
      Array.isArray(range) && range.length === 2 && range.every((v) => typeof v === "number")
        ? [range[0] as number, range[1] as number]
        : null,
    mismatch: a.mismatch === true,
  };
}
