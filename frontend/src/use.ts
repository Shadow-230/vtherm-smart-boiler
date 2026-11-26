// The Use tab's arithmetic (docs/en/development/plans/plan-0.2-i10.md, I10.5): the weeks come
// reckoned by the plugin (vtherm_smart_boiler/days → weeks); the change against yesterday is the
// monitor's own report (its sensor's attributes). This only lays them out. Pure.

export interface WeekUse {
  start: number;
  end: number;
  days: number;
  gas: number | null;
  degree_days: number | null;
  per_degree_day: number | null;
  /** I13.5: where the week's gas per degree-day likely lies, from the house's own scatter;
   * absent or `null` without a signature line to take it from. */
  low?: number | null;
  high?: number | null;
}

/** A week's band as two values, low first; `null` without one. */
export function weekBand(week: WeekUse): [number, number] | null {
  return week.per_degree_day != null && week.low != null && week.high != null ? [week.low, week.high] : null;
}

/** Why a week has no gas per degree-day, by the rule that reckons it (`core/weekly.py`). */
export type WeekGap = "no_week" | "days" | "gas" | "degree_days" | "mild";

const DAYS_IN_WEEK = 7;

/** What keeps `week` from a gas per degree-day; `null` where it has one. */
export function weekGap(week: WeekUse | undefined): WeekGap | null {
  if (!week) return "no_week";
  if (week.per_degree_day != null) return null;
  if (week.days < DAYS_IN_WEEK) return "days";
  if (week.gas == null) return "gas";
  return week.degree_days == null ? "degree_days" : "mild";
}

/** What keeps `week` from its degree-days; `null` where it has them. */
export function degreeDaysGap(week: WeekUse | undefined): WeekGap | null {
  if (!week) return "no_week";
  if (week.degree_days != null) return null;
  return week.days < DAYS_IN_WEEK ? "days" : "degree_days";
}

export const CAUSES = ["weather", "dhw", "settings", "other"] as const;
export type Cause = (typeof CAUSES)[number];

export interface CauseBar {
  cause: Cause;
  amount: number | null;
  /** Share of half the bar's width, 0–100, on the side of the sign. */
  width: number;
  more: boolean;
  /** "Other" within the day-to-day noise the report allows. */
  normal: boolean;
  judged: boolean;
}

/** The report's causes as bars around zero, scaled to the largest. */
export function causeBars(attributes: Record<string, unknown>): CauseBar[] {
  const contributions = (attributes.contributions ?? {}) as Record<string, unknown>;
  const notJudged = Array.isArray(attributes.not_judged) ? attributes.not_judged : [];
  const amounts = CAUSES.map((cause) => {
    const value = contributions[cause];
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  });
  const largest = Math.max(0, ...amounts.map((a) => Math.abs(a ?? 0)));
  return CAUSES.map((cause, i) => {
    const amount = amounts[i];
    return {
      cause,
      amount,
      width: amount == null || largest === 0 ? 0 : (Math.abs(amount) / largest) * 100,
      more: (amount ?? 0) > 0,
      normal: cause === "other" && attributes.other_within_normal === true,
      judged: !notJudged.includes(cause),
    };
  });
}

/** The weekly bars' scale: whole steps above the largest value, a band's top included. */
export function weekScale(weeks: WeekUse[]): number {
  const largest = Math.max(0, ...weeks.map((w) => weekBand(w)?.[1] ?? w.per_degree_day ?? 0));
  if (largest <= 0) return 1;
  const step = largest > 5 ? 2 : largest > 1 ? 1 : 0.2;
  return Math.ceil((largest * 1.1) / step) * step;
}
