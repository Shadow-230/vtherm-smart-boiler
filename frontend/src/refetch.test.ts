import { describe, expect, it } from "vitest";
import { askUntilRunning } from "./refetch";

const NOT_RUNNING = { code: "not_running", message: "Smart Boiler is not running" };

function asker(answers: Array<unknown>) {
  let asked = 0;
  const ask = async () => {
    const answer = answers[Math.min(asked, answers.length - 1)];
    asked += 1;
    if (answer instanceof Error || (typeof answer === "object" && answer !== null && "code" in answer)) {
      throw answer;
    }
    return answer as string;
  };
  return { ask, asked: () => asked };
}

describe("askUntilRunning", () => {
  it("asks again while the plugin reloads, until it answers", async () => {
    const waits: number[] = [];
    const { ask, asked } = asker([NOT_RUNNING, NOT_RUNNING, "installation"]);
    const result = await askUntilRunning(ask, {
      everyMs: 2000,
      withinMs: 30000,
      wait: async (ms) => void waits.push(ms),
    });
    expect(result).toEqual({ kind: "ready", value: "installation" });
    expect(asked()).toBe(3);
    expect(waits).toEqual([2000, 2000, 2000]); // the first wait lets the reload begin
  });

  it("gives up as not running after its time", async () => {
    const { ask, asked } = asker([NOT_RUNNING]);
    const result = await askUntilRunning(ask, { everyMs: 2000, withinMs: 30000, wait: async () => {} });
    expect(result).toEqual({ kind: "not_running" });
    expect(asked()).toBe(15); // every 2 s for 30 s
  });

  it("stops at another error at once", async () => {
    const failure = { code: "unknown_error", message: "boom" };
    const { ask, asked } = asker([failure]);
    const result = await askUntilRunning(ask, { everyMs: 2000, withinMs: 30000, wait: async () => {} });
    expect(result).toEqual({ kind: "error", error: failure });
    expect(asked()).toBe(1);
  });
});
