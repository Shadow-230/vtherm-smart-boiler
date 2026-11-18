// The last 24 h card (docs/en/development/plans/plan-0.2-i10.md, I10.3d): the water the plugin
// asked, flow and return, the burns, and a scrubber with play that picks the moment the whole
// overview shows. It tells the overview the moment with an `at-change` event: a time, or `null`
// for now.
import { LitElement, css, html, nothing, svg } from "lit";
import { formatTemperature } from "./format";
import { localize } from "./localize";
import {
  clock,
  hourTicks,
  numbers,
  rangeOf,
  stepPath,
  known,
  stretches,
  valueAt,
  type History,
  type Series,
} from "./timeline";
import type { HomeAssistant, Installation } from "./types";

export const TIMELINE_TAG = "vtherm-smart-boiler-timeline";

const W = 1000;
const H = 170;
const STEPS = 720; // the scrubber's steps over the day: two minutes each
const TICK_MS = 100;

export class SmartBoilerTimeline extends LitElement {
  static properties = {
    hass: { attribute: false },
    installation: { attribute: false },
    history: { attribute: false },
    from: { type: Number },
    to: { type: Number },
    at: { attribute: false },
    status: { attribute: false },
    alone: { attribute: false },
    playing: { state: true },
    speed: { state: true },
  };

  declare hass?: HomeAssistant;
  declare installation?: Installation;
  declare history: History | null;
  declare from: number;
  declare to: number;
  declare at: number | null;
  /** "loading", "ready", or an error's text. */
  declare status: string;
  /** Shown on its own, as a card: the moment picked shows here only. */
  declare alone: boolean;
  declare playing: boolean;
  declare speed: number;
  private timer: number | undefined;

  constructor() {
    super();
    this.history = null;
    this.from = 0;
    this.to = 0;
    this.at = null;
    this.status = "loading";
    this.alone = false;
    this.playing = false;
    this.speed = 1;
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    this.stop();
  }

  private t(key: string, values?: Record<string, string>): string {
    return localize(this.hass?.language, key, values);
  }

  private get language(): string {
    return this.hass?.locale?.language ?? this.hass?.language ?? "en";
  }

  private emit(at: number | null): void {
    this.dispatchEvent(new CustomEvent("at-change", { detail: at, bubbles: true, composed: true }));
  }

  private stepOf(at: number | null): number {
    if (at == null || this.to <= this.from) return STEPS;
    return Math.round(((at - this.from) / (this.to - this.from)) * STEPS);
  }

  private timeOf(step: number): number | null {
    return step >= STEPS ? null : this.from + ((this.to - this.from) * step) / STEPS;
  }

  private stop(): void {
    if (this.timer !== undefined) window.clearInterval(this.timer);
    this.timer = undefined;
    this.playing = false;
  }

  private togglePlay(): void {
    if (this.playing) {
      this.stop();
      return;
    }
    let step = this.at == null ? 0 : this.stepOf(this.at);
    this.playing = true;
    this.emit(this.timeOf(step));
    this.timer = window.setInterval(() => {
      step += this.speed;
      if (step >= STEPS) {
        this.stop();
        this.emit(null);
      } else {
        this.emit(this.timeOf(step));
      }
    }, TICK_MS);
  }

  render() {
    if (!this.installation || !this.hass) return nothing;
    const lang = this.language;
    const body =
      this.status === "loading"
        ? html`<p class="muted">${this.t("timeline.loading")}</p>`
        : this.status !== "ready"
          ? html`<p class="error" role="alert">${this.t("timeline.error", { message: this.status })}</p>`
          : this.chart(lang);
    return html`<section class="card">
      <div class="head">
        <div>
          <h3>${this.t("timeline.title")}</h3>
          <div class="muted small">${this.t(this.alone ? "timeline.hint_alone" : "timeline.hint")}</div>
        </div>
        <div class="controls">
          <span class="time">${this.at == null ? "" : clock(this.at, lang)}</span>
          <button
            class="play"
            aria-label=${this.playing ? this.t("timeline.pause") : this.t("timeline.play")}
            ?disabled=${this.status !== "ready"}
            @click=${() => this.togglePlay()}
          >
            ${this.playing
              ? html`<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1"></rect><rect x="14" y="5" width="4" height="14" rx="1"></rect></svg>`
              : html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"></path></svg>`}
          </button>
          ${[1, 4].map(
            (speed) => html`<button
              class="pill ${this.speed === speed ? "on" : ""}"
              aria-pressed=${this.speed === speed ? "true" : "false"}
              @click=${() => (this.speed = speed)}
            >
              ×${speed}
            </button>`,
          )}
          <button
            class="pill"
            @click=${() => {
              this.stop();
              this.emit(null);
            }}
          >
            ${this.t("timeline.now")}
          </button>
        </div>
      </div>
      ${body}
    </section>`;
  }

  private chart(lang: string) {
    const installation = this.installation as Installation;
    const history = this.history ?? {};
    const { from, to } = this;
    const signal = (name: string) => history[installation.signals[name] ?? ""];
    const own = (key: string) => history[installation.entities[key] ?? ""];
    const requested = own("control_setpoint")
      ? numbers(own("control_setpoint"), "requested")
      : numbers(own("control_state"), "target");
    const flow = numbers(signal("flow"));
    const ret = numbers(signal("return"));
    if (!known(requested) && !known(flow) && !known(ret) && !signal("flame")) {
      return html`<p class="muted">${this.t("timeline.no_history")}</p>`;
    }
    const [low, high] = rangeOf([requested, flow, ret]);
    const path = (series: Series) => stepPath(series, from, to, low, high, W, H);
    const share = (t: number) => `${(((t - from) / (to - from)) * 100).toFixed(3)}%`;
    const width = (a: number, b: number) => `${Math.max(0.25, ((b - a) / (to - from)) * 100).toFixed(3)}%`;
    const hotWater = signal("dhw_active");
    const heat = stretches(signal("flame"), from, to, (s) => s === "on");
    const water = stretches(hotWater, from, to, (s) => s === "on");
    const grid: string[] = [];
    for (let v = low; v <= high; v += 10) grid.push(`M0 ${(((high - v) / (high - low)) * H).toFixed(1)}H${W}`);
    const cursor = share(this.at ?? to);
    const moment = this.at ?? to;
    const last = (series: Series) => valueAt(series, moment);
    return html`
      <div class="legend">
        ${known(requested) ? html`<span><i class="line dash"></i>${this.t("timeline.legend_requested")} ${formatTemperature(last(requested), lang)}</span>` : nothing}
        ${known(flow) ? html`<span><i class="line flow"></i>${this.t("timeline.legend_flow")} ${formatTemperature(last(flow), lang)}</span>` : nothing}
        ${known(ret) ? html`<span><i class="line ret"></i>${this.t("timeline.legend_return")} ${formatTemperature(last(ret), lang)}</span>` : nothing}
        ${heat.length ? html`<span><i class="box heat"></i>${this.t("timeline.legend_heat")}</span>` : nothing}
        ${water.length ? html`<span><i class="box hot"></i>${this.t("timeline.legend_hot_water")}</span>` : nothing}
      </div>
      <div class="chart">
        <div class="yaxis" aria-hidden="true">
          ${Array.from({ length: (high - low) / 10 + 1 }, (_, i) => low + i * 10).map(
            (v) => html`<span style="top: ${(((high - v) / (high - low)) * 100).toFixed(2)}%">${v}</span>`,
          )}
        </div>
        <div class="plot-wrap">
          <div class="plot" role="img" aria-label=${this.t("timeline.title")}>
            <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
              ${svg`
                <path class="grid" d=${grid.join("")}></path>
                <path class="ret" d=${path(ret)}></path>
                <path class="flow" d=${path(flow)}></path>
                <path class="requested" d=${path(requested)}></path>
              `}
            </svg>
            <span class="cursor" style="left: ${cursor}"></span>
          </div>
          <div class="strip">
            ${heat.map(([a, b]) => html`<span class="burn heat" style="left: ${share(a)}; width: ${width(a, b)}"></span>`)}
            ${water.map(([a, b]) => html`<span class="burn hot" style="left: ${share(a)}; width: ${width(a, b)}"></span>`)}
            <span class="cursor" style="left: ${cursor}"></span>
          </div>
          <input
            class="scrub"
            type="range"
            min="0"
            max=${STEPS}
            step="1"
            .value=${String(this.stepOf(this.at))}
            aria-label=${this.t("timeline.slider")}
            aria-valuetext=${this.at == null ? this.t("timeline.now") : clock(this.at, lang)}
            @input=${(e: Event) => {
              this.stop();
              this.emit(this.timeOf(Number((e.target as HTMLInputElement).value)));
            }}
          />
          <div class="xaxis" aria-hidden="true">
            ${hourTicks(from, to, this.offsetWidth < 560 ? 8 : 4, lang).map(
              (tick) => html`<span style="left: ${share(tick.t)}">${tick.label}</span>`,
            )}
          </div>
        </div>
      </div>
    `;
  }

  static styles = css`
    :host {
      display: block;
      --sb-requested: #2a78d6;
      --sb-flow: #eb6834;
      --sb-return: #1baf7a;
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
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px 16px;
      margin-bottom: 10px;
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
    .error {
      color: var(--error-color, #db4437);
    }
    .controls {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .time {
      font-weight: 700;
      font-variant-numeric: tabular-nums;
      min-width: 48px;
      text-align: right;
    }
    .play {
      appearance: none;
      border: 0;
      width: 44px;
      height: 44px;
      border-radius: 50%;
      background: var(--primary-color);
      color: var(--text-primary-color, #fff);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }
    .play:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }
    .play svg {
      width: 20px;
      height: 20px;
      fill: currentColor;
    }
    .pill {
      appearance: none;
      border: 0;
      font: inherit;
      font-size: 13px;
      font-weight: 600;
      min-height: 36px;
      padding: 0 12px;
      border-radius: 999px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.06));
      color: var(--primary-text-color);
      cursor: pointer;
    }
    .pill.on {
      background: var(--primary-color);
      color: var(--text-primary-color, #fff);
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 6px 16px;
      font-size: 12px;
      color: var(--secondary-text-color);
      margin-bottom: 8px;
    }
    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .line {
      display: inline-block;
      width: 14px;
      border-top: 2px solid;
    }
    .line.dash {
      border-top-style: dashed;
      border-color: var(--sb-requested);
    }
    .line.flow {
      border-color: var(--sb-flow);
    }
    .line.ret {
      border-color: var(--sb-return);
    }
    .box {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 3px;
    }
    .box.heat,
    .burn.heat {
      background: var(--sb-requested);
    }
    .box.hot,
    .burn.hot {
      background: var(--sb-flow);
    }
    .chart {
      display: flex;
      gap: 8px;
    }
    .yaxis {
      position: relative;
      width: 26px;
      flex: none;
      height: 170px;
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
      height: 170px;
    }
    .plot svg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
    }
    .grid,
    .requested,
    .flow,
    .ret {
      fill: none;
      vector-effect: non-scaling-stroke;
      stroke-linejoin: round;
    }
    .grid {
      stroke: var(--divider-color, rgba(0, 0, 0, 0.12));
      stroke-width: 1px;
    }
    .requested {
      stroke: var(--sb-requested);
      stroke-width: 2px;
      stroke-dasharray: 6 4;
    }
    .flow {
      stroke: var(--sb-flow);
      stroke-width: 2px;
    }
    .ret {
      stroke: var(--sb-return);
      stroke-width: 2px;
    }
    .strip {
      position: relative;
      height: 26px;
      margin-top: 8px;
      border-radius: 6px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.06));
    }
    .burn {
      position: absolute;
      top: 5px;
      bottom: 5px;
      border-radius: 3px;
      min-width: 2px;
    }
    .cursor {
      position: absolute;
      top: -4px;
      bottom: -4px;
      width: 2px;
      margin-left: -1px;
      background: var(--primary-text-color);
      border-radius: 1px;
      pointer-events: none;
    }
    .scrub {
      width: 100%;
      margin: 0;
      height: 28px;
      accent-color: var(--primary-color);
      cursor: pointer;
    }
    .xaxis {
      position: relative;
      height: 16px;
    }
    .xaxis span {
      position: absolute;
      transform: translateX(-50%);
      font-size: 11px;
      color: var(--secondary-text-color);
      white-space: nowrap;
    }
  `;
}

if (!customElements.get(TIMELINE_TAG)) {
  customElements.define(TIMELINE_TAG, SmartBoilerTimeline);
}
