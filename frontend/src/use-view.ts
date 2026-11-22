// The Use tab (docs/en/development/plans/plan-0.2-i10.md, I10.5): gas per degree-day and the
// degree-days as tiles, the last 12 weeks' gas per degree-day (reckoned by the plugin), and the
// monitor's report of the change against yesterday, cause by cause. Nothing is computed here.
import { LitElement, css, html, nothing } from "lit";
import { formatNumber, numberOf } from "./format";
import { localize } from "./localize";
import { homeZone } from "./time";
import type { HomeAssistant, Installation } from "./types";
import { causeBars, degreeDaysGap, weekGap, weekScale, type WeekGap, type WeekUse } from "./use";

export const USE_TAG = "vtherm-smart-boiler-use";

/** Two decimals below one unit, so a small change does not read as zero. */
function digitsFor(value: number): number {
  return Math.abs(value) < 1 ? 2 : 1;
}

const REFRESH_MS = 30 * 60000; // daily summaries change once a day

export class SmartBoilerUse extends LitElement {
  static properties = {
    hass: { attribute: false },
    installation: { attribute: false },
    weeks: { state: true },
    error: { state: true },
    hovered: { state: true },
  };

  declare hass?: HomeAssistant;
  declare installation?: Installation;
  declare weeks: WeekUse[] | null;
  declare error: string;
  declare hovered: string;
  private timer: number | undefined;

  constructor() {
    super();
    this.weeks = null;
    this.error = "";
    this.hovered = "";
  }

  connectedCallback(): void {
    super.connectedCallback();
    this.timer = window.setInterval(() => void this.fetchWeeks(), REFRESH_MS);
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    window.clearInterval(this.timer);
  }

  protected firstUpdated(): void {
    void this.fetchWeeks();
  }

  private async fetchWeeks(): Promise<void> {
    if (!this.hass) return;
    try {
      // Only the weeks are needed: no day starts after now, so no day is sent.
      const answer = await this.hass.callWS<{ weeks: WeekUse[] }>({
        type: "vtherm_smart_boiler/days",
        since: Date.now() / 1000,
      });
      this.weeks = answer.weeks;
      this.error = "";
    } catch (err) {
      const message = (err as { message?: unknown })?.message;
      this.error = this.t("use.error", { message: typeof message === "string" ? message : String(err) });
    }
  }

  private t(key: string, values?: Record<string, string>): string {
    return localize(this.hass?.language, key, values);
  }

  private get language(): string {
    return this.hass?.locale?.language ?? this.hass?.language ?? "en";
  }

  private entity(key: string) {
    return this.hass?.states[this.installation?.entities[key] ?? ""];
  }

  private date(seconds: number): string {
    try {
      return new Intl.DateTimeFormat(this.language, { day: "numeric", month: "short", timeZone: homeZone(this.hass) }).format(seconds * 1000);
    } catch {
      return new Date(seconds * 1000).toISOString().slice(0, 10);
    }
  }

  render() {
    if (!this.hass || !this.installation) return nothing;
    const lang = this.language;
    const newest = this.weeks?.[this.weeks.length - 1];
    const tile = (key: string, digits: number, gap: WeekGap | null) => {
      const entity = this.entity(key);
      if (!entity) return nothing;
      const value = numberOf(entity.state);
      // Why there is no value, once the weeks that tell it are read.
      const why = value == null && this.weeks && !this.error ? this.t(`use.why.${gap ?? "other"}`) : "";
      const unit = entity.attributes.unit_of_measurement;
      return html`<div class="card tile">
        <div class="tile-label">${this.t(`use.${key}`)}</div>
        <div class="tile-value">${value == null ? "—" : formatNumber(value, lang, digits)}${value != null && typeof unit === "string" ? html` <span class="unit">${unit}</span>` : nothing}</div>
        <div class="muted small">${why || this.t(`use.${key}_detail`)}</div>
      </div>`;
    };
    const perDegreeDay = this.entity("gas_per_degree_day");
    const unit = typeof perDegreeDay?.attributes.unit_of_measurement === "string" ? perDegreeDay.attributes.unit_of_measurement : "";
    const weeks = this.weeks ?? [];
    const top = weekScale(weeks);
    const report = this.entity("change_report");
    const attributes = report?.attributes ?? {};
    const bars = causeBars(attributes);
    const previous = typeof attributes.previous === "number" ? attributes.previous : null;
    const current = typeof attributes.current === "number" ? attributes.current : null;
    const reportUnit = typeof attributes.unit === "string" ? attributes.unit : "";
    const percent = numberOf(report?.state);
    return html`
      <section class="tiles">${tile("gas_per_degree_day", 2, weekGap(newest))}${tile("degree_days", 0, degreeDaysGap(newest))}</section>
      <div class="row">
        <section class="card wide">
          <h3>${this.t("use.weeks")}</h3>
          <p class="muted small">${this.t("use.weeks_hint")}</p>
          ${this.error
            ? html`<p class="error" role="alert">${this.error}</p>`
            : !weeks.length
              ? html`<p class="muted">${this.t("use.weeks_none")}</p>`
              : !weeks.some((w) => w.per_degree_day != null)
                ? html`<p class="muted why">${this.t(`use.why.${weekGap(newest) ?? "other"}`)}</p>`
              : html`
                  <div class="bars" role="img" aria-label=${weeks.map((w) => this.weekText(w, unit)).join("; ")}>
                    ${weeks.map((w, i) => {
                      const value = w.per_degree_day;
                      const height = value == null ? 0 : (value / top) * 100;
                      return html`<div
                        class="bar-cell"
                        @mouseenter=${() => (this.hovered = this.weekText(w, unit))}
                        @mouseleave=${() => (this.hovered = "")}
                      >
                        ${i === weeks.length - 1 && value != null
                          ? html`<span class="bar-count">${formatNumber(value, lang, 2)}</span>`
                          : nothing}
                        <span class="bar ${i === weeks.length - 1 ? "now" : ""} ${value == null ? "none" : ""}" style="height: ${value == null ? 100 : height.toFixed(1)}%"></span>
                      </div>`;
                    })}
                  </div>
                  <div class="bar-labels" aria-hidden="true">
                    ${weeks.map((w, i) => html`<span>${i % 2 === weeks.length % 2 || i === weeks.length - 1 ? this.date(w.start) : ""}</span>`)}
                  </div>
                  <p class="muted small hover" aria-live="polite">${this.hovered || unit}</p>
                `}
        </section>
        <section class="card side">
          <h3>${this.t("use.change")}</h3>
          ${!report || previous == null || current == null
            ? html`<p class="muted">${this.t("use.no_report")}</p>`
            : html`
                <p class="big">
                  ${this.t("use.total", {
                    sign: current - previous > 0 ? "+" : current - previous < 0 ? "−" : "±",
                    value: formatNumber(Math.abs(current - previous), lang, digitsFor(current - previous)),
                    unit: reportUnit,
                    percent: percent == null ? "—" : `${percent > 0 ? "+" : ""}${formatNumber(percent, lang, 0)} %`,
                  })}
                </p>
                <p class="muted small">${this.t("use.change_hint")}</p>
                <div class="sides muted small"><span>← ${this.t("use.less")}</span><span>${this.t("use.more")} →</span></div>
                ${bars.map(
                  (bar) => html`<div class="cause">
                    <div class="cause-head">
                      <span>${this.t(`use.${bar.cause}`)}
                        ${bar.normal ? html`<span class="muted small"> · ${this.t("use.normal")}</span>` : nothing}
                        ${bar.judged ? nothing : html`<span class="muted small"> · ${this.t("use.not_judged")}</span>`}</span>
                      <b>${bar.amount == null ? "—" : `${bar.amount > 0 ? "+" : bar.amount < 0 ? "−" : "±"}${formatNumber(Math.abs(bar.amount), lang, digitsFor(bar.amount))} ${reportUnit}`}</b>
                    </div>
                    <div class="track">
                      <span class="zero"></span>
                      <span class="fill ${bar.more ? "more" : "less"}" style="width: ${(bar.width / 2).toFixed(1)}%"></span>
                    </div>
                  </div>`,
                )}
                <div class="legend">
                  <span><i class="more"></i>${this.t("use.more")}</span>
                  <span><i class="less"></i>${this.t("use.less")}</span>
                </div>
              `}
        </section>
      </div>
    `;
  }

  private weekText(week: WeekUse, unit: string): string {
    const date = this.date(week.start);
    return week.per_degree_day == null
      ? this.t("use.week_none", { date, why: this.t(`use.why.${weekGap(week) ?? "other"}`) })
      : this.t("use.week", { date, value: `${formatNumber(week.per_degree_day, this.language, 2)} ${unit}`.trim() });
  }

  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      gap: 16px;
      --sb-bar: #2a78d6;
      --sb-more: #e34948;
      --sb-less: #2a78d6;
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
    .why::first-letter {
      text-transform: uppercase;
    }
    .tiles {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }
    .tile {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .tile-label {
      font-size: 13px;
      font-weight: 500;
      color: var(--secondary-text-color);
    }
    .tile-value {
      font-size: 26px;
      font-weight: 600;
      line-height: 1.1;
      font-variant-numeric: tabular-nums;
    }
    .unit {
      font-size: 15px;
      font-weight: 500;
      color: var(--secondary-text-color);
    }
    .row {
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      align-items: flex-start;
    }
    .wide {
      flex: 999 1 560px;
    }
    .side {
      flex: 1 1 340px;
    }
    h3 {
      margin: 0 0 4px;
      font-size: 16px;
      font-weight: 600;
    }
    .muted {
      color: var(--secondary-text-color);
    }
    .small {
      font-size: 12px;
    }
    .error {
      color: var(--error-color, #db4437);
    }
    .bars {
      height: 200px;
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: minmax(0, 1fr);
      gap: 6px;
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.2));
      margin-top: 14px;
    }
    .bar-cell {
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
    }
    .bar {
      display: block;
      border-radius: 4px 4px 0 0;
      background: var(--sb-bar);
      opacity: 0.55;
    }
    .bar.now {
      opacity: 1;
    }
    .bar.none {
      opacity: 1;
      background: repeating-linear-gradient(
        135deg,
        transparent 0 4px,
        var(--divider-color, rgba(0, 0, 0, 0.12)) 4px 6px
      );
    }
    .bar-cell:hover .bar {
      outline: 2px solid var(--primary-text-color);
      outline-offset: 1px;
    }
    .bar-count {
      text-align: center;
      font-size: 12px;
      font-weight: 600;
      margin-bottom: 2px;
    }
    .bar-labels {
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: minmax(0, 1fr);
      gap: 6px;
      font-size: 11px;
      color: var(--secondary-text-color);
      text-align: center;
      margin-top: 6px;
      white-space: nowrap;
    }
    .hover {
      min-height: 16px;
      margin: 8px 0 0;
    }
    .big {
      font-size: 20px;
      font-weight: 700;
      margin: 6px 0 2px;
      font-variant-numeric: tabular-nums;
    }
    .sides {
      display: flex;
      justify-content: space-between;
      margin: 10px 0 6px;
    }
    .cause {
      margin-bottom: 12px;
    }
    .cause-head {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-size: 13px;
      margin-bottom: 4px;
    }
    .cause-head b {
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }
    .track {
      position: relative;
      height: 18px;
      border-radius: 4px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.06));
    }
    .zero {
      position: absolute;
      top: 0;
      bottom: 0;
      left: 50%;
      width: 1px;
      background: var(--divider-color, rgba(0, 0, 0, 0.3));
    }
    .fill {
      position: absolute;
      top: 4px;
      bottom: 4px;
    }
    .fill.more {
      left: 50%;
      border-radius: 0 4px 4px 0;
      background: var(--sb-more);
    }
    .fill.less {
      right: 50%;
      border-radius: 4px 0 0 4px;
      background: var(--sb-less);
    }
    .legend {
      display: flex;
      gap: 6px 16px;
      font-size: 12px;
      color: var(--secondary-text-color);
    }
    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .legend i {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 3px;
    }
    .legend .more {
      background: var(--sb-more);
    }
    .legend .less {
      background: var(--sb-less);
    }
  `;
}

if (!customElements.get(USE_TAG)) {
  customElements.define(USE_TAG, SmartBoilerUse);
}
