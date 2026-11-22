// The Analyses tab (docs/en/development/plans/plan-0.2-i10.md, I10.7): the energy signature —
// each day's heating gas against its mean outdoor temperature, the days the plugin only watched
// and the days under control apart, each with the line the plugin fitted — and the burner's
// heating starts by clock hour over the last four weeks. Both from vtherm_smart_boiler/days.
import { LitElement, css, html, nothing, svg, type TemplateResult } from "lit";
import {
  axisTicks,
  hourMeans,
  hourRows,
  levelOf,
  signatureRanges,
  type DaysAnswer,
  type Signature,
  type SignatureDay,
  type SignatureFit,
} from "./analyses";
import { formatNumber } from "./format";
import { dayLabel } from "./journal";
import { localize } from "./localize";
import type { HomeAssistant, Installation } from "./types";

export const ANALYSES_TAG = "vtherm-smart-boiler-analyses";

const REFRESH_MS = 30 * 60000; // a new day is summarised once a day; the fits follow it
const ROWS = 28; // days in the starts calendar
const H = 300; // the signature's height, px
const PAD = { left: 44, right: 20, top: 12, bottom: 30 };

export class SmartBoilerAnalyses extends LitElement {
  static properties = {
    hass: { attribute: false },
    installation: { attribute: false },
    answer: { state: true },
    error: { state: true },
    width: { state: true },
    hovered: { state: true },
  };

  declare hass?: HomeAssistant;
  declare installation?: Installation;
  declare answer: DaysAnswer | null;
  declare error: string;
  /** The signature's drawing width, px, as its card lays it out. */
  declare width: number;
  /** The day or the hour the pointer is on: its text. */
  declare hovered: string;
  private timer: number | undefined;
  private resize?: ResizeObserver;

  constructor() {
    super();
    this.answer = null;
    this.error = "";
    this.width = 640;
    this.hovered = "";
  }

  connectedCallback(): void {
    super.connectedCallback();
    this.timer = window.setInterval(() => void this.fetchDays(), REFRESH_MS);
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    window.clearInterval(this.timer);
    this.resize?.disconnect();
  }

  protected firstUpdated(): void {
    void this.fetchDays();
  }

  protected willUpdate(): void {
    this.toggleAttribute("dark", this.hass?.themes?.darkMode === true);
  }

  protected updated(): void {
    const box = this.renderRoot.querySelector<HTMLElement>(".plot");
    if (box && !this.resize) {
      this.resize = new ResizeObserver(([entry]) => {
        const width = Math.round(entry.contentRect.width);
        if (width > 0 && Math.abs(width - this.width) > 1) this.width = width;
      });
      this.resize.observe(box);
    }
  }

  private async fetchDays(): Promise<void> {
    if (!this.hass) return;
    try {
      this.answer = await this.hass.callWS<DaysAnswer>({ type: "vtherm_smart_boiler/days" });
      this.error = "";
    } catch (err) {
      const message = (err as { message?: unknown })?.message;
      this.error = this.t("analyses.error", { message: typeof message === "string" ? message : String(err) });
    }
  }

  private t(key: string, values?: Record<string, string>): string {
    return localize(this.hass?.language, key, values);
  }

  private get language(): string {
    return this.hass?.locale?.language ?? this.hass?.language ?? "en";
  }

  // ---------------------------------------------------------------------- the energy signature

  private gas(value: number, unit: string): string {
    return `${formatNumber(value, this.language, value < 10 ? 2 : 1)}${unit ? ` ${unit}` : ""}`;
  }

  private dayText(day: SignatureDay, unit: string): string {
    return this.t("analyses.day", {
      date: dayLabel(day.start * 1000, this.language),
      outdoor: formatNumber(day.outdoor, this.language, 1),
      gas: this.gas(day.gas, unit),
      group: this.t(day.controlled ? "analyses.control" : "analyses.observing"),
    });
  }

  private fitText(fit: SignatureFit, unit: string): string {
    const line = fit.line;
    if (!line) {
      const rules = this.answer?.signature;
      return this.t(`analyses.no_line_${fit.reason ?? "too_few_days"}`, {
        days: String(rules?.min_days ?? 7),
        spread: formatNumber(rules?.min_spread_k ?? 8, this.language, 0),
      });
    }
    return this.t("analyses.line", {
      slope: this.gas(-line.slope, unit),
      balance: formatNumber(line.balance, this.language, 1),
      days: String(line.days),
      r2: formatNumber(line.r_squared, this.language, 2),
    });
  }

  private plot(signature: Signature, unit: string): TemplateResult {
    const width = Math.max(260, this.width);
    const { x: [x0, x1], y: [y0, y1] } = signatureRanges(signature);
    const px = (x: number) => PAD.left + ((x - x0) / (x1 - x0)) * (width - PAD.left - PAD.right);
    const py = (y: number) => H - PAD.bottom - ((y - y0) / (y1 - y0)) * (H - PAD.top - PAD.bottom);
    const lines = (["observing", "control"] as const).flatMap((group) => {
      const line = signature[group].line;
      if (!line) return [];
      const at = (x: number) => line.intercept + line.slope * x;
      return [svg`<line class="fit ${group}" x1=${px(line.low)} y1=${py(at(line.low))} x2=${px(line.high)} y2=${py(at(line.high))}></line>`];
    });
    const point = (day: SignatureDay) => {
      const group = day.controlled ? "control" : "observing";
      return svg`<circle
        class="day ${group} ${day.fitted ? "" : "hollow"}"
        cx=${px(day.outdoor)}
        cy=${py(day.gas)}
        r="4.5"
        @mouseenter=${() => (this.hovered = this.dayText(day, unit))}
        @mouseleave=${() => (this.hovered = "")}
      ><title>${this.dayText(day, unit)}</title></circle>`;
    };
    return html`<svg
      class="signature"
      width=${width}
      height=${H}
      viewBox="0 0 ${width} ${H}"
      role="img"
      aria-label=${this.t("analyses.signature_summary", {
        count: String(signature.days.length),
        observing: this.fitText(signature.observing, unit),
        control: this.fitText(signature.control, unit),
      })}
    >
      ${axisTicks(y0, y1).map(
        (v) => svg`<line class="grid" x1=${PAD.left} x2=${width - PAD.right} y1=${py(v)} y2=${py(v)}></line>
          <text class="tick" x=${PAD.left - 6} y=${py(v) + 4} text-anchor="end">${formatNumber(v, this.language, v < 1 && v > 0 ? 1 : 0)}</text>`,
      )}
      ${axisTicks(x0, x1, width < 420 ? 4 : 6).map(
        (v) => svg`<line class="grid" x1=${px(v)} x2=${px(v)} y1=${PAD.top} y2=${H - PAD.bottom}></line>
          <text class="tick" x=${px(v)} y=${H - PAD.bottom + 16} text-anchor=${px(v) > width - PAD.right - 20 ? "end" : "middle"}>${formatNumber(v, this.language, 0)} °C</text>`,
      )}
      ${lines}
      ${signature.days.filter((d) => !d.controlled).map(point)}
      ${signature.days.filter((d) => d.controlled).map(point)}
    </svg>`;
  }

  private signatureCard(answer: DaysAnswer): TemplateResult {
    const signature = answer.signature;
    const unit = answer.gas_unit ?? "";
    const compared = signature?.comparison;
    return html`<section class="card">
      <div class="head">
        <h3>${this.t("analyses.signature")}</h3>
        <div class="legend">
          <span><i class="dot observing"></i>${this.t("analyses.observing")}</span>
          <span><i class="dot control"></i>${this.t("analyses.control")}</span>
          <span><i class="dot hollow"></i>${this.t("analyses.not_fitted")}</span>
        </div>
      </div>
      <p class="muted small">${this.t("analyses.signature_hint")}</p>
      ${!signature || signature.days.length === 0
        ? html`<p class="muted">${this.t("analyses.no_days")}</p>`
        : html`<div class="plot">${this.plot(signature, unit)}</div>
            <p class="muted small axis-note">
              ${unit ? this.t("analyses.y_unit", { unit }) : this.t("analyses.y_estimated")}
            </p>
            <p class="hover small" aria-live="polite">${this.hovered || " "}</p>
            <div class="fits">
              <p><i class="dot observing"></i><b>${this.t("analyses.observing")}:</b> ${this.fitText(signature.observing, unit)}</p>
              <p><i class="dot control"></i><b>${this.t("analyses.control")}:</b> ${this.fitText(signature.control, unit)}</p>
              ${compared
                ? html`<p class="compare">
                    ${this.t(compared.change <= 0 ? "analyses.compare_less" : "analyses.compare_more", {
                      outdoor: formatNumber(compared.outdoor, this.language, 1),
                      observing: this.gas(compared.observing, unit),
                      control: this.gas(compared.control, unit),
                      percent: formatNumber(Math.abs(compared.change) * 100, this.language, 0),
                    })}
                  </p>`
                : nothing}
            </div>`}
    </section>`;
  }

  // ---------------------------------------------------------------------- the starts by hour

  private startsCard(answer: DaysAnswer): TemplateResult {
    const rows = hourRows(answer.days, ROWS);
    const means = hourMeans(rows);
    const most = Math.max(1, ...rows.flatMap((r) => r.hours.map((h) => h ?? 0)));
    const lang = this.language;
    const hourLabel = (h: number) => String(h).padStart(2, "0");
    return html`<section class="card">
      <div class="head">
        <h3>${this.t("analyses.starts")}</h3>
        <div class="legend scale" aria-hidden="true">
          <span>0</span>${[1, 2, 3, 4, 5].map((l) => html`<i class="cell l${l}"></i>`)}<span>${most}</span>
          <span><i class="cell none"></i>${this.t("analyses.not_kept")}</span>
        </div>
      </div>
      <p class="muted small">${this.t("analyses.starts_hint")}</p>
      ${rows.length === 0
        ? html`<p class="muted">${this.t("analyses.no_days")}</p>`
        : html`<div class="calendar" role="table" aria-label=${this.t("analyses.starts")}>
            <div class="row head-row" role="row">
              <span class="day" role="columnheader"></span>
              ${Array.from({ length: 24 }, (_, h) => html`<span class="hour" role="columnheader">${h % 3 === 0 ? hourLabel(h) : ""}</span>`)}
              <span class="sum" role="columnheader">Σ</span>
            </div>
            ${rows.map(
              (row) => html`<div class="row" role="row">
                <span class="day" role="rowheader">${dayLabel(row.start * 1000, lang)}</span>
                ${row.hours.map((count, h) => {
                  const text =
                    count == null
                      ? this.t("analyses.hour_not_kept", { date: dayLabel(row.start * 1000, lang) })
                      : this.t("analyses.hour", { date: dayLabel(row.start * 1000, lang), hour: hourLabel(h), count: String(count) });
                  return html`<span
                    class="cell ${count == null ? "none" : `l${levelOf(count, most)}`}"
                    role="cell"
                    title=${text}
                    aria-label=${text}
                    @mouseenter=${() => (this.hovered = text)}
                  ></span>`;
                })}
                <span class="sum" role="cell">${row.total}</span>
              </div>`,
            )}
            <div class="row means" role="row">
              <span class="day" role="rowheader">${this.t("analyses.mean")}</span>
              ${means.map((mean) => {
                const height = mean == null ? 0 : Math.max(2, (mean / Math.max(...means.map((m) => m ?? 0), 0.01)) * 100);
                return html`<span class="bar" role="cell" title=${mean == null ? "" : formatNumber(mean, lang, 1)}>
                  <i style="height: ${height.toFixed(1)}%"></i>
                </span>`;
              })}
              <span class="sum"></span>
            </div>
          </div>`}
    </section>`;
  }

  render() {
    if (!this.hass || !this.installation) return nothing;
    const answer = this.answer;
    if (this.error) return html`<p class="error card" role="alert">${this.error}</p>`;
    if (!answer) return nothing;
    return html`${this.signatureCard(answer)} ${this.startsCard(answer)}`;
  }

  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      gap: 16px;
      container-type: inline-size;
      --sb-observing: #2a78d6;
      --sb-control: #eb6834;
      --sb-heat: 42, 120, 214;
    }
    :host([dark]) {
      --sb-observing: #5b9cf0;
      --sb-control: #f08a5d;
      --sb-heat: 91, 156, 240;
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
      color: var(--error-color, #db4437);
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px 14px;
      font-size: 12px;
      color: var(--secondary-text-color);
    }
    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .legend.scale {
      gap: 3px;
    }
    .legend.scale span + span {
      margin-left: 10px;
    }
    .dot {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      margin-right: 6px;
      vertical-align: -1px;
    }
    .legend .dot {
      margin-right: 0;
    }
    .dot.observing {
      background: var(--sb-observing);
    }
    .dot.control {
      background: var(--sb-control);
    }
    .dot.hollow {
      box-shadow: inset 0 0 0 2px var(--secondary-text-color);
    }
    .plot {
      width: 100%;
      overflow: hidden;
    }
    svg.signature {
      display: block;
      max-width: 100%;
    }
    .grid {
      stroke: var(--divider-color, rgba(0, 0, 0, 0.12));
      stroke-width: 1;
    }
    .tick {
      fill: var(--secondary-text-color);
      font-size: 11px;
      font-variant-numeric: tabular-nums;
    }
    .fit {
      stroke-width: 2.5;
      stroke-linecap: round;
    }
    .fit.observing {
      stroke: var(--sb-observing);
    }
    .fit.control {
      stroke: var(--sb-control);
    }
    circle.day {
      stroke: var(--card-background-color, #fff);
      stroke-width: 2;
      cursor: default;
    }
    circle.day.observing {
      fill: var(--sb-observing);
    }
    circle.day.control {
      fill: var(--sb-control);
    }
    circle.day.hollow {
      fill: var(--card-background-color, #fff);
      stroke-width: 2;
    }
    circle.day.hollow.observing {
      stroke: var(--sb-observing);
    }
    circle.day.hollow.control {
      stroke: var(--sb-control);
    }
    circle.day:hover {
      r: 6.5;
    }
    .axis-note {
      margin-top: 2px;
    }
    .hover {
      min-height: 1.4em;
    }
    .fits p {
      font-size: 13px;
    }
    .compare {
      font-weight: 600;
    }
    .calendar {
      display: flex;
      flex-direction: column;
      gap: 2px;
      margin-top: 8px;
      font-variant-numeric: tabular-nums;
    }
    .row {
      display: grid;
      grid-template-columns: 64px repeat(24, minmax(0, 1fr)) 32px;
      gap: 2px;
      align-items: center;
    }
    @container (max-width: 600px) {
      .row {
        grid-template-columns: 48px repeat(24, minmax(0, 1fr)) 24px;
        gap: 1px;
      }
    }
    .day {
      font-size: 11px;
      color: var(--secondary-text-color);
      white-space: nowrap;
      overflow: hidden;
    }
    .hour {
      font-size: 10px;
      color: var(--secondary-text-color);
      white-space: nowrap;
    }
    .sum {
      font-size: 11px;
      text-align: right;
      color: var(--secondary-text-color);
    }
    .cell {
      display: block;
      height: 14px;
      border-radius: 2px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.06));
    }
    .legend .cell {
      display: inline-block;
      width: 14px;
    }
    .cell.l1 {
      background: rgba(var(--sb-heat), 0.22);
    }
    .cell.l2 {
      background: rgba(var(--sb-heat), 0.4);
    }
    .cell.l3 {
      background: rgba(var(--sb-heat), 0.58);
    }
    .cell.l4 {
      background: rgba(var(--sb-heat), 0.78);
    }
    .cell.l5 {
      background: rgba(var(--sb-heat), 1);
    }
    .cell.none {
      background: repeating-linear-gradient(
        45deg,
        transparent 0 3px,
        var(--divider-color, rgba(0, 0, 0, 0.12)) 3px 5px
      );
    }
    .means {
      margin-top: 4px;
      height: 36px;
      align-items: end;
    }
    .bar {
      height: 100%;
      display: flex;
      align-items: flex-end;
    }
    .bar i {
      display: block;
      width: 100%;
      background: rgba(var(--sb-heat), 0.7);
      border-radius: 2px 2px 0 0;
    }
  `;
}

if (!customElements.get(ANALYSES_TAG)) {
  customElements.define(ANALYSES_TAG, SmartBoilerAnalyses);
}
