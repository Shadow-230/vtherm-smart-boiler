// Numbers as the user's language writes them ("41,1" in Polish), and entity states read as numbers.

const UNKNOWN = new Set(["unknown", "unavailable", "none", ""]);

/** The number an entity's state holds; `null` for unknown, unavailable or anything else. */
export function numberOf(state: string | undefined | null): number | null {
  if (state == null || UNKNOWN.has(state)) return null;
  const value = Number(state);
  return Number.isFinite(value) ? value : null;
}

/** `value` with `digits` decimals in `language`'s own way; "—" for no value. */
export function formatNumber(value: number | null | undefined, language: string, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return "—";
  try {
    return new Intl.NumberFormat(language, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(value);
  } catch {
    return value.toFixed(digits);
  }
}

/** A temperature in °C, one decimal. */
export function formatTemperature(value: number | null | undefined, language: string): string {
  return value == null ? "—" : `${formatNumber(value, language, 1)} °C`;
}
