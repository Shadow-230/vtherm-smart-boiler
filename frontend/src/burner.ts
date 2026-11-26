// The burner tab's arithmetic (docs/en/development/plans/plan-0.2-i10.md, I10.5): the burns are
// the monitor's own, as its last analysis classified them (vtherm_smart_boiler/burns); this only
// sorts them for drawing. Pure.
import type { HassEntity } from "./types";

export type BurnKind = "ch" | "dhw" | "unknown";

export interface BurnInfo {
  start: number; // s
  end: number; // s
  kind: BurnKind;
  start_seen: boolean;
  end_seen: boolean;
}

export interface BurnsAnswer {
  at: number | null;
  burns: BurnInfo[];
}

export interface Bucket {
  from: number; // minutes
  to: number; // minutes; Infinity for the last
  count: number;
  /** Shorter than the monitor's short-burn length. */
  short: boolean;
}

const EDGES = [0, 5, 10, 15, 20, 30, 45];

/** The burns within the last `windowS` seconds before `now`, oldest first. */
export function recentBurns(burns: BurnInfo[], now: number, windowS: number): BurnInfo[] {
  return burns
    .filter((burn) => burn.end > now - windowS && burn.start <= now)
    .sort((a, b) => a.start - b.start);
}

/** I13.5: the share of heating burns under 3 minutes (%), as the short burns' sensor gives it
 * beside its own; `null` where it gives none. */
export function veryShortShare(entity: HassEntity | undefined): number | null {
  const value = entity?.attributes.under_3_min;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** How long the heating burns lasted, in buckets of minutes; the monitor's short-burn length
 * always an edge, so a bucket is short or not. Hot water and burns of unknown kind are left out,
 * as the monitor counts heating burns apart. */
export function histogram(burns: BurnInfo[], shortMin: number): Bucket[] {
  const edges = [...new Set([...EDGES, shortMin])].filter((e) => e >= 0).sort((a, b) => a - b);
  const buckets: Bucket[] = edges.map((from, i) => ({
    from,
    to: i + 1 < edges.length ? edges[i + 1] : Number.POSITIVE_INFINITY,
    count: 0,
    short: from < shortMin,
  }));
  for (const burn of burns) {
    if (burn.kind !== "ch") continue;
    const minutes = (burn.end - burn.start) / 60;
    const bucket = buckets.find((b) => minutes >= b.from && minutes < b.to);
    if (bucket) bucket.count += 1;
  }
  return buckets;
}

/** Minutes, rounded, at least one. */
export function minutesOf(burn: BurnInfo): number {
  return Math.max(1, Math.round((burn.end - burn.start) / 60));
}
