// The Journal tab (docs/en/development/plans/plan-0.2-i10.md, I10.6): what the plugin decided and
// why, from its own journal (vtherm_smart_boiler/journal). The lanes show when control held the
// boiler, the heat call, the water written, the alarms and the settings saved, over a day up to
// the 14 days kept; a drag across them zooms in. The list below tells each entry with its reasons,
// filtered by group. The reasons and names are the plugin's own texts.
import { LitElement, css, html, nothing, svg, type TemplateResult } from "lit";
import { formatNumber } from "./format";
import {
  DAY_MS,
  GROUPS,
  WINDOWS,
  alarmSpans,
  callSpans,
  controlSpans,
  dayLabel,
  groupOf,
  shownEntries,
  timeTicks,
  waterRange,
  waterSteps,
  type Group,
  type JournalAnswer,
  type JournalEntry,
  type Span,
} from "./journal";
import { localize } from "./localize";
import { entityText, type Localize } from "./status";
import { profileZone } from "./time";
import { clock } from "./timeline";
import type { HomeAssistant, Installation } from "./types";

export const JOURNAL_TAG = "vtherm-smart-boiler-journal";

const REFRESH_MS = 60000;
const LIST_PAGE = 100; // entries listed at first, and added by "Show more"
const W = 1000; // the water line's drawing width; it stretches to the lane
const WATER_H = 64;

export class SmartBoilerJournal extends LitElement {
  static properties = {
    hass: { attribute: false },
    installation: { attribute: false },
    texts: { attribute: false },
    answer: { state: true },
    error: { state: true },
    days: { state: true },
    zoom: { state: true },
    groups: { state: true },
    hovered: { state: true },
    selection: { state: true },
    limit: { state: true },
  };

  declare hass?: HomeAssistant;
  declare installation?: Installation;
  declare texts: Localize | null;
  declare answer: JournalAnswer | null;
  declare error: string;
  /** The window, in days back from now. */
  declare days: number;
  /** A zoomed part of the window, in milliseconds; `null` for the whole window. */
  declare zoom: [number, number] | null;
  declare groups: Set<Group>;
  /** The entry the pointer is near: its text. */
  declare hovered: string;
  /** A drag across the lanes: where it began and where it is, as shares of their width. */
  declare selection: [number, number] | null;
  /** How many entries the list shows. */
  declare limit: number;
  private timer: number | undefined;
  private now = Date.now();

  constructor() {
    super();
    this.texts = null;
    this.answer = null;
    this.error = "";
    this.days = 1;
    this.zoom = null;
    this.groups = new Set(GROUPS);
    this.hovered = "";
    this.selection = null;
    this.limit = LIST_PAGE;
  }

  connectedCallback(): void {
    super.connectedCallback();
    this.timer = window.setInterval(() => void this.fetchJournal(), REFRESH_MS);
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    window.clearInterval(this.timer);
  }

  protected firstUpdated(): void {
    void this.fetchJournal();
  }

  protected willUpdate(): void {
    this.toggleAttribute("dark", this.hass?.themes?.darkMode === true);
  }

  private async fetchJournal(): Promise<void> {
    if (!this.hass) return;
    try {
      this.answer = await this.hass.callWS<JournalAnswer>({ type: "vtherm_smart_boiler/journal" });
      this.now = Date.now();
      this.error = "";
    } catch (err) {
      const message = (err as { message?: unknown })?.message;
      this.error = this.t("journal.error", { message: typeof message === "string" ? message : String(err) });
    }
  }

  private t(key: string, values?: Record<string, string>): string {
    return localize(this.hass?.language, key, values);
  }

  private get language(): string {
    return this.hass?.locale?.language ?? this.hass?.language ?? "en";
  }

  private get range(): [number, number] {
    return this.zoom ?? [this.now - this.days * DAY_MS, this.now];
  }

  private choose(days: number): void {
    this.days = days;
    this.zoom = null;
    this.limit = LIST_PAGE;
    this.now = Date.now();
  }

  private toggle(group: Group): void {
    const groups = new Set(this.groups);
    if (groups.has(group)) groups.delete(group);
    else groups.add(group);
    this.groups = groups;
    this.limit = LIST_PAGE;
  }

  // ------------------------------------------------------------------------------- the texts

  private reasons(codes: string[] | undefined): string {
    return (codes ?? [])
      .map((code) => entityText(this.texts, "sensor", "control_state", `state_attributes.reasons.state.${code}`, code))
      .join(", ");
  }

  private alarmName(subject: string | undefined): string {
    const key = subject ?? "";
    const friendly = this.hass?.states[this.installation?.entities[key] ?? ""]?.attributes.friendly_name;
    return entityText(this.texts, "binary_sensor", key, "name", typeof friendly === "string" ? friendly : key);
  }

  private water(value: number | undefined): string {
    return value == null ? "—" : `${formatNumber(value, this.language, 1)} °C`;
  }

  /** What an entry says, and why. */
  entryText(entry: JournalEntry): { title: string; detail: string } {
    switch (entry.kind) {
      case "call_off": {
        const reason = entry.reasons?.[0];
        const why = reason
          ? entityText(this.texts, "binary_sensor", "boiler_called", `state_attributes.call_reason.state.${reason}`, reason)
          : "";
        return { title: this.t("journal.call_off"), detail: why };
      }
      case "water":
        return {
          title:
            entry.previous == null
              ? this.t("journal.water_first", { value: this.water(entry.value) })
              : this.t("journal.water", { value: this.water(entry.value), previous: this.water(entry.previous) }),
          detail: this.reasons(entry.reasons),
        };
      case "circuit_need":
        return { title: this.t("journal.circuit_need", { value: this.water(entry.value) }), detail: this.reasons(entry.reasons) };
      case "alarm_on":
        return {
          title: this.alarmName(entry.subject),
          detail: this.t(entry.level === "warning" ? "journal.raised_warning" : "journal.raised_alarm"),
        };
      case "alarm_off":
        return { title: this.alarmName(entry.subject), detail: this.t("journal.cleared") };
      case "settings": {
        const changed = (entry.reasons ?? []).map((key) => {
          const text = this.t(`journal.section_${key}`);
          return text === `journal.section_${key}` ? key : text;
        });
        return {
          title: this.t(entry.subject === "page" ? "journal.settings_page" : "journal.settings"),
          detail: changed.join(", "),
        };
      }
      default:
        return { title: this.t(`journal.${entry.kind}`), detail: this.reasons(entry.reasons) };
    }
  }

  private when(entry: JournalEntry): string {
    const t = entry.at * 1000;
    const zone = profileZone(this.hass);
    return `${dayLabel(t, this.language, zone)} ${clock(t, this.language, zone)}`;
  }

  // ------------------------------------------------------------------------------- the lanes

  private share(t: number, [from, to]: [number, number]): number {
    return ((t - from) / (to - from)) * 100;
  }

  private spanStyle(span: Span, range: [number, number]): string {
    const left = this.share(span.start, range);
    const width = Math.max(0.2, this.share(span.end, range) - left);
    return `left: ${left.toFixed(3)}%; width: ${width.toFixed(3)}%`;
  }

  private marker(entry: JournalEntry, range: [number, number], cls: string): TemplateResult {
    const { title, detail } = this.entryText(entry);
    return html`<span
      class="marker ${cls}"
      style="left: ${this.share(entry.at * 1000, range).toFixed(3)}%"
      title=${`${this.when(entry)} — ${title}${detail ? ` (${detail})` : ""}`}
    ></span>`;
  }

  private fraction(event: PointerEvent): number {
    const box = (event.currentTarget as HTMLElement).getBoundingClientRect();
    return Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
  }

  private down(event: PointerEvent): void {
    if (event.button !== 0) return;
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    const x = this.fraction(event);
    this.selection = [x, x];
  }

  private move(event: PointerEvent, entries: JournalEntry[], range: [number, number]): void {
    const x = this.fraction(event);
    if (this.selection) this.selection = [this.selection[0], x];
    const t = range[0] + x * (range[1] - range[0]);
    const near = (range[1] - range[0]) * 0.015;
    let best: JournalEntry | null = null;
    for (const entry of entries) {
      const d = Math.abs(entry.at * 1000 - t);
      if (d <= near && (!best || d < Math.abs(best.at * 1000 - t))) best = entry;
    }
    if (best) {
      const { title, detail } = this.entryText(best);
      this.hovered = `${this.when(best)} — ${title}${detail ? ` (${detail})` : ""}`;
    } else this.hovered = "";
  }

  private up(range: [number, number]): void {
    const selection = this.selection;
    this.selection = null;
    if (!selection) return;
    const [a, b] = [Math.min(...selection), Math.max(...selection)];
    // A drag of at least 2 % of the width and ten minutes zooms in; a click does nothing.
    const from = range[0] + a * (range[1] - range[0]);
    const to = range[0] + b * (range[1] - range[0]);
    if (b - a >= 0.02 && to - from >= 600000) {
      this.zoom = [from, to];
      this.limit = LIST_PAGE;
    }
  }

  private lanes(entries: JournalEntry[], range: [number, number]): TemplateResult {
    const [from, to] = range;
    const inRange = entries.filter((e) => e.at * 1000 >= from && e.at * 1000 <= to);
    const control = controlSpans(entries, from, to);
    const calls = callSpans(entries, from, to);
    const alarms = alarmSpans(entries, from, to);
    const subjects = [...new Set(alarms.map((a) => a.subject))].sort();
    const rows = Math.max(1, Math.min(4, subjects.length));
    const steps = waterSteps(entries, from, to);
    const [low, high] = waterRange(steps);
    const x = (t: number) => ((t - from) / (to - from)) * W;
    const y = (v: number) => WATER_H - 4 - ((v - low) / (high - low)) * (WATER_H - 8);
    let path = "";
    let last: number | null = null;
    for (const [t, v] of steps) {
      if (v == null) {
        last = null;
        continue;
      }
      path += last == null ? `M${x(t).toFixed(1)},${y(v).toFixed(1)}` : `H${x(t).toFixed(1)}V${y(v).toFixed(1)}`;
      last = v;
    }
    const narrow = this.offsetWidth > 0 && this.offsetWidth < 600;
    const ticks = timeTicks(from, to, this.language, narrow, profileZone(this.hass));
    const sel = this.selection;
    const shown = inRange.filter((e) => this.groups.has(groupOf(e)));
    return html`<div class="chart">
      <div class="labels" aria-hidden="true">
        <div class="label lane-control">${this.t("journal.lane_control")}</div>
        <div class="label lane-call">${this.t("journal.lane_call")}</div>
        <div class="label lane-water">
          ${this.t("journal.lane_water")}
          <span class="muted small">${formatNumber(low, this.language, 0)}–${formatNumber(high, this.language, 0)} °C</span>
        </div>
        <div class="label lane-alarm" style="height: ${rows * 12 + 12}px">${this.t("journal.lane_alarm")}</div>
        <div class="label lane-settings">${this.t("journal.lane_settings")}</div>
      </div>
      <div
        class="tracks"
        role="img"
        aria-label=${this.t("journal.summary", {
          count: String(inRange.length),
          calls: String(calls.length),
          alarms: String(alarms.length),
        })}
        @pointerdown=${(e: PointerEvent) => this.down(e)}
        @pointermove=${(e: PointerEvent) => this.move(e, shown, range)}
        @pointerup=${() => this.up(range)}
        @pointercancel=${() => (this.selection = null)}
        @pointerleave=${() => (this.hovered = "")}
      >
        ${ticks.map((tick) => html`<span class="grid" style="left: ${this.share(tick.t, range).toFixed(3)}%"></span>`)}
        <div class="track lane-control">
          ${control.map((span) => html`<span class="span control ${span.open ? "open" : ""}" style=${this.spanStyle(span, range)}></span>`)}
          ${this.groups.has("control")
            ? inRange.filter((e) => groupOf(e) === "control").map((e) => this.marker(e, range, e.kind))
            : nothing}
        </div>
        <div class="track lane-call">
          ${calls.map((span) => html`<span class="span call" style=${this.spanStyle(span, range)}></span>`)}
        </div>
        <div class="track lane-water">
          <svg viewBox="0 0 ${W} ${WATER_H}" preserveAspectRatio="none" aria-hidden="true">
            ${path ? svg`<path class="water" d=${path}></path>` : nothing}
          </svg>
          ${this.groups.has("water")
            ? inRange.filter((e) => e.kind === "circuit_need").map((e) => this.marker(e, range, "need"))
            : nothing}
        </div>
        <div class="track lane-alarm" style="height: ${rows * 12 + 12}px">
          ${alarms.map(({ subject, level, span }) => {
            const row = Math.min(rows - 1, subjects.indexOf(subject));
            return html`<span
              class="span alarm ${level}"
              style="${this.spanStyle(span, range)}; top: ${6 + row * 12}px"
              title=${this.alarmName(subject)}
            ></span>`;
          })}
        </div>
        <div class="track lane-settings">
          ${this.groups.has("settings")
            ? inRange.filter((e) => e.kind === "settings").map((e) => this.marker(e, range, "settings"))
            : nothing}
        </div>
        ${sel
          ? html`<span
              class="selection"
              style="left: ${(Math.min(...sel) * 100).toFixed(3)}%; width: ${(Math.abs(sel[1] - sel[0]) * 100).toFixed(3)}%"
            ></span>`
          : nothing}
      </div>
      <div></div>
      <div class="xaxis" aria-hidden="true">
        ${ticks.map(
          (tick) => html`<span class="tick" style="left: ${this.share(tick.t, range).toFixed(3)}%">${tick.label}</span>`,
        )}
      </div>
    </div>`;
  }

  // ---------------------------------------------------------------------------------- render

  render() {
    if (!this.hass || !this.installation) return nothing;
    const answer = this.answer;
    const entries = answer?.entries ?? [];
    const range = this.range;
    const listed = shownEntries(entries, range[0], range[1], this.groups);
    const counts = new Map<Group, number>(GROUPS.map((g) => [g, 0]));
    for (const entry of entries) {
      const t = entry.at * 1000;
      if (t >= range[0] && t <= range[1]) counts.set(groupOf(entry), (counts.get(groupOf(entry)) ?? 0) + 1);
    }
    const lang = this.language;
    const zoomText = this.zoom
      ? this.t("journal.zoomed", {
          from: `${dayLabel(range[0], lang, profileZone(this.hass))} ${clock(range[0], lang, profileZone(this.hass))}`,
          to: `${dayLabel(range[1], lang, profileZone(this.hass))} ${clock(range[1], lang, profileZone(this.hass))}`,
        })
      : "";
    return html`
      <section class="card">
        <div class="head">
          <h3>${this.t("journal.title")}</h3>
          <div class="windows" role="group" aria-label=${this.t("journal.window")}>
            ${WINDOWS.map(
              (days) => html`<button
                class="window ${this.days === days && !this.zoom ? "on" : ""}"
                aria-pressed=${this.days === days && !this.zoom ? "true" : "false"}
                @click=${() => this.choose(days)}
              >
                ${this.t(`journal.days_${days}`)}
              </button>`,
            )}
          </div>
        </div>
        <p class="muted small">
          ${this.zoom
            ? html`${zoomText} <button class="link" @click=${() => (this.zoom = null)}>${this.t("journal.unzoom")}</button>`
            : this.t("journal.hint", { days: String(answer?.days ?? 14), max: formatNumber(answer?.max ?? 2000, lang, 0) })}
        </p>
        ${this.error
          ? html`<p class="error" role="alert">${this.error}</p>`
          : !answer
            ? nothing
            : html`${this.lanes(entries, range)}
                <p class="hover small" aria-live="polite">${this.hovered || " "}</p>`}
      </section>
      <section class="card">
        <div class="head">
          <h3>${this.t("journal.list")}</h3>
          <div class="filters" role="group" aria-label=${this.t("journal.filter")}>
            ${GROUPS.map(
              (group) => html`<button
                class="chip ${group} ${this.groups.has(group) ? "on" : ""}"
                aria-pressed=${this.groups.has(group) ? "true" : "false"}
                @click=${() => this.toggle(group)}
              >
                <i class="dot ${group}"></i>${this.t(`journal.group_${group}`)}
                <span class="count">${counts.get(group) ?? 0}</span>
              </button>`,
            )}
          </div>
        </div>
        ${!answer
          ? nothing
          : listed.length === 0
            ? html`<p class="muted">${this.t("journal.empty")}</p>`
            : html`<ol class="list">
                ${listed.slice(0, this.limit).map((entry) => {
                  const { title, detail } = this.entryText(entry);
                  const group = groupOf(entry);
                  const level = entry.kind === "alarm_on" ? (entry.level === "warning" ? "warning" : "alarm") : "";
                  return html`<li class="item">
                    <time class="muted small" datetime=${new Date(entry.at * 1000).toISOString()}>${this.when(entry)}</time>
                    <i class="dot ${group} ${level} ${entry.kind === "alarm_off" ? "cleared" : ""}" aria-hidden="true"></i>
                    <span class="what">
                      <span>${title}</span>
                      ${detail ? html`<span class="muted small">${detail}</span>` : nothing}
                    </span>
                  </li>`;
                })}
              </ol>
              ${listed.length > this.limit
                ? html`<button class="more" @click=${() => (this.limit += LIST_PAGE)}>
                    ${this.t("journal.more", { count: String(listed.length - this.limit) })}
                  </button>`
                : nothing}`}
      </section>
    `;
  }

  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      gap: 16px;
      container-type: inline-size;
      --sb-call: #eb6834;
      --sb-water: #2a78d6;
      --sb-control: rgba(127, 127, 127, 0.28);
      --sb-settings: #7f56d9;
      --sb-warn: #a35f00;
      --sb-bad: #c62828;
      --sb-good: #2e7d32;
    }
    :host([dark]) {
      --sb-water: #5b9cf0;
      --sb-settings: #a68af0;
      --sb-warn: #f0a030;
      --sb-bad: #ef6a5e;
      --sb-good: #66bb6a;
    }
    .card {
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: var(--ha-card-box-shadow, none);
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      padding: 16px;
      box-sizing: border-box;
      min-width: 0;
    }
    .head {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 8px 16px;
      margin-bottom: 6px;
    }
    h3 {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
    }
    p {
      margin: 6px 0;
    }
    .muted {
      color: var(--secondary-text-color);
    }
    .small {
      font-size: 12px;
    }
    .error {
      color: var(--sb-bad);
    }
    .windows,
    .filters {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    button {
      font: inherit;
      cursor: pointer;
    }
    .window,
    .chip {
      appearance: none;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.2));
      background: transparent;
      color: var(--primary-text-color);
      border-radius: 999px;
      min-height: 32px;
      padding: 0 12px;
      font-size: 13px;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .window.on {
      background: var(--primary-color);
      border-color: var(--primary-color);
      color: var(--text-primary-color, #fff);
    }
    .chip:not(.on) {
      color: var(--secondary-text-color);
      opacity: 0.7;
    }
    .chip:not(.on) .dot {
      background: transparent;
      box-shadow: inset 0 0 0 1.5px var(--secondary-text-color);
    }
    .chip .count {
      font-variant-numeric: tabular-nums;
      color: var(--secondary-text-color);
    }
    .more {
      appearance: none;
      border: 1px solid var(--primary-color);
      background: transparent;
      color: var(--primary-color);
      border-radius: 10px;
      min-height: 36px;
      padding: 0 14px;
      font-weight: 600;
      margin-top: 10px;
    }
    .window:focus-visible,
    .chip:focus-visible,
    .more:focus-visible,
    .link:focus-visible {
      outline: 2px solid var(--primary-color);
      outline-offset: 2px;
    }
    .link {
      appearance: none;
      border: 0;
      background: transparent;
      color: var(--primary-color);
      padding: 0 4px;
      font-size: 12px;
    }
    .chart {
      display: grid;
      grid-template-columns: 120px minmax(0, 1fr);
      column-gap: 10px;
      margin-top: 8px;
    }
    @container (max-width: 600px) {
      .chart {
        grid-template-columns: 72px minmax(0, 1fr);
      }
    }
    .labels {
      display: flex;
      flex-direction: column;
    }
    .label {
      display: flex;
      flex-direction: column;
      justify-content: center;
      font-size: 12px;
      font-weight: 500;
      color: var(--secondary-text-color);
      line-height: 1.2;
    }
    .lane-control,
    .lane-call,
    .lane-settings {
      height: 28px;
    }
    .lane-water {
      height: ${WATER_H}px;
    }
    .tracks {
      position: relative;
      touch-action: pan-y;
      cursor: crosshair;
      user-select: none;
    }
    .track {
      position: relative;
      border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    }
    .track:last-of-type {
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    }
    .grid {
      position: absolute;
      top: 0;
      bottom: 0;
      width: 1px;
      background: var(--divider-color, rgba(0, 0, 0, 0.12));
      pointer-events: none;
    }
    .span {
      position: absolute;
      border-radius: 3px;
      pointer-events: none;
    }
    .span.control {
      top: 2px;
      bottom: 2px;
      background: var(--sb-control);
      border-radius: 4px;
    }
    .span.call {
      top: 7px;
      bottom: 7px;
      background: var(--sb-call);
    }
    .span.alarm {
      height: 8px;
    }
    .span.alarm.alarm {
      background: var(--sb-bad);
    }
    .span.alarm.warning {
      background: var(--sb-warn);
    }
    .span.open {
      border-top-right-radius: 0;
      border-bottom-right-radius: 0;
    }
    svg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      overflow: visible;
    }
    .water {
      fill: none;
      stroke: var(--sb-water);
      stroke-width: 2px;
      vector-effect: non-scaling-stroke;
      stroke-linejoin: round;
    }
    .marker {
      position: absolute;
      top: 50%;
      width: 10px;
      height: 10px;
      margin: -5px 0 0 -5px;
      border-radius: 50%;
      background: var(--card-background-color, #fff);
      box-shadow: 0 0 0 2px var(--card-background-color, #fff);
    }
    .marker.started,
    .marker.stopped {
      border: 2px solid var(--secondary-text-color);
      box-sizing: border-box;
    }
    .marker.stopped {
      background: var(--secondary-text-color);
    }
    .marker.handed_back {
      border: 2px solid var(--sb-bad);
      box-sizing: border-box;
    }
    .marker.took_over {
      border: 2px solid var(--sb-good);
      box-sizing: border-box;
    }
    .marker.need {
      top: 8px;
      background: var(--sb-water);
      border-radius: 2px;
      width: 8px;
      height: 8px;
      margin: -4px 0 0 -4px;
    }
    .marker.settings {
      background: var(--sb-settings);
      border-radius: 2px;
      transform: rotate(45deg);
    }
    .selection {
      position: absolute;
      top: 0;
      bottom: 0;
      background: color-mix(in srgb, var(--primary-color) 18%, transparent);
      border-left: 1px solid var(--primary-color);
      border-right: 1px solid var(--primary-color);
      pointer-events: none;
    }
    .xaxis {
      position: relative;
      height: 18px;
      margin-top: 4px;
      font-size: 11px;
      color: var(--secondary-text-color);
    }
    .tick {
      position: absolute;
      transform: translateX(-50%);
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }
    .hover {
      min-height: 1.4em;
      color: var(--primary-text-color);
    }
    .list {
      list-style: none;
      margin: 8px 0 0;
      padding: 0;
    }
    .item {
      display: grid;
      grid-template-columns: 112px 12px minmax(0, 1fr);
      align-items: baseline;
      gap: 10px;
      padding: 7px 0;
      border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    }
    @container (max-width: 600px) {
      .item {
        grid-template-columns: 12px minmax(0, 1fr);
      }
      .item time {
        grid-column: 1 / -1;
      }
    }
    .what {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }
    .dot {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      flex: none;
    }
    .dot.control {
      background: var(--secondary-text-color);
    }
    .dot.call {
      background: var(--sb-call);
    }
    .dot.water {
      background: var(--sb-water);
    }
    .dot.alarm {
      background: var(--sb-bad);
    }
    .dot.alarm.warning {
      background: var(--sb-warn);
    }
    .dot.alarm.cleared {
      background: var(--sb-good);
    }
    .dot.settings {
      background: var(--sb-settings);
      border-radius: 2px;
      transform: rotate(45deg) scale(0.85);
    }
  `;
}

if (!customElements.get(JOURNAL_TAG)) {
  customElements.define(JOURNAL_TAG, SmartBoilerJournal);
}
