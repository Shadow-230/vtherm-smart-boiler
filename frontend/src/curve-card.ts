// The heating curve card (docs/en/development/plans/plan-0.2-i10.md, I10.3c): the curve as the
// plugin decides the water, "where we are" on it, the last 7 days' decisions, the curve's settings,
// and a preview of changes — drag the design point, shift the curve — that asks the plugin for the
// points and its checks and saves nothing.
import { LitElement, css, html, nothing, svg } from "lit";
import {
  chartFor,
  dragTo,
  pastDecisions,
  pathOf,
  place,
  ticks,
  waterAt,
  whereNow,
  type Chart,
  type Draft,
  type Point,
  type Recorded,
} from "./curve";
import { formatNumber, formatTemperature } from "./format";
import { localize } from "./localize";
import type { CurveSettings, HomeAssistant, Installation } from "./types";

export const CURVE_TAG = "vtherm-smart-boiler-curve";

const W = 1000;
const H = 280;
const DAY_MS = 86400000;

interface CurveAnswer {
  points: Point[];
  problems: string[];
}

export class SmartBoilerCurve extends LitElement {
  static properties = {
    hass: { attribute: false },
    installation: { attribute: false },
    saved: { state: true },
    draft: { state: true },
    draftAnswer: { state: true },
    past: { state: true },
    error: { state: true },
  };

  declare hass?: HomeAssistant;
  declare installation?: Installation;
  declare saved: Point[] | null;
  declare draft: Draft | null;
  declare draftAnswer: CurveAnswer | null;
  declare past: Point[];
  declare error: string;
  private savedRoom: number | null | undefined = undefined;
  private historyAsked = false;
  private asking = false;
  private askAgain = false;

  constructor() {
    super();
    this.saved = null;
    this.draft = null;
    this.draftAnswer = null;
    this.past = [];
    this.error = "";
  }

  private t(key: string, values?: Record<string, string>): string {
    return localize(this.hass?.language, key, values);
  }

  private get language(): string {
    return this.hass?.locale?.language ?? this.hass?.language ?? "en";
  }

  private get settings(): CurveSettings | null {
    return this.installation?.curve ?? null;
  }

  private controlState() {
    const id = this.installation?.entities.control_state;
    return id ? this.hass?.states[id] : undefined;
  }

  /** The room temperature the curve is drawn for: the one control decides with now (Auto
   * follows the warmest room), else the one entered. */
  private room(): number | null {
    return whereNow(this.controlState())?.room ?? this.settings?.room ?? null;
  }

  protected willUpdate(): void {
    const settings = this.settings;
    if (!this.hass || !settings?.entered) return;
    const room = this.room();
    if (room !== this.savedRoom) {
      this.savedRoom = room;
      void this.askSaved(room);
    }
    if (!this.historyAsked) {
      this.historyAsked = true;
      void this.askHistory();
    }
  }

  private async curve(fields: Record<string, number>): Promise<CurveAnswer> {
    const chart = chartFor(this.settings as CurveSettings);
    return (this.hass as HomeAssistant).callWS<CurveAnswer>({
      type: "vtherm_smart_boiler/curve",
      outdoor_from: chart.outdoorFrom,
      outdoor_to: chart.outdoorTo,
      step: 0.5,
      ...fields,
    });
  }

  private async askSaved(room: number | null): Promise<void> {
    try {
      const answer = await this.curve(room == null ? {} : { room });
      this.saved = answer.points;
      this.error = "";
    } catch (err) {
      this.error = this.t("curve.loading_error", { message: messageOf(err) });
    }
  }

  private async askHistory(): Promise<void> {
    const entityId = this.installation?.entities.control_state;
    if (!entityId || !this.hass) return;
    const end = new Date();
    try {
      const answer = await this.hass.callWS<Record<string, Recorded[]>>({
        type: "history/history_during_period",
        start_time: new Date(end.getTime() - 7 * DAY_MS).toISOString(),
        end_time: end.toISOString(),
        entity_ids: [entityId],
        include_start_time_state: true,
        significant_changes_only: false,
        minimal_response: false,
        no_attributes: false,
      });
      this.past = pastDecisions(answer[entityId] ?? []);
    } catch {
      this.past = []; // the dots are a help, not a must: without the recorder there are none
    }
  }

  private async askDraft(): Promise<void> {
    if (this.asking) {
      this.askAgain = true;
      return;
    }
    const draft = this.draft;
    if (!draft) return;
    this.asking = true;
    try {
      const room = this.room();
      this.draftAnswer = await this.curve({ ...draft, ...(room == null ? {} : { room }) });
    } catch (err) {
      this.error = this.t("curve.loading_error", { message: messageOf(err) });
    } finally {
      this.asking = false;
      if (this.askAgain) {
        this.askAgain = false;
        void this.askDraft();
      }
    }
  }

  private setDraft(change: Partial<Draft>): void {
    if (!this.draft) return;
    this.draft = { ...this.draft, ...change };
    void this.askDraft();
  }

  private togglePreview(): void {
    const settings = this.settings;
    if (this.draft || !settings) {
      this.draft = null;
      this.draftAnswer = null;
      return;
    }
    this.draft = {
      design_outdoor: settings.design_outdoor,
      design_flow: settings.design_flow,
      offset: settings.offset,
    };
    void this.askDraft();
  }

  private onPointer(event: PointerEvent, chart: Chart): void {
    const handle = event.currentTarget as HTMLElement;
    if (event.type === "pointerdown") handle.setPointerCapture(event.pointerId);
    if (!handle.hasPointerCapture(event.pointerId)) return;
    if (event.type === "pointerup" || event.type === "pointercancel") {
      handle.releasePointerCapture(event.pointerId);
      return;
    }
    const box = (handle.parentElement as HTMLElement).getBoundingClientRect();
    this.setDraft(
      dragTo(chart, (event.clientX - box.left) / box.width, (event.clientY - box.top) / box.height),
    );
  }

  private onKey(event: KeyboardEvent): void {
    const draft = this.draft;
    if (!draft) return;
    const step: Record<string, [number, number]> = {
      ArrowLeft: [-0.5, 0],
      ArrowRight: [0.5, 0],
      ArrowUp: [0, 0.5],
      ArrowDown: [0, -0.5],
    };
    const move = step[event.key];
    if (!move) return;
    event.preventDefault();
    this.setDraft({
      design_outdoor: Math.min(-5, Math.max(-30, draft.design_outdoor + move[0])),
      design_flow: Math.min(80, Math.max(25, draft.design_flow + move[1])),
    });
  }

  render() {
    const settings = this.settings;
    if (!this.hass || !this.installation) return nothing;
    if (!settings) return this.frame(html`<p class="muted">${this.t("curve.no_curve")}</p>`);
    if (!settings.entered) return this.frame(html`<p class="muted">${this.t("curve.not_entered")}</p>`);
    const chart = chartFor(settings);
    const where = whereNow(this.controlState());
    const lang = this.language;
    const t = (v: number | null) => formatTemperature(v, lang);
    const draft = this.draft;
    const draftPoints = draft ? (this.draftAnswer?.points ?? null) : null;
    const pct = (outdoor: number, water: number) => {
      const p = place(chart, outdoor, water);
      return { left: `${(p.x * 100).toFixed(2)}%`, top: `${(p.y * 100).toFixed(2)}%` };
    };
    const gridLines = ticks(chart.waterFrom + 5, chart.waterTo, 10)
      .map((v) => `M0 ${(place(chart, 0, v).y * H).toFixed(1)}H${W}`)
      .join("");
    const zero = place(chart, 0, chart.waterFrom).x * W;
    const limits = [settings.hard_min, settings.hard_max]
      .map((v) => `M0 ${(place(chart, 0, v).y * H).toFixed(1)}H${W}`)
      .join("");
    const now = where ? pct(where.outdoor, where.water) : null;
    const handle = draft ? pct(draft.design_outdoor, draft.design_flow) : null;
    const effectAt = where?.outdoor ?? 0;
    const savedAt = this.saved ? waterAt(this.saved, effectAt) : null;
    const draftAt = draftPoints ? waterAt(draftPoints, effectAt) : null;
    return this.frame(html`
      <div class="where">
        <div class="muted small">${this.t("curve.where")}</div>
        ${where
          ? html`<div class="big">${t(where.outdoor)} → ${t(where.water)}</div>
              <div class="muted small">
                ${this.t("curve.where_detail", { room: t(where.room ?? settings.room) })}
              </div>`
          : html`<div class="muted">${this.t("curve.where_none")}</div>`}
      </div>
      <div class="chart">
        <div class="yaxis" aria-hidden="true">
          ${ticks(chart.waterFrom + 5, chart.waterTo, 10).map(
            (v) => html`<span style="top: ${pct(0, v).top}">${v}</span>`,
          )}
        </div>
        <div class="plot-wrap">
          <div class="plot" role="img" aria-label=${where ? `${this.t("curve.where")}: ${t(where.outdoor)} → ${t(where.water)}` : this.t("curve.title")}>
            <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
              ${svg`
                <path class="grid" d=${gridLines + `M${zero.toFixed(1)} 0V${H}`}></path>
                <path class="limit" d=${limits}></path>
                <path class=${draft ? "saved" : "line"} d=${this.saved ? pathOf(chart, this.saved, W, H) : ""}></path>
                <path class="line" d=${draftPoints ? pathOf(chart, draftPoints, W, H) : ""}></path>
              `}
            </svg>
            ${this.past.map((p) => {
              const at = pct(p[0], p[1]);
              return html`<span class="past" style="left: ${at.left}; top: ${at.top}"></span>`;
            })}
            <span class="limit-label" style="top: ${pct(0, settings.hard_max).top}"
              >${this.t("curve.highest", { value: t(settings.hard_max) })}</span
            >
            <span class="limit-label" style="top: ${pct(0, settings.hard_min).top}"
              >${this.t("curve.lowest", { value: t(settings.hard_min) })}</span
            >
            ${now ? html`<span class="now" style="left: ${now.left}; top: ${now.top}"></span>` : nothing}
            ${handle && draft
              ? html`<button
                  class="handle"
                  style="left: ${handle.left}; top: ${handle.top}"
                  aria-label=${this.t("curve.handle", {
                    outdoor: t(draft.design_outdoor),
                    water: t(draft.design_flow),
                  })}
                  @pointerdown=${(e: PointerEvent) => this.onPointer(e, chart)}
                  @pointermove=${(e: PointerEvent) => this.onPointer(e, chart)}
                  @pointerup=${(e: PointerEvent) => this.onPointer(e, chart)}
                  @pointercancel=${(e: PointerEvent) => this.onPointer(e, chart)}
                  @keydown=${(e: KeyboardEvent) => this.onKey(e)}
                ></button>`
              : nothing}
          </div>
          <div class="xaxis" aria-hidden="true">
            ${ticks(chart.outdoorFrom, chart.outdoorTo, 10).map(
              (v) => html`<span style="left: ${pct(v, chart.waterFrom).left}">${formatNumber(v, lang, 0)}</span>`,
            )}
          </div>
          <div class="muted small center">${this.t("curve.axis")}</div>
        </div>
      </div>
      <div class="legend">
        <span><i class="dot now-dot"></i>${this.t("curve.legend_now")}</span>
        <span><i class="dot past-dot"></i>${this.t("curve.legend_days")}</span>
        ${draft
          ? html`<span><i class="dash"></i>${this.t("curve.legend_saved")}</span>
              <span><i class="solid"></i>${this.t("curve.legend_draft")}</span>`
          : nothing}
      </div>
      ${draft
        ? html`<div class="preview">
            <p class="muted small">${this.t("curve.preview_hint")}</p>
            <label class="field">
              <span>${this.t("curve.offset")} <b>${formatNumber(draft.offset, lang, 1)} K</b></span>
              <input
                type="range"
                min="-5"
                max="5"
                step="0.5"
                .value=${String(draft.offset)}
                @input=${(e: Event) => this.setDraft({ offset: Number((e.target as HTMLInputElement).value) })}
              />
            </label>
            ${savedAt != null && draftAt != null
              ? html`<p>${this.t("curve.preview_effect", { outdoor: t(effectAt), saved: t(savedAt), draft: t(draftAt) })}</p>`
              : nothing}
            ${(this.draftAnswer?.problems ?? []).map(
              (key) => html`<p class="problem" role="alert">${this.t(`curve.problem.${key}`)}</p>`,
            )}
            <button class="text" @click=${() => this.setDraft({ design_outdoor: settings.design_outdoor, design_flow: settings.design_flow, offset: settings.offset })}>
              ${this.t("curve.reset")}
            </button>
            <p class="muted small">${this.t("curve.preview_note")}</p>
          </div>`
        : html`<dl>
            <dt>${this.t("curve.design_point")}</dt>
            <dd>${t(settings.design_outdoor)} → ${t(settings.design_flow)}</dd>
            <dt>${this.t("curve.room")}</dt>
            <dd>${settings.room_auto ? this.t("curve.room_auto", { value: t(this.room()) }) : t(settings.room)}</dd>
            <dt>${this.t("curve.offset")}</dt>
            <dd>${formatNumber(settings.offset, lang, 1)} K</dd>
            <dt>${this.t("curve.exponent")}</dt>
            <dd>${formatNumber(settings.exponent, lang, 2)}</dd>
            <dt>${this.t("curve.limits")}</dt>
            <dd>${t(settings.hard_min)} / ${t(settings.hard_max)}</dd>
            <dt>${this.t("curve.correction")}</dt>
            <dd>
              ${settings.comfort_correction
                ? this.t("curve.correction_on", { value: formatNumber(settings.correction_max_k, lang, 0) })
                : this.t("curve.correction_off")}
            </dd>
          </dl>`}
      ${this.error ? html`<p class="problem" role="alert">${this.error}</p>` : nothing}
    `);
  }

  private frame(body: unknown) {
    const settings = this.settings;
    return html`<section class="card">
      <div class="head">
        <h3>${this.t("curve.title")}</h3>
        ${settings?.entered
          ? html`<button class="outline" aria-pressed=${this.draft ? "true" : "false"} @click=${() => this.togglePreview()}>
              ${this.draft ? this.t("curve.preview_close") : this.t("curve.preview")}
            </button>`
          : nothing}
      </div>
      ${body}
    </section>`;
  }

  static styles = css`
    :host {
      display: block;
      --sb-curve: #2a78d6;
      --sb-now: #eb6834;
      --sb-past: #9c9a93;
    }
    .card {
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: var(--ha-card-box-shadow, none);
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      padding: 16px;
      box-sizing: border-box;
    }
    .head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
    }
    h3 {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
    }
    .muted {
      color: var(--secondary-text-color);
    }
    .small {
      font-size: 12px;
    }
    .center {
      text-align: center;
      margin-top: 4px;
    }
    .where {
      margin: 10px 0 12px;
      padding: 10px 12px;
      border-radius: 10px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.05));
    }
    .big {
      font-size: 22px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }
    .chart {
      display: flex;
      gap: 6px;
    }
    .yaxis {
      position: relative;
      width: 26px;
      flex: none;
      height: 280px;
    }
    .yaxis span {
      position: absolute;
      right: 0;
      transform: translateY(-50%);
      font-size: 11px;
      color: var(--secondary-text-color);
    }
    .plot-wrap {
      flex: 1;
      min-width: 0;
    }
    .plot {
      position: relative;
      height: 280px;
    }
    .plot svg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      overflow: visible;
    }
    .grid,
    .limit,
    .line,
    .saved {
      fill: none;
      vector-effect: non-scaling-stroke;
      stroke-linejoin: round;
      stroke-linecap: round;
    }
    .grid {
      stroke: var(--divider-color, rgba(0, 0, 0, 0.12));
      stroke-width: 1px;
    }
    .limit {
      stroke: var(--secondary-text-color);
      stroke-width: 1px;
      stroke-dasharray: 6 5;
    }
    .line {
      stroke: var(--sb-curve);
      stroke-width: 2.5px;
    }
    .saved {
      stroke: var(--secondary-text-color);
      stroke-width: 2px;
      stroke-dasharray: 6 5;
    }
    .past {
      position: absolute;
      width: 7px;
      height: 7px;
      margin: -3.5px 0 0 -3.5px;
      border-radius: 50%;
      background: var(--sb-past);
      opacity: 0.7;
      pointer-events: none;
    }
    .now {
      position: absolute;
      width: 16px;
      height: 16px;
      margin: -8px 0 0 -8px;
      border-radius: 50%;
      background: var(--sb-now);
      box-shadow: 0 0 0 3px var(--card-background-color, #fff), 0 0 0 4px var(--sb-now);
      pointer-events: none;
    }
    .handle {
      position: absolute;
      width: 28px;
      height: 28px;
      margin: -14px 0 0 -14px;
      border-radius: 50%;
      border: 0;
      padding: 0;
      background: var(--sb-curve);
      box-shadow: 0 0 0 4px var(--card-background-color, #fff), 0 0 0 5px var(--sb-curve), 0 4px 12px rgba(0, 0, 0, 0.25);
      cursor: grab;
      touch-action: none;
      z-index: 2;
    }
    .handle:focus-visible {
      outline: 3px solid var(--primary-text-color);
      outline-offset: 6px;
    }
    .limit-label {
      position: absolute;
      right: 2px;
      transform: translateY(-115%);
      font-size: 11px;
      color: var(--secondary-text-color);
      pointer-events: none;
    }
    .xaxis {
      position: relative;
      height: 16px;
      margin-top: 4px;
    }
    .xaxis span {
      position: absolute;
      transform: translateX(-50%);
      font-size: 11px;
      color: var(--secondary-text-color);
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 4px 14px;
      font-size: 12px;
      color: var(--secondary-text-color);
      margin: 8px 0 12px 32px;
    }
    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      display: inline-block;
    }
    .now-dot {
      background: var(--sb-now);
    }
    .past-dot {
      background: var(--sb-past);
    }
    .dash,
    .solid {
      display: inline-block;
      width: 16px;
      border-top: 2px solid var(--sb-curve);
    }
    .dash {
      border-top: 2px dashed var(--secondary-text-color);
    }
    dl {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 6px 16px;
      margin: 0;
    }
    dt {
      color: var(--secondary-text-color);
      font-size: 13px;
    }
    dd {
      margin: 0;
      font-weight: 600;
      font-size: 13px;
      text-align: right;
      font-variant-numeric: tabular-nums;
    }
    .preview {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .preview p {
      margin: 0;
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: 2px;
      font-size: 13px;
    }
    .field input {
      width: 100%;
      accent-color: var(--primary-color);
    }
    .problem {
      color: var(--error-color, #db4437);
      font-size: 13px;
    }
    button.outline,
    button.text {
      appearance: none;
      border-radius: 10px;
      min-height: 36px;
      padding: 0 14px;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
      background: transparent;
      color: var(--primary-color);
    }
    button.outline {
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.2));
    }
    button.outline[aria-pressed="true"] {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.05));
    }
    button.text {
      border: 0;
      align-self: flex-start;
    }
  `;
}

function messageOf(err: unknown): string {
  const message = (err as { message?: unknown })?.message;
  return typeof message === "string" ? message : String(err);
}

if (!customElements.get(CURVE_TAG)) {
  customElements.define(CURVE_TAG, SmartBoilerCurve);
}
