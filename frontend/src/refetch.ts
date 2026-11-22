// After a save from the page the plugin reloads its settings, and its commands answer
// "not_running" until its new run is set up — which may take longer than a fixed wait
// (the test session's review of 2026-11-22, F17's follow-up): the page asks again until the
// plugin answers, keeping what it shows meanwhile.

export type Asked<T> =
  | { kind: "ready"; value: T }
  | { kind: "not_running" }
  | { kind: "error"; error: unknown };

export interface AskOptions {
  /** How long between two asks, the first included: the reload begins meanwhile. */
  everyMs: number;
  /** How long to keep asking while the plugin is not running. */
  withinMs: number;
  wait: (ms: number) => Promise<void>;
}

function notRunning(err: unknown): boolean {
  return (err as { code?: unknown })?.code === "not_running";
}

/** `ask` after `everyMs`, and again every `everyMs` while it answers "not_running", for
 * `withinMs` at most; another error ends it at once. */
export async function askUntilRunning<T>(ask: () => Promise<T>, options: AskOptions): Promise<Asked<T>> {
  const tries = Math.max(1, Math.floor(options.withinMs / options.everyMs));
  for (let attempt = 1; attempt <= tries; attempt += 1) {
    await options.wait(options.everyMs);
    try {
      return { kind: "ready", value: await ask() };
    } catch (err) {
      if (!notRunning(err)) return { kind: "error", error: err };
    }
  }
  return { kind: "not_running" };
}
