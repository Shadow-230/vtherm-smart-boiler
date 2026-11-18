// What the Analyses tab draws from the plugin's days (vtherm_smart_boiler/days): the energy
// signature as the plugin fitted it, placed on the chart, and the heating starts of each day by
// clock hour. The fits and the counts are the plugin's own; only their places are reckoned here.

export interface SignatureDay {
  start: number;
  outdoor: number;
  gas: number;
  controlled: boolean;
  fitted: boolean;
}

export interface SignatureLine {
  slope: number;
  intercept: number;
  low: number;
  high: number;
  days: number;
  r_squared: number;
  balance: number;
}

export interface SignatureFit {
  line: SignatureLine | null;
  reason: string | null;
}

export interface Signature {
  days: SignatureDay[];
  observing: SignatureFit;
  control: SignatureFit;
  comparison: { outdoor: number; observing: number; control: number; change: number } | null;
  /** The fit's rules: the heating days and the spread of outdoor temperature a line needs. */
  min_days?: number;
  min_spread_k?: number;
}

export interface StoredDay {
  start: number;
  end: number;
  starts: number;
  hourly_starts?: number[] | null;
}

export interface DaysAnswer {
  days: StoredDay[];
  signature?: Signature;
  gas_unit?: string | null;
}

/** "Nice" ends and steps for an axis over [low, high]: the ends rounded out to the step. */
export function niceAxis(low: number, high: number, ticks = 5): { low: number; high: number; step: number } {
  if (!(high > low)) {
    high = low + 1;
  }
  const raw = (high - low) / ticks;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? 10 * power;
  return { low: Math.floor(low / step) * step, high: Math.ceil(high / step) * step, step };
}

/** The signature chart's ranges: every day, the lines' ends and zero gas included. */
export function signatureRanges(signature: Signature): { x: [number, number]; y: [number, number] } {
  const xs = signature.days.map((d) => d.outdoor);
  const ys = signature.days.map((d) => d.gas);
  for (const fit of [signature.observing, signature.control]) {
    if (fit.line) {
      xs.push(fit.line.low, fit.line.high);
      ys.push(fit.line.intercept + fit.line.slope * fit.line.low);
    }
  }
  if (!xs.length) return { x: [-10, 20], y: [0, 10] };
  const x = niceAxis(Math.min(...xs) - 1, Math.max(...xs) + 1);
  const y = niceAxis(0, Math.max(...ys, 0.1));
  return { x: [x.low, x.high], y: [0, y.high] };
}

/** The ticks of an axis over [low, high]. */
export function axisTicks(low: number, high: number, count = 5): number[] {
  const { step } = niceAxis(low, high, count);
  const out: number[] = [];
  for (let v = Math.ceil(low / step - 1e-9) * step; v <= high + 1e-9; v += step) out.push(Math.round(v * 1e6) / 1e6 || 0); // never "-0"
  return out;
}

export interface HourRow {
  start: number;
  /** Starts by clock hour 0–23; `null` everywhere for a day kept before its hours were. */
  hours: (number | null)[];
  total: number;
}

/** The last `count` days' heating starts by clock hour, newest first: each hour from the day's
 * start placed at its clock hour in the browser's time zone, so a day of 23 or 25 hours lands
 * right (a repeated hour adds up, a skipped one stays empty). */
export function hourRows(days: StoredDay[], count: number): HourRow[] {
  return [...days]
    .sort((a, b) => b.start - a.start)
    .slice(0, count)
    .map((day) => {
      const kept = day.hourly_starts;
      if (!Array.isArray(kept)) return { start: day.start, hours: Array<number | null>(24).fill(null), total: day.starts };
      const hours = Array<number | null>(24).fill(0);
      kept.forEach((n, k) => {
        const hour = new Date((day.start + k * 3600) * 1000).getHours();
        hours[hour] = (hours[hour] ?? 0) + n;
      });
      return { start: day.start, hours, total: day.starts };
    });
}

/** The mean starts in each clock hour over the rows that kept their hours; `null` without any. */
export function hourMeans(rows: HourRow[]): (number | null)[] {
  const kept = rows.filter((r) => r.hours[0] != null);
  return Array.from({ length: 24 }, (_, h) =>
    kept.length ? kept.reduce((sum, r) => sum + (r.hours[h] ?? 0), 0) / kept.length : null,
  );
}

/** A count's step on a five-step scale up to `most`: 0 for none, 1–5 for some. */
export function levelOf(count: number, most: number): number {
  if (count <= 0 || most <= 0) return 0;
  return Math.min(5, Math.max(1, Math.ceil((count / most) * 5)));
}
