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

/** The weekly bars' scale: whole steps above the largest value. */
export function weekScale(weeks: WeekUse[]): number {
  const largest = Math.max(0, ...weeks.map((w) => w.per_degree_day ?? 0));
  if (largest <= 0) return 1;
  const step = largest > 5 ? 2 : largest > 1 ? 1 : 0.2;
  return Math.ceil((largest * 1.1) / step) * step;
}
