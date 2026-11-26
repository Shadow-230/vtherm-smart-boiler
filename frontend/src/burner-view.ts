// The Burner tab (docs/en/development/plans/plan-0.2-i10.md, I10.5): the monitor's burner
// metrics as tiles, its burns of the last 24 h on a timeline, and how long the heating burns
// lasted. The burns are the monitor's own (vtherm_smart_boiler/burns); nothing is judged here.
import { LitElement, css, html, nothing } from "lit";
import { histogram, minutesOf, recentBurns, veryShortShare, type BurnInfo, type BurnsAnswer } from "./burner";
import { formatNumber, numberOf } from "./format";
import { localize } from "./localize";
import { profileZone } from "./time";
import { clock, hourTicks } from "./timeline";
import type { HomeAssistant, Installation } from "./types";

export const BURNER_TAG = "vtherm-smart-boiler-burner";

const DAY_S = 86400;
const REFRESH_MS = 5 * 60000; // the monitor analyses every 5 minutes
const METRICS: [key: string, digits: number][] = [
  ["starts_per_hour", 1],
  ["median_burn", 0],
  ["short_burn_share", 0],
  ["burner_hours", 1],
  ["condensing_share", 0],
];

export class SmartBoilerBurner extends LitElement {
  static properties = {
    hass: { attribute: false },
    installation: { attribute: false },
    answer: { state: true },
    error: { state: true },
    hovered: { state: true },
  };

  declare hass?: HomeAssistant;
  declare installation?: Installation;
  declare answer: BurnsAnswer | null;
  declare error: string;
  /** The burn or the bucket the pointer is on: its text. */
  declare hovered: string;
  private timer: number | undefined;

  constructor() {
    super();
    this.answer = null;
    this.error = "";
    this.hovered = "";
  }

  connectedCallback(): void {
    super.connectedCallback();
    this.timer = window.setInterval(() => void this.fetchBurns(), REFRESH_MS);
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    window.clearInterval(this.timer);
  }

  protected firstUpdated(): void {
    void this.fetchBurns();
  }

  private async fetchBurns(): Promise<void> {
    if (!this.hass) return;
    try {
      this.answer = await this.hass.callWS<BurnsAnswer>({ type: "vtherm_smart_boiler/burns" });
      this.error = "";
    } catch (err) {
      const message = (err as { message?: unknown })?.message;
      this.error = this.t("burner.error", { message: typeof message === "string" ? message : String(err) });
    }
  }

  private t(key: string, values?: Record<string, string>): string {
    return localize(this.hass?.language, key, values);
  }

  private get language(): string {
    return this.hass?.locale?.language ?? this.hass?.language ?? "en";
  }

  private tiles() {
    const hass = this.hass as HomeAssistant;
    const installation = this.installation as Installation;
    const lang = this.language;
    const shortMin = formatNumber(installation.short_burn_min, lang, 0);
    return METRICS.flatMap(([key, digits]) => {
      const entity = hass.states[installation.entities[key] ?? ""];
      if (!entity) return [];
      const value = numberOf(entity.state);
      const unit = entity.attributes.unit_of_measurement;
      const shown = value == null ? "—" : `${formatNumber(value, lang, digits)}${typeof unit === "string" && unit !== "/h" ? ` ${unit}` : ""}`;
      // I13.5: beside the short burns' share, the share under 3 minutes.
      const under = key === "short_burn_share" ? veryShortShare(entity) : null;
      return [
        html`<div class="card tile">
          <div class="tile-label">${this.t(`burner.${key}`)}</div>
          <div class="tile-value">${shown}</div>
          <div class="muted small">${this.t(`burner.${key}_detail`, { value: shortMin })}</div>
          ${under == null
            ? nothing
            : html`<div class="muted small">${this.t("burner.under_3_min", { value: formatNumber(under, lang, 0) })}</div>`}
        </div>`,
      ];
    });
  }

  private burnText(burn: BurnInfo, lang: string): string {
    return this.t("burner.burn", {
      from: clock(burn.start * 1000, lang, profileZone(this.hass)),
      to: clock(burn.end * 1000, lang, profileZone(this.hass)),
      minutes: String(minutesOf(burn)),
      kind: this.t(`burner.${burn.kind === "ch" ? "heat" : burn.kind}`),
    });
  }

  render() {
    if (!this.hass || !this.installation) return nothing;
    const lang = this.language;
    const answer = this.answer;
    const now = Date.now() / 1000;
    const from = now - DAY_S;
    const burns = answer ? recentBurns(answer.burns, now, DAY_S) : [];
    const buckets = histogram(burns, this.installation.short_burn_min);
    const most = Math.max(4, ...buckets.map((b) => b.count));
    const shortCount = buckets.filter((b) => b.short).reduce((n, b) => n + b.count, 0);
    const share = (t: number) => `${(((Math.max(t, from) - from) / DAY_S) * 100).toFixed(3)}%`;
    const width = (burn: BurnInfo) =>
      `${Math.max(0.25, ((burn.end - Math.max(burn.start, from)) / DAY_S) * 100).toFixed(3)}%`;
    const count = (kind: string) => String(burns.filter((b) => b.kind === kind).length);
    const label = (from: number, to: number) =>
      to === Number.POSITIVE_INFINITY ? `${formatNumber(from, lang, 0)}+` : `${formatNumber(from, lang, 0)}–${formatNumber(to, lang, 0)}`;
    return html`
      <section class="tiles">${this.tiles()}</section>
      <section class="card">
        <div class="head">
          <h3>${this.t("burner.timeline")}</h3>
          <div class="legend">
            <span><i class="box ch"></i>${this.t("burner.heat")}</span>
            <span><i class="box dhw"></i>${this.t("burner.dhw")}</span>
            <span><i class="box unknown"></i>${this.t("burner.unknown")}</span>
          </div>
        </div>
        ${this.error
          ? html`<p class="error" role="alert">${this.error}</p>`
          : !answer
            ? nothing
            : answer.at == null
              ? html`<p class="muted">${this.t("burner.no_analysis")}</p>`
              : html`
                  <div
                    class="strip"
                    role="img"
                    aria-label=${this.t("burner.summary", {
                      count: String(burns.length), heat: count("ch"), dhw: count("dhw"), unknown: count("unknown"),
                    })}
                  >
                    ${Array.from({ length: 5 }, (_, i) => html`<span class="hour" style="left: ${(((i + 1) * 4) / 24) * 100}%"></span>`)}
                    ${burns.map(
                      (burn) => html`<span
                        class="burn ${burn.kind}"
                        style="left: ${share(burn.start)}; width: ${width(burn)}"
                        @mouseenter=${() => (this.hovered = this.burnText(burn, lang))}
                        @mouseleave=${() => (this.hovered = "")}
                      ></span>`,
                    )}
                  </div>
                  <div class="xaxis" aria-hidden="true">
                    ${hourTicks(from * 1000, now * 1000, this.offsetWidth < 560 ? 8 : 4, lang, profileZone(this.hass)).map(
                      (tick) => html`<span style="left: ${share(tick.t / 1000)}">${tick.label}</span>`,
                    )}
                  </div>
                  <p class="muted small hover" aria-live="polite">
                    ${this.hovered ||
                    (burns.length
                      ? this.t("burner.as_of", { time: clock(answer.at * 1000, lang, profileZone(this.hass)) })
                      : this.t("burner.none"))}
                  </p>
                `}
      </section>
      ${answer?.at != null
        ? html`<section class="card">
            <div class="head">
              <h3>${this.t("burner.lengths")}</h3>
              ${shortCount
                ? html`<span class="chip warn">${this.t("burner.short", {
                    count: String(shortCount),
                    value: formatNumber(this.installation.short_burn_min, lang, 0),
                  })}</span>`
                : nothing}
            </div>
            <p class="muted small">${this.t("burner.lengths_hint")}</p>
            <div class="bars" role="img" aria-label=${buckets.map((b) => this.t("burner.count", { label: label(b.from, b.to), count: String(b.count) })).join("; ")}>
              ${buckets.map(
                (b) => html`<div class="bar-cell">
                  <span class="bar-count">${b.count || ""}</span>
                  <span class="bar ${b.short ? "short" : ""}" style="height: ${((b.count / most) * 100).toFixed(1)}%"></span>
                </div>`,
              )}
            </div>
            <div class="bar-labels" aria-hidden="true">
              ${buckets.map((b) => html`<span>${label(b.from, b.to)}</span>`)}
            </div>
            <div class="muted small center">${this.t("burner.minutes")}</div>
          </section>`
        : nothing}
    `;
  }

  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      gap: 16px;
      --sb-ch: #2a78d6;
      --sb-dhw: #eb6834;
      --sb-unknown: #9c9a93;
      --sb-warn: #fab219;
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
    .tiles {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
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
    .head {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      justify-content: space-between;
      gap: 8px 16px;
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
    .center {
      text-align: center;
    }
    .error {
      color: var(--error-color, #db4437);
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 6px 14px;
      font-size: 12px;
      color: var(--secondary-text-color);
    }
    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .box {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 3px;
    }
    .ch {
      background: var(--sb-ch);
    }
    .dhw {
      background: var(--sb-dhw);
    }
    .unknown {
      background: var(--sb-unknown);
    }
    .strip {
      position: relative;
      height: 56px;
      border-radius: 6px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.06));
    }
    .hour {
      position: absolute;
      top: 0;
      bottom: 0;
      width: 1px;
      background: var(--divider-color, rgba(0, 0, 0, 0.12));
    }
    .burn {
      position: absolute;
      top: 6px;
      bottom: 6px;
      border-radius: 3px;
      min-width: 2px;
    }
    .burn:hover {
      outline: 2px solid var(--primary-text-color);
      outline-offset: 1px;
    }
    .xaxis {
      position: relative;
      height: 16px;
      margin-top: 6px;
    }
    .xaxis span {
      position: absolute;
      transform: translateX(-50%);
      font-size: 11px;
      color: var(--secondary-text-color);
      white-space: nowrap;
    }
    .hover {
      min-height: 16px;
      margin: 8px 0 0;
    }
    .chip {
      font-size: 12px;
      font-weight: 600;
      padding: 3px 10px;
      border-radius: 999px;
    }
    .chip.warn {
      background: rgba(250, 178, 25, 0.18);
      color: var(--primary-text-color);
      box-shadow: inset 0 0 0 1px var(--sb-warn);
    }
    .bars {
      position: relative;
      height: 180px;
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: minmax(0, 1fr);
      gap: 10px;
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.2));
      margin-top: 12px;
    }
    .bar-cell {
      position: relative;
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      align-items: stretch;
    }
    .bar {
      display: block;
      border-radius: 4px 4px 0 0;
      background: var(--sb-ch);
      min-height: 0;
    }
    .bar.short {
      background: var(--sb-warn);
    }
    .bar-count {
      text-align: center;
      font-size: 12px;
      font-weight: 600;
      margin-bottom: 2px;
      font-variant-numeric: tabular-nums;
    }
    .bar-labels {
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: minmax(0, 1fr);
      gap: 10px;
      font-size: 11px;
      color: var(--secondary-text-color);
      text-align: center;
      margin-top: 6px;
    }
  `;
}

if (!customElements.get(BURNER_TAG)) {
  customElements.define(BURNER_TAG, SmartBoilerBurner);
}
